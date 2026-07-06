"""Postmortem writer (04 §4, M07). Auto-resolved incidents get an LLM-written
PostmortemMemory; human take-overs become a deterministic 'lesson' capturing the human's
resolution. Either way the fingerprint is computed in code and the embed text is
title + content + templates so recall can match a future occurrence."""

from __future__ import annotations

from typing import Any

import structlog

from argus.agents import prompts
from argus.agents.schemas import PostmortemMemory
from argus.errors import ArgusError
from argus.llm.router import LLMRouter
from argus.memory import fingerprint as fp
from argus.memory.embedder import embed
from argus.memory.pgvector_store import PgVectorStore
from argus.memory.vectorstore import VectorStore
from argus.tools import worldstate

log = structlog.get_logger(__name__)


def _fingerprint_and_templates(
    alert: dict[str, Any], affected: list[str]
) -> tuple[dict[str, Any], list[str]]:
    try:
        templates = fp.error_templates(worldstate.read_logs(alert.get("service"), 30))
    except Exception:
        templates = []
    services = [str(alert.get("service", "")), *affected]
    return fp.fingerprint(
        alert_rule=str(alert.get("rule")), services=services, templates=templates
    ), templates


def _latest_remediation(state: dict[str, Any]) -> dict[str, Any] | None:
    attempts = [a for a in state.get("remediation_attempts", []) if a.get("action")]
    return attempts[-1] if attempts else None


def write_postmortem(
    state: dict[str, Any],
    router: LLMRouter,
    *,
    incident_id: str,
    trace_id: str,
    parent_span_id: str,
    store: VectorStore | None = None,
) -> str | None:
    store = store or PgVectorStore()
    alert = state["alert"]
    hypothesis = state.get("hypothesis")
    decision = state.get("approval_decision") or {}
    affected = list(hypothesis.affected_services) if hypothesis else []
    fingerprint, templates = _fingerprint_and_templates(alert, affected)

    if decision.get("kind") == "takeover":
        title = f"Human take-over: {alert.get('rule')} on {alert.get('service')}"
        content = (
            f"human resolved: {decision.get('root_cause') or 'n/a'}. "
            f"action taken: {decision.get('action_taken') or 'n/a'}."
        )
        kind = "lesson"
    else:
        root_cause = hypothesis.root_cause if hypothesis else "incident resolved"
        try:
            postmortem = router.structured(
                "memory_writer",
                prompts.postmortem_messages(
                    alert, root_cause, affected, _latest_remediation(state), state.get("recovery")
                ),
                PostmortemMemory,
                incident_id=incident_id,
                trace_id=trace_id,
                parent_span_id=parent_span_id,
            )
            title, content, kind = postmortem.title, postmortem.content, postmortem.kind
        except ArgusError:  # deterministic fallback so a memory is still written
            log.warning("postmortem.llm_failed", incident_id=incident_id, exc_info=True)
            title = f"{alert.get('rule')} on {alert.get('service')}"
            content = str(root_cause)
            kind = "incident_pattern"

    embedding = embed(fp.memory_embed_text(title, content, templates))
    return store.add(
        kind=kind,
        title=title,
        content=content,
        fingerprint=fingerprint,
        embedding=embedding,
        source_incident_id=incident_id,
    )
