"""Fetch case document metadata from Resident Interface collections API."""

from __future__ import annotations

import json
import logging
import ssl
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from src.analysis_agent.database.db_utils import get_ssm_parameter

from src.config import Settings

logger = logging.getLogger(__name__)

_DEFAULT_BASE = "https://test-ri-core.residentinterface.com"
_DOCUMENTS_PATH_TEMPLATE = "/collections/v1/cases/{case_id}/documents?enable_signed_url=true"


@dataclass(frozen=True)
class CaseDocumentFetchResult:
    """Normalized outcome for LangGraph state updates."""

    storage_urls: list[str]
    confidence_score: int
    api_response_status: str  # SUCCESS | ERROR | HUMAN_REVIEW
    ok: bool
    http_status: int | None
    error_message: str | None


def _normalize_storage_url(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw.strip()
    return str(raw).strip() if raw else ""


def _is_valid_storage_url(url: str) -> bool:
    return bool(url)


def extract_storage_url_from_payload(data: Any) -> list[str]:
    """
    Defensively read ``storageUrl`` from API JSON (root or first ``items[]`` entry).

    Returns a non-empty string only when a usable URL is present.
    """
    if not isinstance(data, dict):
        return []

    direct = _normalize_storage_url(data.get("storageUrl"))
    if _is_valid_storage_url(direct):
        return [direct]

    items = data.get("items")
    if not isinstance(items, list):
        return []
    
    candidate: list[str] = []
    for entry in items:
        if not isinstance(entry, dict):
            continue
        candidate.append(_normalize_storage_url(entry.get("storageUrl")))

    return [url for url in candidate if _is_valid_storage_url(url)]


#Used to fetch the case documents from the Resident Interface collections API
def fetch_case_documents_storage_url(
    settings: Settings,
    case_id: str,
    account_id: str,
    *,
    timeout_s: float | None = None,
) -> CaseDocumentFetchResult:
    """
    GET ``/collections/v1/cases/:caseId/documents`` and derive ``storageUrl`` + confidence.

    On any failure (network, non-2xx, invalid JSON), returns ``storage_url=""`` and
    ``confidence_score=0``.
    """
    cid = (case_id or "").strip()
    if not cid:
        return CaseDocumentFetchResult(
            storage_urls=[],
            confidence_score=0,
            api_response_status="ERROR",
            ok=False,
            http_status=None,
            error_message="case id is empty",
        )

    aid = (account_id or "").strip()
    if not aid:
        return CaseDocumentFetchResult(
            storage_urls=[],
            confidence_score=0,
            api_response_status="ERROR",
            ok=False,
            http_status=None,
            error_message="account id is empty",
        )
    base = (getattr(settings, "ri_core_base_url", None) or _DEFAULT_BASE).rstrip("/")
    path = _DOCUMENTS_PATH_TEMPLATE.format(case_id=cid)
    url = f"{base}{path}"
    logger.info(f"Fetching case documents from URL: {url}")
    token = get_ssm_parameter(settings.aws_region, settings.collection_core_documents_api_ssm_parameter)
    headers = {
        "content-type": "application/json",
        "x-account-id":aid,
    }
    logger.info(f"Headers: {headers}")
    if token:
        headers["x-api-key"] = token

    timeout = timeout_s if timeout_s is not None else float(getattr(settings, "ri_core_http_timeout_s", 30.0) or 30.0)

    req = Request(url, method="GET", headers=headers)

    started = time.monotonic()
    try:
        ctx = ssl.create_default_context()
        with urlopen(req, timeout=timeout, context=ctx) as resp:  # noqa: S310 — configured RI API base
            status = getattr(resp, "status", None) or resp.getcode()
            raw_body = resp.read()
        logger.info(
            "Case documents API succeeded case_id=%s account_id=%s status=%s elapsed_ms=%.0f",
            cid,
            aid,
            status,
            (time.monotonic() - started) * 1000,
        )
    except HTTPError as e:
        logger.warning(
            "Case documents HTTP error case_id=%s account_id=%s status=%s elapsed_ms=%.0f",
            cid,
            aid,
            e.code,
            (time.monotonic() - started) * 1000,
            exc_info=False,
        )
        return CaseDocumentFetchResult(
            storage_urls=[],
            confidence_score=0,
            api_response_status="ERROR",
            ok=False,
            http_status=int(e.code),
            error_message=str(e.reason) if e.reason else f"HTTP {e.code}",
        )
    except URLError as e:
        logger.warning(
            "Case documents request failed case_id=%s account_id=%s elapsed_ms=%.0f: %s",
            cid,
            aid,
            (time.monotonic() - started) * 1000,
            e.reason,
        )
        return CaseDocumentFetchResult(
            storage_urls=[],
            confidence_score=0,
            api_response_status="ERROR",
            ok=False,
            http_status=None,
            error_message=str(e.reason) if e.reason else str(e),
        )
    except (TimeoutError, OSError) as e:
        logger.warning(
            "Case documents I/O error case_id=%s account_id=%s elapsed_ms=%.0f: %s",
            cid,
            aid,
            (time.monotonic() - started) * 1000,
            e,
        )
        return CaseDocumentFetchResult(
            storage_urls=[],
            confidence_score=0,
            api_response_status="ERROR",
            ok=False,
            http_status=None,
            error_message=str(e),
        )

    if status is not None and int(status) >= 400:
        logger.warning("Case documents non-success status=%s case_id=%s", status, cid)
        return CaseDocumentFetchResult(
            storage_urls=[],
            confidence_score=0,
            api_response_status="ERROR",
            ok=False,
            http_status=int(status),
            error_message=f"HTTP {status}",
        )

    try:
        storage_urls = []
        payload = json.loads(raw_body.decode("utf-8") if isinstance(raw_body, (bytes, bytearray)) else str(raw_body))
        if payload.get("count") > 0:
                storage_urls = extract_storage_url_from_payload(payload)
                if not storage_urls:
                    return CaseDocumentFetchResult(
                        storage_urls=[],
                        confidence_score=0,
                        api_response_status="HUMAN_REVIEW",
                        ok=True,
                        http_status=int(status) if status is not None else None,
                        error_message="Human review required because no valid s3 storage URLs found for creditor documents",
                    )
                return CaseDocumentFetchResult(
                        storage_urls=storage_urls,
                        confidence_score=0,
                        api_response_status="SUCCESS",
                        ok=True,
                        http_status=int(status) if status is not None else None,
                        error_message=None,
                    )
        return CaseDocumentFetchResult(
                        storage_urls=storage_urls,
                        confidence_score=0,
                        api_response_status="HUMAN_REVIEW",
                        ok=True,
                        http_status=int(status) if status is not None else None,
                        error_message="Human review required because 0 no. of record found for creditor documents",
                    )
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        logger.warning("Case documents invalid JSON case_id=%s: %s", cid, e)
        return CaseDocumentFetchResult(
            storage_urls=[],
            confidence_score=0,
            api_response_status="ERROR",
            ok=False,
            http_status=int(status) if status is not None else None,
            error_message="invalid JSON response",
        )
