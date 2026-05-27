"""LangGraph nodes: ingest, dual LLM analysis, DynamoDB, HITL, retrain, and human-only patch."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from collections.abc import Callable
from typing import Any, Literal

from src.analysis_agent.case_documents import fetch_case_documents_storage_url
from src.analysis_agent.database.db_utils import (
    DisputeRecordNotFoundError,
    assert_dispute_record_exists,
    put_item_with_retry,
    query_items_by_pk_and_sk_prefix_with_retry,
    update_item_with_retry,
    decrypt_value,
)
from src.analysis_agent.document_ingest import (
    copy_s3_object_uri_to_uri,
    download_s3_json_object,
)
from src.analysis_agent.langgraph.state import AnalysisAgentState
from src.analysis_agent.retry import RetriesExhaustedError, call_with_retry
from src.analysis_agent.utilities import invoke_agent_analysis, pdf_ingestion, _dedupe_strings
from src.config import get_settings, Settings
from src.graph_node_logging import log_node_finished, log_node_skipped, log_node_started
from pathlib import Path

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
DISPUTE_STATUS_IN_REVIEW = "IN_REVIEW"
DISPUTE_STATUS_VERIFIED = "ANALYZING"


def _as_string_list(value: Any) -> list[str]:
    if isinstance(value, list | tuple | set):
        return _dedupe_strings([str(item or "") for item in value])
    text = str(value or "").strip()
    return [text] if text else []


def _document_staging_prefix(
    state: AnalysisAgentState,
    settings: Settings,
    *,
    folder_name: str,
) -> str:
    """Build the case-analysis S3 prefix used to stage PDFs before OpenAI upload."""
    bucket = settings.case_dispute_analysis_s3_bucket.strip()
    base_prefix = settings.case_dispute_analysis_s3_prefix.strip("/")
    dispute_or_case_id = str(state.get("dispute_uuid","")).strip()
    if not bucket:
        raise ValueError("case_dispute_analysis_s3_bucket is empty")
    if not dispute_or_case_id:
        raise ValueError("dispute_id or case_id is required to stage documents")

    key_parts = [part for part in (base_prefix, dispute_or_case_id, folder_name) if part]
    key_prefix = "/".join(part.strip("/") for part in key_parts)
    return f"s3://{bucket}/{key_prefix}/"


def _copy_documents_to_staging(
    state: AnalysisAgentState,
    settings: Settings,
    source_uris: list[str],
    destination_s3_uri: str,
    operation: str,
) -> tuple[str, list[str]]:
    """Copy source PDFs into the analysis bucket and return the staging prefix + copied URIs."""
    destination_s3_uri = str(destination_s3_uri or "").strip()
    logger.info("_copy_documents_to_staging: destination_s3_uri: %s", destination_s3_uri)
    source_uris = _dedupe_strings(source_uris)
    if not destination_s3_uri:
        raise ValueError(f"{operation}: destination S3 URI is empty")
    if not source_uris:
        logger.info("%s: no source documents to copy", operation)
        return destination_s3_uri, []

    def _copy() -> list[str]:
        return copy_s3_object_uri_to_uri(
            source_uris,
            destination_s3_uri,
            aws_region=settings.aws_region,
        )

    logger.info(
        "%s: copying %d document(s) to %s",
        operation,
        len(source_uris),
        destination_s3_uri,
    )
    copied_uris = call_with_retry(
        _copy,
        operation=operation,
        state=state,
        settings=settings,
    )
    logger.info(
        "%s: copied %d document(s) to %s",
        operation,
        len(copied_uris),
        destination_s3_uri,
    )
    return destination_s3_uri, copied_uris


def _update_dispute_status_dynamo(
    state: AnalysisAgentState,
    settings: Settings,
    dispute_status: str,
    log_prefix: str,
) -> dict[str, Any]:
    """Update ``disputeStatus`` on the source dispute row."""
    if not (settings.aws_dynamodb_table or "").strip():
        return {
            "workflow_fields_persisted": False,
            "action_log": [f"{log_prefix}: AWS_DYNAMODB_TABLE not set; skip"],
        }

    pk = state.get("source_pk")
    sk = state.get("source_sk")
    logger.info("_update_dispute_status_dynamo: pk: %s, sk: %s , dispute uuid: %s", pk, sk, state.get("dispute_uuid"))
    if not pk or not sk:
        return {
            "workflow_fields_persisted": False,
            "action_log": [
                f"{log_prefix}: missing PK/SK (source_pk/sk or account/case/dispute ids)"
            ],
        }

    attribute_updates: dict[str, Any] = {
        "disputeStatus": dispute_status,
    }
    logger.info("_update_dispute_status_dynamo: pk: %s, sk: %s", pk, sk)
    try:
        update_item_with_retry(
            pk=pk,
            sk=sk,
            attribute_updates=attribute_updates,
            state=state,
            settings=settings,
        )
    except RetriesExhaustedError as e:
        return {
            "dynamodb_error": str(e),
            "workflow_fields_persisted": False,
            "action_log": [f"{log_prefix}: FAILED {e}"],
        }
    except Exception as e:
        logger.exception("%s failed", log_prefix)
        return {
            "dynamodb_error": str(e),
            "workflow_fields_persisted": False,
            "action_log": [f"{log_prefix}: FAILED {e}"],
        }

    return {
        "workflow_fields_persisted": True,
        "action_log": [
            f"{log_prefix}: disputeStatus={dispute_status!r} pk={pk} sk={sk}"
        ],
    }


def update_status_dynamo_verified(state: AnalysisAgentState) -> dict[str, Any]:
    """Set ``disputeStatus`` to analyzing after confirming the source row exists."""
    settings = get_settings()
    table = (settings.aws_dynamodb_table or "").strip()
    if not table:
        raise ValueError("update_status_dynamo_verified: AWS_DYNAMODB_TABLE is not configured")

    pk = str(state.get("source_pk") or "").strip()
    sk = str(state.get("source_sk") or "").strip()
    logger.info("update_status_dynamo_verified: pk: %s, sk: %s", pk, sk)
    if not pk or not sk:
        raise DisputeRecordNotFoundError(
            "update_status_dynamo_verified: missing source_pk or source_sk on workflow state"
        )

    assert_dispute_record_exists(pk=pk, sk=sk, state=state, settings=settings)

    return _update_dispute_status_dynamo(
        state,
        settings=settings,
        dispute_status=DISPUTE_STATUS_VERIFIED,
        log_prefix="update_status_dynamo_verified",
    )


def fetch_dispute_details_from_dynamo(state: AnalysisAgentState):
    """
    Fetch the source dispute row and store it in ``dispute_details``.

    Uses:
    ``PK = ACCOUNT#<accountId>``
    ``SK begins_with CASE#<accountNumber>#DISPUTE#`` when the full SK is not available.
    """
    account_no = str(state.get("account_no") or "").strip()
    dispute_uuid = str(state.get("dispute_uuid") or "").strip()
    logger.info("fetch_dispute_details_from_dynamo: account_no: %s, dispute_uuid: %s", account_no, dispute_uuid)

    if not account_no:
        msg = (
            "fetch_dispute_details_from_dynamo: missing account_no"
        )
        return {"workflow_error": msg, "action_log": [msg]}
    logger.info("fetch_dispute_details_from_dynamo: source_pk: %s", state.get("source_pk"))
    pk = str(state.get("source_pk") or "").strip()
    if not pk:
        return {
            "workflow_error": "fetch_dispute_details_from_dynamo: missing source_pk",
            "action_log": ["fetch_dispute_details_from_dynamo: missing source_pk"],
        }
    sk_prefix = f"CASE#{account_no}#DISPUTE#{dispute_uuid}#ATTACHMENT#"
    settings = get_settings()
    logger.info("fetch_dispute_details_from_dynamo: sk_prefix: %s", sk_prefix)
    try:
        items = query_items_by_pk_and_sk_prefix_with_retry(
            pk=pk,
            sk_prefix=sk_prefix,
            state=state,
            settings=settings,
        )
        item = items[0] if items else None
    except RetriesExhaustedError as e:
        logger.exception("fetch_dispute_details_from_dynamo: retries exhausted")
        return {
            "workflow_error": str(e),
            "dynamodb_error": str(e),
            "action_log": [f"fetch_dispute_details_from_dynamo: FAILED {e}"],
        }
    except Exception as e:
        logger.exception("fetch_dispute_details_from_dynamo failed")
        return {
            "workflow_error": str(e),
            "dynamodb_error": str(e),
            "action_log": [f"fetch_dispute_details_from_dynamo: FAILED {e}"],
        }
    attachment_available = bool(state.get("attachmentAvailable"))
    logger.info(
        "fetch_dispute_details_from_dynamo: items=%s item_found=%s attachmentAvailable=%s",
        len(items),
        item is not None,
        attachment_available,
    )
    if not item:
        if attachment_available:
            msg = f"fetch_dispute_details_from_dynamo: item not found pk={pk} sk={sk_prefix}"
            return {"workflow_error": msg, "action_log": [msg]}
        return {
            "consumer_document_s3_uris": [],
            "action_log": [
                "fetch_dispute_details_from_dynamo: no attachment row; continuing without consumer documents"
            ],
        }

    sk = str(item.get("SK") or sk_prefix).strip()
    converted_path = str(item.get("convertedFilePath") or "").strip()
    consumer_document_s3_uris = [converted_path] if converted_path else []
    return {
        "consumer_document_s3_uris": consumer_document_s3_uris,
        "attachment_details": item,
        "action_log": [
            f"fetch_dispute_details_from_dynamo: loaded dispute details pk={pk} sk={sk}"
        ],
    }


def has_workflow_error(state: AnalysisAgentState) -> bool:
    """True when a prior node recorded a failure that should stop the workflow."""
    if (state.get("workflow_error") or "").strip():
        logger.info("has_workflow_error: workflow_error: %s", state.get("workflow_error"))
        return True
    if (state.get("dynamodb_error") or "").strip():
        logger.info("has_workflow_error: dynamodb_error: %s", state.get("dynamodb_error"))
        return True
    return False


def propagate_workflow_error(result: dict[str, Any]) -> dict[str, Any]:
    """Normalize node outputs so failures set ``workflow_error`` for graph routing."""
    if (result.get("workflow_error") or "").strip():
        logger.info("propagate_workflow_error: workflow_error: %s", result.get("workflow_error"))
        return result
    dynamo_err = (result.get("dynamodb_error") or "").strip()
    if dynamo_err:
        logger.info("propagate_workflow_error: dynamo_err: %s", dynamo_err)
        return {**result, "workflow_error": dynamo_err}
    for line in result.get("action_log") or []:
        if ": FAILED" in str(line):
            logger.info("propagate_workflow_error: line: %s", line)
            return {**result, "workflow_error": str(line)}
    logger.info("propagate_workflow_error: result: %s", result)
    return result


def workflow_error_guard(
    node_fn: Callable[[AnalysisAgentState], dict[str, Any]],
    *,
    node_name: str | None = None,
    skip_if_error: bool = True,
) -> Callable[[AnalysisAgentState], dict[str, Any]]:
    """Catch unhandled exceptions and map known failure fields to ``workflow_error``."""

    resolved_name = node_name or node_fn.__name__

    def wrapped(state: AnalysisAgentState) -> dict[str, Any]:
        if skip_if_error and has_workflow_error(state):
            log_node_skipped(
                resolved_name,
                reason="workflow_error already present",
            )
            return {}
        start = log_node_started(resolved_name)
        try:
            result = node_fn(state) or {}
        except Exception as e:
            log_node_finished(resolved_name, start, success=False, detail=str(e))
            logger.exception("langgraph_node node=%s unhandled exception", resolved_name)
            return {
                "workflow_error": str(e),
                "action_log": [f"{resolved_name}: FAILED {e}"],
            }
        normalized = propagate_workflow_error(result)
        workflow_err = (normalized.get("workflow_error") or "").strip()
        if workflow_err:
            log_node_finished(resolved_name, start, success=False, detail=workflow_err)
        else:
            log_node_finished(resolved_name, start, success=True)
        return normalized

    return wrapped


def route_on_workflow_error(
    state: AnalysisAgentState,
) -> Literal["ERROR", "CONTINUE"]:
    if has_workflow_error(state):
        logger.info("workflow_error present -> Human_review")
        return "ERROR"
    logger.info("route_on_workflow_error: CONTINUE")
    return "CONTINUE"


def route_after_creditor_documents(
    state: AnalysisAgentState,
) -> Literal["ERROR", "HUMAN_REVIEW", "PROCESS_CONSUMER", "PROCESS_CREDITOR"]:
    if has_workflow_error(state):
        logger.info("has_workflow_error: ERROR")
        return "ERROR"
    status_route = route_by_status(state)
    if status_route == "HUMAN_REVIEW":
        logger.info("status_route: HUMAN_REVIEW")
        return "HUMAN_REVIEW"
    if state.get("attachmentAvailable"):
        logger.info("attachmentAvailable=True -> process_consumer_documents")
        logger.info("attachmentAvailable: PROCESS_CONSUMER")
        return "PROCESS_CONSUMER"
    logger.info("attachmentAvailable=False -> PROCESS_CREDITOR")
    return "PROCESS_CREDITOR"


def route_after_invoke_llm(
    state: AnalysisAgentState,
) -> Literal["ERROR", "HIGH_CONFIDENCE", "LOW_CONFIDENCE"]:
    if has_workflow_error(state):
        logger.info("has_workflow_error: ERROR")
        return "ERROR"
    return route_by_confidence_score(state)


def route_after_dispute_details(
    state: AnalysisAgentState,
) -> Literal["ERROR", "MISSING_VALUES", "VALUES_PRESENT"]:
    if has_workflow_error(state):
        logger.info("has_workflow_error: ERROR")
        return "ERROR"
    return route_by_empty_values(state)


def route_after_mark_dispute_verified(
    state: AnalysisAgentState,
) -> Literal["ERROR", "MISSING_VALUES", "VALUES_PRESENT"]:
    """Single router after mark_dispute_verified (workflow error, then required fields)."""
    if has_workflow_error(state):
        logger.info("route_after_mark_dispute_verified: workflow_error -> ERROR")
        return "ERROR"
    route = route_by_empty_values(state)
    logger.info("route_after_mark_dispute_verified: %s", route)
    return route


def download_creditor_documents(state: AnalysisAgentState):
    """
    Load case document ``storageUrl`` from RI collections API.

    Sets ``value``, ``confidenceScore``, ``api_response_status``, and merges URLs into ``creditor_documents``.
    """
    settings = get_settings()
    case_id = (state.get("case_id") or "").strip()
    account_id = (state.get("account_id") or "").strip()
    logger.info("download_creditor_documents: case_id: %s, account_id: %s", case_id, account_id)
    result = fetch_case_documents_storage_url(settings, case_id, account_id)
    logger.info("download_creditor_documents: result: %s", result)
    creditor_document_source_s3_uris = []
    for u in result.storage_urls:
        u = (u or "").strip()
        if u and u not in creditor_document_source_s3_uris:
            creditor_document_source_s3_uris.append(u)
    log_bits: list[str] = [
        f"case_documents_fetch: case_id={case_id!r}",
        f"api_response_status={result.api_response_status}",
        f"url_present={bool(creditor_document_source_s3_uris or [])}",
        f"storage_url_count={len(result.storage_urls)}",
    ]
    if result.http_status is not None:
        log_bits.append(f"http_status={result.http_status}")
    if result.error_message:
        log_bits.append(f"error={result.error_message!r}")

    return {
        "creditor_document_source_s3_uris": creditor_document_source_s3_uris,
        "api_response_status": result.api_response_status,
        "action_log": ["; ".join(log_bits)],
    }

def download_config_details(state: AnalysisAgentState):
    """
    Load ``originatorDisputeCode1.json`` and ``originatorDisputeCode2.json`` from
    ``s3://case-dispute-analysis/configuration/`` and parse them into ``config_details``.
    """
    existing = state.get("config_details")
    if existing:
        return {"config_details": existing}

    settings = get_settings()

    def _load_config() -> dict[str, Any]:
        parsed: dict[str, Any] = {}
        for filename in settings.config_json_files:
            s3_key = f"{settings.config_s3_prefix}{filename}"
            state_key = Path(filename).stem
            parsed[state_key] = download_s3_json_object(
                settings.config_s3_bucket,
                s3_key,
                aws_region=settings.aws_region,
            )
        return parsed

    try:
        config_details = call_with_retry(
            _load_config,
            operation="download configuration JSON from S3",
            state=state,
            settings=settings,
        )
    except RetriesExhaustedError as e:
        logger.exception("download_config_details: retries exhausted")
        return {
            "workflow_error": str(e),
            "action_log": [f"download_config_details: FAILED {e}"],
        }
    except Exception as e:
        logger.exception("download_config_details: S3 download or JSON parse failed")
        return {
            "workflow_error": str(e),
            "action_log": [f"download_config_details: FAILED {e}"],
        }

    loaded = ", ".join(settings.config_json_files)
    consumer_doc_s3_uri = _document_staging_prefix(
        state,
        settings,
        folder_name="ConsumerDocuments",
    )
    creditor_doc_s3_uri = _document_staging_prefix(
        state,
        settings,
        folder_name="CreditorDocuments",
    )
    return {
        "consumer_document_s3_bucket": consumer_doc_s3_uri,
        "creditor_document_s3_bucket": creditor_doc_s3_uri,
        "configuredDisputeCode1": config_details.get("originatorDisputeCode1", {}),
        "configuredDisputeCode2": config_details.get("originatorDisputeCode2", {}),
        "action_log": [
            f"download_config_details: loaded [{loaded}] from "
            f"s3://{settings.config_s3_bucket}/{settings.config_s3_prefix}"
        ],
    }



def consumer_document_ingestion(state: AnalysisAgentState):
    """Copy consumer PDFs into the analysis bucket, then upload them to OpenAI."""
    settings = get_settings()
    default_bucket = str(state.get("document_s3_bucket") or "").strip()
    consumer_document_s3_uris: list[str] = []
    consumer_document_s3_uris = _as_string_list(state.get("consumer_document_s3_uris"))
    consumer_doc_s3_bucket = str(
        state.get("consumer_document_s3_bucket")
        or _document_staging_prefix(state, settings, folder_name="ConsumerDocuments")
    )
    logger.info("consumer_document_ingestion: consumer_doc_s3_bucket: %s", consumer_doc_s3_bucket)
    try:
        consumer_doc_s3_uri, copied_pdf_files = _copy_documents_to_staging(
            state,
            settings,
            consumer_document_s3_uris,
            consumer_doc_s3_bucket,
            operation="copy consumer documents to analysis S3",
        )
        file_ids = pdf_ingestion(state, copied_pdf_files, settings)
    except Exception as e:
        logger.exception("consumer_document_ingestion failed")
        return {
            "workflow_error": str(e),
            "action_log": [f"consumer_document_ingestion: FAILED {e}"],
        }
    return {
        "consumer_document_s3_bucket": consumer_doc_s3_uri,
        "consumer_document_s3_uris": copied_pdf_files,
        "consumer_document_file_ids": file_ids,
        "action_log": [
            "consumer_document_ingestion: copied "
            f"{len(copied_pdf_files)} S3 document(s), uploaded {len(file_ids)} OpenAI file_id(s)"
        ],
    }


def creditor_document_ingestion(state: AnalysisAgentState) -> dict[str, Any]:
    """Copy creditor PDFs into the analysis bucket, then upload them to OpenAI."""
    settings = get_settings()
    creditor_document_source_s3_uris = _as_string_list(
        state.get("creditor_document_source_s3_uris")
    )
    creditor_doc_s3_bucket_value = state.get("creditor_document_s3_bucket")
    if not creditor_document_source_s3_uris and isinstance(
        creditor_doc_s3_bucket_value, list
    ):
        creditor_document_source_s3_uris = _as_string_list(creditor_doc_s3_bucket_value)
    creditor_doc_s3_bucket = (
        str(creditor_doc_s3_bucket_value)
        if isinstance(creditor_doc_s3_bucket_value, str)
        else _document_staging_prefix(state, settings, folder_name="CreditorDocuments")
    )
    logger.info("creditor_document_ingestion: creditor_doc_s3_bucket: %s", creditor_doc_s3_bucket)
    try:
        creditor_doc_s3_uri, copied_pdf_files = _copy_documents_to_staging(
            state,
            settings,
            creditor_document_source_s3_uris,
            creditor_doc_s3_bucket,
            operation="copy creditor documents to analysis S3",
        )
        file_ids = pdf_ingestion(state, copied_pdf_files, settings)
    except Exception as e:
        logger.exception("creditor_document_ingestion failed")
        return {
            "workflow_error": str(e),
            "action_log": [f"creditor_document_ingestion: FAILED {e}"],
        }
    return {
        "creditor_document_s3_bucket": creditor_doc_s3_uri,
        "creditor_document_s3_uris": copied_pdf_files,
        "creditor_document_file_ids": file_ids,
        "action_log": [
            "creditor_document_ingestion: copied "
            f"{len(copied_pdf_files)} S3 document(s), uploaded {len(file_ids)} OpenAI file_id(s)"
        ],
    }


def invoke_analysis_agent(state: AnalysisAgentState) -> dict[str, Any]:
    settings = get_settings()
    processingImageDisputeCode1:str=""
    processingImageDisputeCode2:str=""
    if state["consumerInfo"] is not None:
        ssn = state["consumerInfo"].get("ssn")
        if ssn is not None:
            ssn = decrypt_value(ssn, settings)
        dob = state["consumerInfo"].get("dob")
        if dob is not None:
            dob = decrypt_value(dob, settings)
        state["consumerInfo"]["ssn"]=ssn
        state["consumerInfo"]["dob"]=dob
    if state["disputeInfo"] is not None:
        cfg1 = dict(state.get("configuredDisputeCode1") or {})
        cfg2 = dict(state.get("configuredDisputeCode2") or {})
        dispute_info = state["disputeInfo"]
        logger.info("invoke_analysis_agent: dispute_info: %s", dispute_info)
        code1 = state.get("imageDisputeCode1", 0)
        code2 = state.get("imageDisputeCode2", 0)
        logger.info("invoke_analysis_agent: code1: %s, code2: %s", code1, code2)
        processingImageDisputeCode1 = f"{code1}:{cfg1.get(str(code1), 0)}"
        processingImageDisputeCode2 = f"{code2}{cfg2.get(str(code2), 0)}"
        logger.info("invoke_analysis_agent: processingImageDisputeCode1: %s, processingImageDisputeCode2: %s", processingImageDisputeCode1, processingImageDisputeCode2)
    ai, analysis_usage = invoke_agent_analysis(
        settings,
        account_id=state["account_id"],
        case_id=state["case_id"],
        source=state.get("source") or "other",
        consumer_document_file_ids=list(state.get("consumer_document_file_ids") or []),
        creditor_document_file_ids=list(state.get("creditor_document_file_ids") or []),
        processing_image_dispute_code_1=processingImageDisputeCode1,
        processing_image_dispute_code_2=processingImageDisputeCode2,
        dispute_info=state.get("disputeInfo") or {},
        consumer_info=state.get("consumerInfo") or {},
        account_info=state.get("accountInfo") or {},
    )
    return {
        "processingImageDisputeCode1": processingImageDisputeCode1,
        "processingImageDisputeCode2": processingImageDisputeCode2,
        "analysis_payload": ai.model_dump(),
        "analysis_usage": analysis_usage,
        "action_log": ["analysis agent analysis: structured analysis received"],
    }

def Batch_dynamo_db_write(state: AnalysisAgentState) -> dict[str, Any]:
    """Put a new JUDGMENT#MODEL row (after successful analysis) or update dispute on low confidence."""
    settings = get_settings()
    table = (settings.aws_dynamodb_table or "").strip()
    if not table:
        return {
            "workflow_fields_persisted": False,
            "action_log": ["Batch_dynamo_db_write: AWS_DYNAMODB_TABLE not set; skip"],
        }

    created = datetime.now(timezone.utc).isoformat()
    analysis_payload = dict(state.get("analysis_payload") or {})

    def _str_field(key: str) -> str:
        v = analysis_payload.get(key)
        return v if isinstance(v, str) else ""

    conf = analysis_payload.get("aiConfidenceLevel")
    if not isinstance(conf, int):
        try:
            conf = int(conf) if conf is not None else 0
        except (TypeError, ValueError):
            conf = 0
    logger.info("Batch_dynamo_db_write: dispute_uuid: %s", state['dispute_uuid'])
    item = {
        "PK": "JUDGMENT#MODEL",
        "SK": f"JUDGMENT#{state['dispute_uuid']}",
        "source_pk": state.get("source_pk"),
        "source_sk": state.get("source_sk"),
        "status": "PENDING",
        "analysis_model": state["analysis_model"],
        "payload": {
            "analysisDisputeResponseCode": _str_field("aiDisputeResponseCode"),
            "analysisRecommendationReason": _str_field("aiRecommendationReason"),
            "analysisConfidenceLevel": conf,
            "analysisSummary": _str_field("aiSummary"),
            "analysisRecommendation": _str_field("aiRecommendation"),
            "analysisDisputeReason": _str_field("aiDisputeReason"),
            "analysisAutomatableResponse": _str_field("aiAutomatableResponse"),
            #"consumer_documents": state.get("consumer_documents"),
            #"creditor_documents": state.get("creditor_documents")

        },
        "accountId": state.get("account_id"),
        "caseId": state.get("case_id"),
        "source": state.get("source"),
        "dispute_uuid": state.get("dispute_uuid"),
        "dispute_id": state.get("dispute_id"),
        "disputeInfo": state.get("disputeInfo"),
        "consumerInfo": state.get("consumerInfo"),
        "accountInfo": state.get("accountInfo"),
        "processingImageDisputeCode1": state.get("processingImageDisputeCode1"),
        "processingImageDisputeCode2": state.get("processingImageDisputeCode2"),
        "consumer_document_file_ids": state.get("consumer_document_file_ids"),
        "creditor_document_file_ids": state.get("creditor_document_file_ids"),
        "creditor_document_s3_path": state.get("creditor_document_s3_bucket"),
        "consumer_document_s3_path": state.get("consumer_document_s3_bucket"),
        "createdAt": created,
        "GSI2PK": "JUDGMENT#MODEL#STATUS#PENDING",
        "GSI2SK": f"JUDGMENT#{created}",
    }

    try:
        put_item_with_retry(item=item, state=state, settings=settings)
    except RetriesExhaustedError as e:
        return {
            "workflow_error": str(e),
            "dynamodb_error": str(e),
            "workflow_fields_persisted": False,
            "action_log": [f"Batch_dynamo_db_write: FAILED {e}"],
        }
    except Exception as e:
        logger.exception("Batch_dynamo_db_write: PutItem failed")
        return {
            "workflow_error": str(e),
            "dynamodb_error": str(e),
            "workflow_fields_persisted": False,
            "action_log": [f"Batch_dynamo_db_write: FAILED {e}"],
        }

    return {
        "created_at_iso": created,
        "workflow_fields_persisted": True,
        "action_log": ["Batch_dynamo_db_write: PutItem succeeded"],
    }


def update_status_dynamo_human_review(state: AnalysisAgentState) -> dict[str, Any]:
    """Set ``disputeStatus`` to ``in_review`` on the source dispute row."""
    settings = get_settings()
    logger.info("update_status_dynamo_human_review: dispute_status: %s", DISPUTE_STATUS_IN_REVIEW)
    result = _update_dispute_status_dynamo(
        state,
        settings=settings,
        dispute_status=DISPUTE_STATUS_IN_REVIEW,
        log_prefix="update_status_dynamo_human_review",
    )
    if not result.get("dynamodb_error"):
        result["analysis_payload"] = {}
    return result


def route_by_status(state: AnalysisAgentState) -> Literal[
    "SUCCESS",
    "HUMAN_REVIEW",
]:
    """Route after case-documents API based on ``api_response_status``."""
    status = state.get("api_response_status") or "ERROR"
    if status == "SUCCESS":
        logger.info("api_response_status: SUCCESS -> pdf_ingestion")
        return "SUCCESS"
    if status == "HUMAN_REVIEW":
        logger.info("api_response_status: HUMAN_REVIEW -> update_status_dynamo")
        return "HUMAN_REVIEW"
    logger.info("api_response_status: ERROR -> update_dispute_details_in_dynamo")
    return "HUMAN_REVIEW"


def route_by_confidence_score(state: AnalysisAgentState) -> Literal[
    "LOW_CONFIDENCE",
    "HIGH_CONFIDENCE",
]:
    """Route after case-documents API based on ``api_response_status``."""
    settings = get_settings()
    confidence_score = state.get("confidenceScore") or 0
    if confidence_score >= settings.ai_confidence_level_threshold:
        logger.info(f"confidence_score: > threshold -> Batch_dynamo_db_write {confidence_score} > {settings.ai_confidence_level_threshold}")
        return "HIGH_CONFIDENCE"
    logger.info(f"confidence_score: < threshold -> update_status_dynamo {confidence_score} < {settings.ai_confidence_level_threshold}")
    return "LOW_CONFIDENCE"

def route_by_empty_values(state: AnalysisAgentState) -> Literal[
    "MISSING_VALUES",
    "VALUES_PRESENT",
]:
    """Route after case-documents API based on ``api_response_status``."""

    def _routing_dispute_code_present(value: Any) -> bool:
        """True when a dispute code was supplied (integer 0 is a valid code)."""
        if value is None:
            return False
        if isinstance(value, bool):
            return False
        if isinstance(value, int):
            return True
        if isinstance(value, str):
            return value.strip() != ""
        return False

    account_no = state.get("account_no")
    case_id = state.get("case_id")
    account_id = state.get("account_id")
    imageDisputeCode1 = state.get("imageDisputeCode1")
    imageDisputeCode2 = state.get("imageDisputeCode2")

    if (
        account_no
        and case_id
        and account_id
        and _routing_dispute_code_present(imageDisputeCode1)
        and _routing_dispute_code_present(imageDisputeCode2)
    ):
        logger.info("account_no, case_id, account_id, imageDisputeCode1, imageDisputeCode2: SUCCESS -> fetch_case_documents")
        return "VALUES_PRESENT"
    logger.info("account_no, case_id, account_id, imageDisputeCode1, imageDisputeCode2: ERROR -> update_status_dynamo")
    return "MISSING_VALUES"