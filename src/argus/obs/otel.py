"""OTel dual-sink wiring (ADR-07): code emits each span once; the Postgres exporter
(``obs.pg_exporter``) is the primary sink that powers the UI + dashboard, and an optional
OTLP exporter mirrors the same spans to Jaeger when ``OTEL_EXPORT_JAEGER=true``.

Two responsibilities live here so ``obs.spans`` stays a thin context manager:

* **incident-root registry** — the worker opens one ``incident`` root span per run and
  registers its id; ``obs.spans`` then auto-parents any otherwise-parentless node span to it,
  so an incident is a single rooted tree (08 #24) with no per-node edits.
* **OTLP mirror** — ``start_span``/``end_span`` open/close a matching OTel span, linked to the
  parent's OTel span so Jaeger shows the same hierarchy. Everything is best-effort and lazy:
  if the OTel packages or the collector are missing, the Postgres sink is unaffected."""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Any

import structlog

from argus.settings import get_settings

log = structlog.get_logger(__name__)

# --- incident root-span registry (in-process, set by the worker around graph.invoke) -----
_roots: dict[str, str] = {}
_roots_lock = threading.Lock()


def register_root(incident_id: str, root_span_id: str) -> None:
    with _roots_lock:
        _roots[incident_id] = root_span_id


def current_root(incident_id: str | None) -> str | None:
    if not incident_id:
        return None
    with _roots_lock:
        return _roots.get(incident_id)


def clear_root(incident_id: str) -> None:
    with _roots_lock:
        _roots.pop(incident_id, None)


# --- optional OTLP -> Jaeger sink --------------------------------------------------------
_setup_lock = threading.Lock()
_configured = False
_tracer: Any = None
_otel_spans: dict[str, Any] = {}  # our span_id -> live OTel span (open spans only)
_otel_lock = threading.Lock()


def setup_tracing(service_name: str) -> None:
    """Idempotent TracerProvider setup at api/worker boot. Adds the OTLP->Jaeger processor
    only when OTEL_EXPORT_JAEGER=true; otherwise a no-op (Postgres sink still works)."""
    global _configured, _tracer
    with _setup_lock:
        if _configured:
            return
        _configured = True
        settings = get_settings()
        if not settings.otel_export_jaeger:
            return
        try:
            from opentelemetry import trace
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            resource = Resource.create(
                {"service.name": service_name, "service.version": settings.git_sha}
            )
            provider = TracerProvider(resource=resource)
            endpoint = settings.otel_exporter_otlp_endpoint
            provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True))
            )
            trace.set_tracer_provider(provider)
            _tracer = trace.get_tracer("argus")
            log.info("otel.jaeger_enabled", service=service_name, endpoint=endpoint)
        except Exception as exc:  # missing package / bad endpoint -> Postgres sink unaffected
            log.warning("otel.setup_failed", error=str(exc))
            _tracer = None


def _to_ns(dt: datetime) -> int:
    return int(dt.timestamp() * 1_000_000_000)


def _otel_attrs(kind: str, incident_id: str | None, attrs: dict[str, Any] | None) -> dict[str, Any]:
    out: dict[str, Any] = {"kind": kind, "incident_id": incident_id or ""}
    for key, value in (attrs or {}).items():
        out[key] = value if isinstance(value, str | int | float | bool) else str(value)
    return out


def start_span(
    span_id: str,
    name: str,
    kind: str,
    incident_id: str | None,
    parent_span_id: str | None,
    started: datetime,
    attrs: dict[str, Any] | None,
) -> None:
    """Open a mirror OTel span as a child of parent_span_id's OTel span (best-effort)."""
    if _tracer is None:
        return
    try:
        from opentelemetry import trace

        with _otel_lock:
            parent = _otel_spans.get(parent_span_id) if parent_span_id else None
        ctx = trace.set_span_in_context(parent) if parent is not None else None
        span = _tracer.start_span(
            name,
            context=ctx,
            start_time=_to_ns(started),
            attributes=_otel_attrs(kind, incident_id, attrs),
        )
        with _otel_lock:
            _otel_spans[span_id] = span
    except Exception as exc:
        log.warning("otel.start_failed", error=str(exc))


def end_span(span_id: str, status: str, ended: datetime, attrs: dict[str, Any] | None) -> None:
    if _tracer is None:
        return
    try:
        from opentelemetry.trace import Status, StatusCode

        with _otel_lock:
            span = _otel_spans.pop(span_id, None)
        if span is None:
            return
        for key, value in (attrs or {}).items():
            span.set_attribute(
                key, value if isinstance(value, str | int | float | bool) else str(value)
            )
        if status == "ERROR":
            span.set_status(Status(StatusCode.ERROR))
        span.end(end_time=_to_ns(ended))
    except Exception as exc:
        log.warning("otel.end_failed", error=str(exc))
