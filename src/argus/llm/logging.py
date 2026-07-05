"""Persist llm_calls rows (03 §1). The row doubles as the record/replay cache."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from argus.db.models import LLMCall
from argus.db.session import session_scope


def write_llm_call(
    *,
    role: str,
    provider: str,
    model: str,
    messages: list[dict[str, Any]],
    response: dict[str, Any],
    tokens_in: int,
    tokens_out: int,
    cost_usd: Decimal,
    latency_ms: int,
    validation_retries: int,
    mode: str,
    cache_key: str,
    incident_id: str | None = None,
    span_id: str | None = None,
) -> str:
    with session_scope() as session:
        row = LLMCall(
            role=role,
            provider=provider,
            model=model,
            messages=messages,
            response=response,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            validation_retries=validation_retries,
            mode=mode,
            cache_key=cache_key,
            incident_id=incident_id,
            span_id=span_id,
        )
        session.add(row)
        session.flush()
        return row.id
