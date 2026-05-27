"""Structured start/end logging for LangGraph workflow nodes."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def log_node_started(node_name: str) -> datetime:
    start = datetime.now(timezone.utc)
    logger.info(
        "langgraph_node node=%s status=STARTED start_time=%s",
        node_name,
        _iso(start),
    )
    return start


def log_node_finished(
    node_name: str,
    start: datetime,
    *,
    success: bool,
    detail: str | None = None,
) -> None:
    end = datetime.now(timezone.utc)
    elapsed_ms = (end - start).total_seconds() * 1000
    status = "SUCCESS" if success else "FAILED"
    msg = (
        "langgraph_node node=%s status=%s start_time=%s end_time=%s elapsed_ms=%.0f"
    )
    args: list[Any] = [node_name, status, _iso(start), _iso(end), elapsed_ms]
    if detail:
        msg += " detail=%s"
        args.append(detail)
    if success:
        logger.info(msg, *args)
    else:
        logger.error(msg, *args)


def log_node_skipped(node_name: str, *, reason: str) -> None:
    now = datetime.now(timezone.utc)
    logger.info(
        "langgraph_node node=%s status=SKIPPED start_time=%s end_time=%s reason=%s",
        node_name,
        _iso(now),
        _iso(now),
        reason,
    )
