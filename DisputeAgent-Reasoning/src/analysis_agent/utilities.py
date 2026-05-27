"""OpenAI (parse) and Anthropic (tool-use) invokers for dual compliance analysis."""

from __future__ import annotations

import logging
import os
import time
from io import BytesIO
from typing import Any

from openai import OpenAI

from src.analysis_agent.schema import ComplianceAIAnalysis
from src.analysis_agent.document_ingest import (
    cleanup_analysis_model_uploads,
    download_s3_object_to_tempfile,
    get_ssm_parameter,
    parse_s3_bucket_and_key,
    upload_file_to_analysis_model,
)
from src.analysis_agent.prompts import (
    ANALYSIS_AGENT_SYSTEM,
    analysis_agent_message_content,
)
from src.analysis_agent.langgraph.state import AnalysisAgentState
from src.config import Settings, openai_chat_request_kwargs
from src.analysis_agent.retry import call_with_retry

logger = logging.getLogger(__name__)


def invoke_agent_analysis(
    settings: Settings,
    *,
    account_id: str,
    case_id: str,
    source: str,
    consumer_document_file_ids: list[str] | None = None,
    creditor_document_file_ids: list[str] | None = None,
    processing_image_dispute_code_1: Any = None,
    processing_image_dispute_code_2: Any = None,
    dispute_info: dict[str, Any] | None = None,
    consumer_info: dict[str, Any] | None = None,
    account_info: dict[str, Any] | None = None,
    extra_user_context: str | None = None,
    system_addon: str | None = None,
) -> tuple[ComplianceAIAnalysis, dict[str, Any]]:
    api_key = get_ssm_parameter(settings, settings.analysis_model_api_key_ssm_parameter)
    if not api_key:
        raise ValueError("Missing ANALYSIS_MODEL_API_KEY from SSM parameter.")
    client = OpenAI(api_key=api_key)
    system_text = ANALYSIS_AGENT_SYSTEM
    if system_addon:
        system_text = system_text + "\n\n" + system_addon.strip()
    user_content = analysis_agent_message_content(
        account_id=account_id,
        case_id=case_id,
        source=source,
        consumer_document_file_ids=consumer_document_file_ids,
        creditor_document_file_ids=creditor_document_file_ids,
        processing_image_dispute_code_1=processing_image_dispute_code_1,
        processing_image_dispute_code_2=processing_image_dispute_code_2,
        dispute_info=dispute_info,
        consumer_info=consumer_info,
        account_info=account_info,
        extra_context=extra_user_context,
    )
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_text},
        {"role": "user", "content": user_content},
    ]

    started = time.monotonic()
    try:
        completion = client.chat.completions.parse(
            model=settings.analysis_model,
            messages=messages,
            response_format=ComplianceAIAnalysis,
            **openai_chat_request_kwargs(
                settings.analysis_model,
                temperature=settings.analysis_model_temperature,
                max_tokens=settings.analysis_model_max_tokens,
            ),
        )
        parsed = completion.choices[0].message.parsed
        if parsed is None:
            raise RuntimeError("analysis model returned no parsed structured output")
        usage = completion.usage.model_dump() if completion.usage else {}
        logger.info(
            "OpenAI analysis completed model=%s file_count=%d usage=%s elapsed_ms=%.0f",
            settings.analysis_model,
            len(consumer_document_file_ids) + len(creditor_document_file_ids),
            usage,
            (time.monotonic() - started) * 1000,
        )
        return parsed, usage
    except Exception:
        logger.exception(
            "OpenAI analysis failed model=%s file_count=%d elapsed_ms=%.0f",
            settings.analysis_model,
            len(consumer_document_file_ids) + len(creditor_document_file_ids),
            (time.monotonic() - started) * 1000,
        )
        raise


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in values:
        value = str(raw or "").strip()
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def pdf_ingestion(
    state: AnalysisAgentState,
    pdf_files: list[str],
    settings: Settings,
) -> list[str]:
    """Download S3 PDFs and upload them to OpenAI, returning file IDs."""
    targets: list[tuple[str, str]] = []
    seen_targets: set[tuple[str, str]] = set()

    for raw_file in pdf_files:
        file_ref = str(raw_file or "").strip()
        if not file_ref:
            continue
        bucket, key = parse_s3_bucket_and_key(file_ref)
        pair = (bucket, key)
        if pair not in seen_targets:
            seen_targets.add(pair)
            targets.append(pair)

    if not targets:
        logger.info("pdf_ingestion: no S3 PDF files supplied")
        return []

    file_ids: list[str] = []

    for bucket, key in targets:

        def _one_upload(b: str = bucket, k: str = key) -> str:
            tmp_path, filename = download_s3_object_to_tempfile(
                b, k, aws_region=settings.aws_region
            )
            try:
                logger.info("Uploading S3 document to OpenAI Files API: s3://%s/%s", b, k)
                with open(tmp_path, "rb") as f:
                    data = f.read()
                return upload_file_to_analysis_model(settings, BytesIO(data), filename)
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

        oa = call_with_retry(
            _one_upload,
            operation=f"S3 download + analysis model file upload ({bucket}/{key})",
            state=state,
            settings=settings,
        )
        logger.info("Uploaded S3 document to OpenAI: s3://%s/%s file_id=%s", bucket, key, oa)
        file_ids.append(oa)

    logger.info("pdf_ingestion: uploaded %d/%d S3 PDF file(s)", len(file_ids), len(targets))
    return file_ids
