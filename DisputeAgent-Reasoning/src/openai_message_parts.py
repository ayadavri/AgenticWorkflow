"""OpenAI Chat Completions user message content parts (text + file attachments)."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def _dedupe_openai_file_ids(*groups: Iterable[str] | None) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for group in groups:
        for fid in group or []:
            s = str(fid or "").strip()
            if s and s not in seen:
                seen.add(s)
                out.append(s)
    return out


def chat_user_content_with_files(
    text: str,
    *,
    creditor_document_file_ids: Iterable[str] | None = None,
    consumer_document_file_ids: Iterable[str] | None = None,
    file_ids: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Build Chat Completions user ``content``: text plus ``{"type": "file", ...}`` parts.

    Creditor file IDs are listed before consumer IDs; ``file_ids`` is a legacy combined list.
    """
    content: list[dict[str, Any]] = [{"type": "text", "text": text}]
    for fid in _dedupe_openai_file_ids(
        creditor_document_file_ids,
        consumer_document_file_ids,
        file_ids,
    ):
        content.append({"type": "file", "file": {"file_id": fid}})
    return content
