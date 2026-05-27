"""Normalize DynamoDB stream / EventBridge payloads into LangGraph initial state."""

from __future__ import annotations

import json
import logging
from typing import Any

from src.config import Settings

logger = logging.getLogger(__name__)


def extract_dispute_id_from_sk(sk: str) -> str:
    marker = "#DISPUTE#"
    if marker not in sk:
        return ""
    return sk.split(marker, 1)[1]


def keys_from_detail(detail: dict[str, Any]) -> tuple[str, str]:
    keys = detail.get("keys") or {}
    if not isinstance(keys, dict):
        return "", ""
    pk = str(keys.get("PK") or keys.get("pk") or "").strip()
    sk = str(keys.get("SK") or keys.get("sk") or "").strip()
    return pk, sk


def detail_to_analysis_payload(detail: dict[str, Any]) -> dict[str, Any]:
    """Map EventBridge dispute stream detail to the shape expected by extract_case_context."""
    pk, sk = keys_from_detail(detail)
    new_image = detail.get("newImage") or detail.get("NewImage") or {}
    if not isinstance(new_image, dict):
        new_image = {}
    payload: dict[str, Any] = {"NewImage": new_image}
    if pk:
        payload["PK"] = pk
    if sk:
        payload["SK"] = sk
    return payload


def is_prepared_analysis_state(payload: dict[str, Any]) -> bool:
    """True when the payload already matches AnalysisAgentState identity fields."""
    return bool(str(payload.get("source_pk") or "").strip()) and bool(
        str(payload.get("source_sk") or "").strip()
    )


def extract_case_context(
    payload: dict[str, Any],
    settings: Settings,
    *,
    event_name: str | None = None,
) -> dict[str, Any]:
    """Pull identifiers used for PK/SK and workflow correlation."""

    def g(*names: str) -> str:
        for n in names:
            v = payload.get(n)
            if v is not None and str(v).strip():
                return str(v).strip()
        return ""

    pk = g("PK", "pk", "partitionKey")
    sk = g("SK", "sk", "sortKey")
    logger.info("extract_case_context: PK=%s SK=%s", pk, sk)
    new_image = payload.get("NewImage", {})
    if not new_image:
        logger.warning("No NewImage found in payload: %s", payload)
        raise ValueError("No NewImage found in payload. Path is missing.")
    dispute_status = new_image.get("disputeStatus", "")
    if str(dispute_status).lower() != "open":
        logger.warning("Dispute status not open: %s", dispute_status)
        raise ValueError(f"Dispute status not open: {dispute_status}")
    account_id = new_image.get("accountId", "")
    account_number = new_image.get("accountNumber", "")
    case_id = new_image.get("caseId", "")
    dispute_id = new_image.get("acdvId", "")
    dispute_info = new_image.get("disputeInfo", {})
    consumer_info = new_image.get("consumerInfo", {})
    account_info = new_image.get("accountInfo", {})
    source = str(new_image.get("source"))
    image_dispute_code1 = new_image.get("originatorDisputeCode1", 0)
    image_dispute_code2 = new_image.get("originatorDisputeCode2", 0)
    dispute_uuid = extract_dispute_id_from_sk(sk)
    attachment_available = bool(new_image.get("imageReceived", False))
    if str(source).lower() not in settings.source_list:
        logger.warning("Source not supported: %s", source)
        return {
            "workflow_fields_persisted": False,
            "action_log": [
                f"Source not supported: {source}, source list: {settings.source_list}"
            ],
        }

    return {
        "account_id": account_id,
        "case_id": case_id,
        "dispute_id": dispute_id,
        "dispute_uuid": dispute_uuid,
        "account_no": account_number,
        "source_pk": pk,
        "source_sk": sk,
        "source": source,
        "analysis_model": settings.analysis_model,
        "judgment_model": settings.judgment_model,
        "action_log": [f"initial_dual_state_from_stream_view: eventName={event_name!r}"],
        "dynamodb_error": "",
        "Openai_usage": {},
        "value": "",
        "confidenceScore": 0,
        "api_response_status": "SUCCESS",
        "creditor_documents": [],
        "disputeInfo": dispute_info,
        "consumerInfo": consumer_info,
        "accountInfo": account_info,
        "imageDisputeCode1": image_dispute_code1,
        "imageDisputeCode2": image_dispute_code2,
        "attachmentAvailable": attachment_available,
    }


def prepare_initial_state_for_graph(
    payload: dict[str, Any],
    settings: Settings,
    *,
    event_name: str | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """
    Normalize an AgentCore/Lambda invocation into graph initial state.

    Returns ``(initial_state, skip_response)``. When ``skip_response`` is set, do not run the graph.
    Raises ``ValueError`` when the payload cannot be interpreted.
    """
    if is_prepared_analysis_state(payload):
        return payload, None

    stream_payload = payload
    detail = payload.get("detail")
    if isinstance(detail, str):
        try:
            detail = json.loads(detail)
        except json.JSONDecodeError as e:
            raise ValueError("EventBridge detail field is not valid JSON") from e
    if isinstance(detail, dict):
        stream_payload = detail_to_analysis_payload(detail)
        event_name = event_name or str(detail.get("eventName") or "INSERT")

    if stream_payload.get("NewImage"):
        initial_state = extract_case_context(
            stream_payload, settings, event_name=event_name
        )
        if initial_state.get("workflow_fields_persisted") is False:
            return None, {
                "status": "skipped",
                "action_log": initial_state.get("action_log", []),
            }
        return initial_state, None

    raise ValueError(
        "Payload must include prepared workflow fields (source_pk, source_sk) "
        "or a DynamoDB stream shape with NewImage (or EventBridge detail with newImage)."
    )
