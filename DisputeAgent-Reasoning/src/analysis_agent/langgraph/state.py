"""LangGraph state for the analysis agent (S3 ingest, OpenAI, DynamoDB)."""

from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, NotRequired, TypedDict


class AnalysisAgentState(TypedDict):
    """Keys required to run the graph; optional keys are filled as nodes execute."""

    # Identity / DynamoDB source row
    account_id: str
    case_id: str
    dispute_id: str
    dispute_uuid: str
    account_no: str
    source_pk: str
    source_sk: str
    source: str

    # Consumer document source from Lambda/debug input
    attachedDocumentS3BucketPDFFile: NotRequired[str]
    document_s3_bucket: NotRequired[str]
    document_s3_key: NotRequired[str]
    document_s3_keys: NotRequired[list[str]]

    # Staged S3 locations and OpenAI file IDs
    consumer_document_s3_bucket: NotRequired[str]
    # Staging prefix (str) or legacy list of creditor source URIs (list)
    creditor_document_s3_bucket: NotRequired[str | list[str]]
    consumer_document_s3_uris: NotRequired[list[str]]
    creditor_document_source_s3_uris: NotRequired[list[str]]
    creditor_document_s3_uris: NotRequired[list[str]]
    consumer_document_file_ids: NotRequired[list[str]]
    creditor_document_file_ids: NotRequired[list[str]]

    # Model/runtime configuration
    analysis_model: str
    judgment_model: str
    action_log: Annotated[list[str], operator.add]
    created_at_iso: NotRequired[str]

    # Workflow status and diagnostics
    analysis_payload: NotRequired[dict[str, Any]]
    analysis_usage: NotRequired[dict[str, Any]]
    dynamodb_error: str
    Openai_usage: NotRequired[dict[str, Any]]
    confidenceScore: int
    api_response_status: Literal["SUCCESS", "ERROR", "HUMAN_REVIEW"]
    workflow_fields_persisted: NotRequired[bool]
    workflow_error: NotRequired[str]

    # Dispute code configuration and processing values
    config_details: NotRequired[dict[str, Any]]
    configuredDisputeCode1: NotRequired[dict[str, Any]]
    configuredDisputeCode2: NotRequired[dict[str, Any]]
    imageDisputeCode1: NotRequired[Any]
    imageDisputeCode2: NotRequired[Any]
    processingImageDisputeCode1: NotRequired[Any]
    processingImageDisputeCode2: NotRequired[Any]

    # Input payload sections from Lambda/debug
    attachmentAvailable: bool
    disputeInfo: dict[str, Any]
    consumerInfo: dict[str, Any]
    accountInfo: dict[str, Any]

    # Optional legacy/intermediate fields still emitted by Lambda or nodes
    value: NotRequired[str]
    creditor_documents: NotRequired[list[str]]
    attachment_details: NotRequired[dict[str, Any]]

# Backward-compatible alias used by retry/db_utils imports
DualLLMGraphState = AnalysisAgentState