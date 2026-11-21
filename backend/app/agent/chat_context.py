"""Redact chat context while retaining authorized source references from tool results."""
from __future__ import annotations

import json

from ..privacy import sanitize_context


async def sanitize_chat_context(canon: list[dict], repo, workspace_id: str) -> tuple[list[dict], dict[str, int]]:
    cleaned, counts = sanitize_context(canon)
    for original, sanitized in zip(canon, cleaned, strict=True):
        if original.get('role') != 'tool' or original.get('name') != 'list_sources':
            continue
        try:
            data = json.loads(original.get('content', ''))
        except (ValueError, TypeError):
            continue
        if not isinstance(data, dict) or not isinstance(data.get('sources'), list):
            continue
        safe, _ = sanitize_context(data)
        if not isinstance(safe.get('sources'), list):
            continue
        for source, safe_source in zip(data['sources'], safe['sources'], strict=True):
            if not isinstance(source, dict) or not isinstance(safe_source, dict):
                continue
            source_id = source.get('id')
            if isinstance(source_id, str) and await repo.get_source(source_id, workspace_id):
                safe_source['id'] = source_id
        sanitized['content'] = json.dumps(safe, ensure_ascii=False)[:4000]
    return cleaned, counts
