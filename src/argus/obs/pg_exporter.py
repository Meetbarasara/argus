"""Writes span rows to Postgres (03 §1 spans) — the primary sink of ADR-07's dual-sink
model. Best-effort: observability must never break the pipeline, so a write failure is
logged and swallowed. Oversized attrs are capped to 2 KB each with a WARN (never dropped
silently). The optional OTLP→Jaeger sink is wired separately in ``obs.otel``."""

from __future__ import annotations

import json
from typing import Any

import structlog

from argus.db.models import Span
from argus.db.session import session_scope

log = structlog.get_logger(__name__)

MAX_ATTR_BYTES = 2048


def _cap_attrs(attrs: dict[str, Any] | None) -> dict[str, Any]:
    """Cap each attr value to MAX_ATTR_BYTES of JSON, WARNing on truncation (08 #21)."""
    capped: dict[str, Any] = {}
    for key, value in (attrs or {}).items():
        serialized = value if isinstance(value, str) else json.dumps(value, default=str)
        if len(serialized.encode("utf-8")) > MAX_ATTR_BYTES:
            log.warning("span.attr_truncated", key=key, bytes=len(serialized.encode("utf-8")))
            capped[key] = serialized[:MAX_ATTR_BYTES] + "…[truncated]"
        else:
            capped[key] = value
    return capped


def write_span(row: dict[str, Any]) -> None:
    row = {**row, "attrs": _cap_attrs(row.get("attrs"))}
    try:
        with session_scope() as session:
            session.add(Span(**row))
    except Exception as exc:  # never let telemetry break the caller
        log.warning("span.write_failed", name=row.get("name"), error=str(exc))
