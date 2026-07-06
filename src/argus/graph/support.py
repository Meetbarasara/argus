"""Shared, deterministic helpers for graph nodes (budget accounting, trace-id lookup,
counter roll-up, approval rows, escalation-level bookkeeping). No LLM imports — safe for
the deterministic nodes to use."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from argus.db.models import Approval, Incident, LLMCall, ToolCall
from argus.db.session import session_scope
from argus.policy.risk_gate import stricter


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def read_trace_id(incident_id: str) -> str:
    """Trace id lives on the incident row (03 §1), written by intake. Every node reads it
    so all spans in the incident share one trace."""
    with session_scope() as session:
        trace_id = session.execute(
            select(Incident.trace_id).where(Incident.id == incident_id)
        ).scalar_one_or_none()
    return trace_id or uuid.uuid4().hex


# --- budget --------------------------------------------------------------------------
def bump_budget(state: dict[str, Any], n_llm_calls: int) -> dict[str, Any]:
    budget = dict(state.get("budget") or {})
    budget["llm_calls_used"] = int(budget.get("llm_calls_used", 0)) + n_llm_calls
    return budget


def budget_breach_reason(state: dict[str, Any], policy: dict[str, Any]) -> str | None:
    limits = policy.get("limits", {})
    budget = state.get("budget") or {}
    used = int(budget.get("llm_calls_used", 0))
    max_calls = int(limits.get("max_llm_calls_per_incident", 40))
    if used >= max_calls:
        return f"LLM call budget exhausted ({used}/{max_calls})"
    started = budget.get("started_at_iso")
    if started:
        elapsed = (datetime.now(UTC) - datetime.fromisoformat(started)).total_seconds()
        max_wall = float(limits.get("max_wall_seconds_per_incident", 420))
        if elapsed >= max_wall:
            return f"wall-clock budget exhausted ({int(elapsed)}s/{int(max_wall)}s)"
    return None


def mark_breached(state: dict[str, Any]) -> dict[str, Any]:
    budget = dict(state.get("budget") or {})
    budget["breached"] = True
    return budget


# --- counters / escalation -----------------------------------------------------------
def counter_rollup(session: Session, incident_id: str, budget: dict[str, Any]) -> dict[str, Any]:
    """Denormalized incident counters (03 §1) rolled up from the child rows + budget."""
    count, t_in, t_out, cost = session.execute(
        select(
            func.count(LLMCall.id),
            func.coalesce(func.sum(LLMCall.tokens_in), 0),
            func.coalesce(func.sum(LLMCall.tokens_out), 0),
            func.coalesce(func.sum(LLMCall.cost_usd), 0),
        ).where(LLMCall.incident_id == incident_id)
    ).one()
    tool_count = session.execute(
        select(func.count(ToolCall.id)).where(ToolCall.incident_id == incident_id)
    ).scalar_one()
    return {
        "llm_calls": int((budget or {}).get("llm_calls_used", 0) or count),
        "tokens_in": int(t_in),
        "tokens_out": int(t_out),
        "cost_usd": cost,
        "tool_calls_count": int(tool_count),
    }


def escalation_field(incident: Incident, level: str | None) -> dict[str, Any]:
    """Return {'escalation_level': highest-reached} for a transition, or {} if unchanged."""
    if level is None:
        return {}
    current = incident.escalation_level or "AUTO"
    return {"escalation_level": stricter(current, level)}


# --- approvals -----------------------------------------------------------------------
def approval_context(state: dict[str, Any]) -> dict[str, Any]:
    """Package the decision context an approvals row carries (03 §1 approvals.context)."""
    hypothesis = state.get("hypothesis")
    plan = state.get("plan")
    excerpts = [
        evidence.model_dump(mode="json")
        for finding in state.get("findings", [])
        for evidence in finding.evidence
    ]
    return {
        "hypothesis": hypothesis.model_dump(mode="json") if hypothesis is not None else None,
        "evidence_excerpts": excerpts[:8],
        "plan_summary": plan.rationale if plan is not None else "",
        "memory_refs": [hit.get("memory_id") for hit in state.get("memory_hits", [])],
    }


def create_approval(
    incident_id: str,
    *,
    level: str,
    status: str,
    proposed_action: dict[str, Any] | None,
    context: dict[str, Any],
    decided_by: str | None = None,
) -> str:
    """Insert an approvals row (03 §1) and return its id."""
    approval = Approval(
        incident_id=incident_id,
        level=level,
        status=status,
        proposed_action=proposed_action or {},
        context=context,
        decided_by=decided_by,
    )
    with session_scope() as session:
        session.add(approval)
        session.flush()
        return str(approval.id)
