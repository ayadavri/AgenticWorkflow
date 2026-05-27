"""Exponential backoff retries for I/O and LLM calls."""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from typing import Any, TypeVar
from collections.abc import Mapping

from src.analysis_agent.langgraph.state import AnalysisAgentState
from src.analysis_agent.document_ingest import cleanup_analysis_model_uploads
from src.config import Settings

logger = logging.getLogger(__name__)

T = TypeVar("T")


class RetriesExhaustedError(RuntimeError):
    """Raised when ``call_with_retry`` runs out of attempts."""

    def __init__(self, message: str, *, last_error: BaseException | None = None) -> None:
        super().__init__(message)
        self.last_error = last_error


def _all_analysis_upload_file_ids(state: Mapping[str, Any]) -> list[str]:
    """Collect consumer and creditor OpenAI file IDs from workflow state."""
    ids: list[str] = []
    seen: set[str] = set()
    for key in ("consumer_document_file_ids", "creditor_document_file_ids"):
        for fid in state.get(key) or []:
            s = str(fid or "").strip()
            if s and s not in seen:
                seen.add(s)
                ids.append(s)
    return ids


def _cleanup_stale_uploads(state: Mapping[str, Any], settings: Settings) -> None:
    """Best-effort delete of OpenAI file_ids if a retried operation never completes."""
    upload_ids = _all_analysis_upload_file_ids(state)
    if upload_ids:
        try:
            cleanup_analysis_model_uploads(settings, upload_ids)
        except Exception:
            logger.exception("Failed to cleanup analysis model uploads after retries exhausted")
        try:
            state["consumer_document_file_ids"] = []
            state["creditor_document_file_ids"] = []
        except Exception:
            pass


def call_with_retry(
    fn: Callable[[], T],
    *,
    attempts: int = 5,
    base_delay_s: float = 0.5,
    max_delay_s: float = 30.0,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
    operation: str = "operation",
    state: Mapping[str, Any],
    settings:Settings
) -> T:
    """
    Run ``fn`` with exponential backoff and full jitter between failures.

    Raises ``RetriesExhaustedError`` if all attempts fail (fatal per workflow spec).
    """
    if attempts < 1:
        raise ValueError("attempts must be >= 1")

    last_exc: BaseException | None = None
    operation_started = time.monotonic()
    for attempt in range(1, attempts + 1):
        attempt_started = time.monotonic()
        try:
            result = fn()
            logger.info(
                "%s succeeded attempt=%d/%d elapsed_ms=%.0f",
                operation,
                attempt,
                attempts,
                (time.monotonic() - attempt_started) * 1000,
            )
            return result
        except retry_on as e:  # type: ignore[misc]
            last_exc = e
            if attempt >= attempts:
                _cleanup_stale_uploads(state, settings)
                logger.exception(
                    "%s failed after %d attempts total_elapsed_ms=%.0f",
                    operation,
                    attempts,
                    (time.monotonic() - operation_started) * 1000,
                )
                raise RetriesExhaustedError(
                    f"{operation} failed after {attempts} attempt(s): {e}",
                    last_error=e,
                ) from e
            cap = min(max_delay_s, base_delay_s * (2 ** (attempt - 1)))
            sleep_s = random.uniform(0, cap)
            logger.warning(
                "%s attempt %d/%d failed (%s); retrying in %.2fs",
                operation,
                attempt,
                attempts,
                e,
                sleep_s,
            )
            time.sleep(sleep_s)
    raise RetriesExhaustedError(f"{operation}: unexpected exit", last_error=last_exc)
