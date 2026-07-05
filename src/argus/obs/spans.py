"""Span context manager (03 §1 spans). Every LLM/tool/node emits one; attrs are filled
during the block and persisted on exit with timing + OK/ERROR status."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from argus.obs.pg_exporter import write_span


@dataclass
class SpanHandle:
    span_id: str
    trace_id: str
    incident_id: str | None
    attrs: dict[str, Any] = field(default_factory=dict)

    def set(self, **kwargs: Any) -> None:
        self.attrs.update(kwargs)


@contextmanager
def span(
    name: str,
    kind: str,
    *,
    incident_id: str | None = None,
    trace_id: str | None = None,
    parent_span_id: str | None = None,
    attrs: dict[str, Any] | None = None,
) -> Iterator[SpanHandle]:
    handle = SpanHandle(
        span_id=uuid.uuid4().hex[:16],
        trace_id=trace_id or uuid.uuid4().hex,
        incident_id=incident_id,
        attrs=dict(attrs or {}),
    )
    started = datetime.now(UTC)
    status = "OK"
    try:
        yield handle
    except Exception:
        status = "ERROR"
        raise
    finally:
        ended = datetime.now(UTC)
        write_span(
            {
                "span_id": handle.span_id,
                "trace_id": handle.trace_id,
                "incident_id": incident_id,
                "parent_span_id": parent_span_id,
                "name": name,
                "kind": kind,
                "status": status,
                "started_at": started,
                "ended_at": ended,
                "duration_ms": int((ended - started).total_seconds() * 1000),
                "attrs": handle.attrs,
            }
        )
