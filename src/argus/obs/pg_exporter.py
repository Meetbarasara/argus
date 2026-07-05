"""Writes span rows to Postgres (03 §1 spans). Best-effort: observability must never break
the pipeline, so a write failure is logged and swallowed. M09 adds batching + OTLP/Jaeger."""

from __future__ import annotations

from typing import Any

import structlog

from argus.db.models import Span
from argus.db.session import session_scope

log = structlog.get_logger(__name__)


def write_span(row: dict[str, Any]) -> None:
    try:
        with session_scope() as session:
            session.add(Span(**row))
    except Exception as exc:  # never let telemetry break the caller
        log.warning("span.write_failed", name=row.get("name"), error=str(exc))
