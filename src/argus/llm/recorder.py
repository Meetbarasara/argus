"""Record/replay cache (ADR-05). The llm_calls row IS the cache: its cache_key indexes a
prior response so replay/record can serve deterministically without calling a provider."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from argus.db.models import LLMCall


def canonical_messages(messages: list[dict[str, Any]]) -> str:
    return json.dumps(messages, sort_keys=True, ensure_ascii=False)


def cache_key(role: str, model: str, messages: list[dict[str, Any]], structure_id: str) -> str:
    payload = f"{role}|{model}|{structure_id}|{canonical_messages(messages)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def lookup_cached(session: Session, key: str) -> dict[str, Any] | None:
    """Most recent recorded response for this cache_key, or None."""
    stmt = (
        select(LLMCall).where(LLMCall.cache_key == key).order_by(desc(LLMCall.created_at)).limit(1)
    )
    row = session.scalars(stmt).first()
    return dict(row.response) if row is not None else None
