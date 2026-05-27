"""AWS Lambda entry for dispute analysis (SQS agentic FIFO and optional DynamoDB stream)."""

from __future__ import annotations

import json
import logging
from typing import Any, Mapping

from boto3.dynamodb.types import TypeDeserializer

from src.analysis_agent.langgraph.graph import build_invoke_graph
from src.analysis_agent.payload import (
    detail_to_analysis_payload,
    prepare_initial_state_for_graph,
)
from src.config import get_settings

logger = logging.getLogger(__name__)

DESERIALIZER = TypeDeserializer()

# Matches disputes-core-invokeAgenticAI (disputes.case.created.agentic on INSERT from stream Lambda).
ANALYSIS_FIFO_DETAIL_TYPES = frozenset({"disputes.case.created.agentic"})


def _configure_lambda_logging() -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for handler in root.handlers:
        handler.setLevel(logging.INFO)


_configure_lambda_logging()


def unmarshall_item(item: Mapping[str, Any]) -> dict[str, Any]:
    return {key: DESERIALIZER.deserialize(value) for key, value in item.items()}


def _parse_eventbridge_envelope(body: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
    try:
        envelope = json.loads(body)
    except json.JSONDecodeError:
        logger.warning("SQS message body is not valid JSON")
        return None
    if not isinstance(envelope, dict):
        return None

    detail = envelope.get("detail")
    if isinstance(detail, str):
        try:
            detail = json.loads(detail)
        except json.JSONDecodeError:
            logger.warning("EventBridge detail field is not valid JSON")
            return None
    if not isinstance(detail, dict):
        logger.warning("EventBridge envelope missing detail object")
        return None
    return envelope, detail


def _should_run_analysis(*, event_name: str | None, detail_type: str | None) -> bool:
    if detail_type and detail_type not in ANALYSIS_FIFO_DETAIL_TYPES:
        return False
    return event_name in (None, "INSERT")


def _process_analysis_payload(payload: dict[str, Any], *, event_name: str | None) -> bool:
    """Run the analysis graph for one dispute payload. Returns True if invoked."""
    settings = get_settings()
    initial_state, skip_response = prepare_initial_state_for_graph(
        payload, settings, event_name=event_name
    )
    if skip_response is not None:
        logger.info("Skipping analysis: %s", skip_response.get("action_log"))
        return False
    if initial_state is None:
        return False
    build_invoke_graph(initial_state)
    return True


def _process_dynamodb_stream_record(record: dict[str, Any]) -> bool:
    if record.get("eventName") != "INSERT":
        return False

    dynamodb = record.get("dynamodb")
    if not dynamodb:
        logger.warning("DynamoDB section missing for record: %s", record)
        return False

    try:
        new_image = unmarshall_item(dynamodb.get("NewImage") or {})
    except Exception:
        logger.exception("Failed to unmarshall NewImage")
        return False

    pk = ""
    sk = ""
    keys = dynamodb.get("Keys")
    if keys:
        unmarshalled_keys = unmarshall_item(keys)
        pk = str(unmarshalled_keys.get("PK", ""))
        sk = str(unmarshalled_keys.get("SK", ""))

    payload = {"NewImage": new_image, "PK": pk, "SK": sk}
    return _process_analysis_payload(payload, event_name=record.get("eventName"))


def _record_item_identifier(record: dict[str, Any]) -> str:
    """SQS partial-batch failure identifier (messageId)."""
    return str(record.get("messageId") or record.get("eventID") or "")


def _process_single_record(record: dict[str, Any]) -> bool:
    """Dispatch one event record. Returns True when analysis was invoked."""
    event_source = record.get("eventSource")
    if event_source == "aws:sqs":
        return _process_sqs_record(record)
    if event_source == "aws:dynamodb":
        return _process_dynamodb_stream_record(record)
    logger.warning("Unknown eventSource: %s", event_source)
    return False


def _process_sqs_record(record: dict[str, Any]) -> bool:
    body = record.get("body")
    if not isinstance(body, str) or not body.strip():
        logger.warning("SQS record missing body")
        return False

    parsed = _parse_eventbridge_envelope(body)
    if parsed is None:
        return False

    envelope, detail = parsed
    detail_type = envelope.get("detail-type") or envelope.get("detail_type") or ""
    entity_type = str(detail.get("entityType", "")).upper()
    if entity_type and entity_type != "DISPUTE":
        logger.info("Skipping non-DISPUTE entityType=%s", entity_type)
        return False

    if detail_type and detail_type not in ANALYSIS_FIFO_DETAIL_TYPES:
        logger.info("Skipping detail-type=%s (not routed to dispute-agent.fifo)", detail_type)
        return False

    event_name = str(detail.get("eventName") or "INSERT")
    if not _should_run_analysis(event_name=event_name, detail_type=detail_type or None):
        logger.info(
            "Skipping analysis for detail-type=%s eventName=%s",
            detail_type,
            event_name,
        )
        return False

    payload = detail_to_analysis_payload(detail)
    return _process_analysis_payload(payload, event_name=event_name)


def dynamo_stream_event_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    Invoked by SQS (dispute-agent.fifo) and optionally DynamoDB stream.

    SQS messages are EventBridge envelopes from disputes-core-invokeAgenticAI
    (detail-type disputes.case.created.agentic on DisputeCore INSERT).

    Processes every record in the batch. Per-record failures are logged and counted;
    successful records are not rolled back when another record fails. Failed SQS
    messages are not reported in ``batchItemFailures`` so they are not retried.
    """
    records = event.get("Records", [])
    if not records:
        logger.warning("No records found in event.")
        return {"processed": 0, "failed": 0, "skipped": 0, "total": 0}

    processed = 0
    failed = 0
    skipped = 0

    for record in records:
        item_id = _record_item_identifier(record)
        try:
            if _process_single_record(record):
                processed += 1
                logger.info(
                    "Record succeeded itemIdentifier=%s eventSource=%s",
                    item_id or "(unknown)",
                    record.get("eventSource"),
                )
            else:
                skipped += 1
                logger.info(
                    "Record skipped itemIdentifier=%s eventSource=%s",
                    item_id or "(unknown)",
                    record.get("eventSource"),
                )
        except Exception:
            failed += 1
            logger.exception(
                "Record failed (no retry) itemIdentifier=%s eventSource=%s",
                item_id or "(unknown)",
                record.get("eventSource"),
            )

    total = len(records)
    logger.info(
        "Batch complete: total=%d processed=%d failed=%d skipped=%d",
        total,
        processed,
        failed,
        skipped,
    )

    return {
        "processed": processed,
        "failed": failed,
        "skipped": skipped,
        "total": total,
    }
