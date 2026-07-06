"""take_over (interrupt-style hold): the escalation endpoint reached on reviewer reject,
budget breach, exhausted remediation attempts, or a TAKE_OVER risk level. It packages the
context into a PENDING TAKE_OVER approvals row (which stays PENDING until a human posts a
takeover resolution — 03 §1), sets the terminal TAKEN_OVER status with the reason, and
rolls up counters. Real human resolution + postmortem follow in later milestones."""

from __future__ import annotations

from typing import Any

from argus.db.session import session_scope
from argus.graph.support import (
    approval_context,
    counter_rollup,
    create_approval,
    escalation_field,
    read_trace_id,
)
from argus.obs.spans import span
from argus.repo import incidents as incident_repo


def _derive_reason(state: dict[str, Any]) -> str:
    """Explain why we escalated, for the incident's status_reason (all four take_over paths)."""
    if state.get("status_reason"):  # e.g. budget guard already set a reason
        return str(state["status_reason"])
    history = state.get("review_history", [])
    if history and history[-1].verdict != "approve":
        return f"reviewer did not approve after {len(history)} review(s): {history[-1].feedback}"
    if state.get("remediation_attempts") and not (state.get("recovery") or {}).get("recovered"):
        return "remediation attempts exhausted without recovery"
    if (state.get("escalation") or {}).get("level") == "TAKE_OVER":
        return "risk gate escalated to human take-over"
    return "escalated to a human on-call (take-over)"


def take_over(state: dict[str, Any], deps: Any) -> dict[str, Any]:
    incident_id = state["incident_id"]
    trace_id = read_trace_id(incident_id)
    reason = _derive_reason(state)
    hypothesis = state.get("hypothesis")
    proposed = hypothesis.proposed_action.model_dump(mode="json") if hypothesis else None

    with span("node.take_over", "human", incident_id=incident_id, trace_id=trace_id) as sp:
        approval_id = create_approval(
            incident_id,
            level="TAKE_OVER",
            status="PENDING",
            proposed_action=proposed,
            context=approval_context(state),
        )
        sp.set(reason=reason, approval_id=approval_id)

    with session_scope() as session:
        incident = incident_repo.get_incident(session, incident_id)
        if incident is not None:
            fields = {
                "status_reason": reason,
                **escalation_field(incident, "TAKE_OVER"),
                **counter_rollup(session, incident_id, state.get("budget", {})),
            }
            incident_repo.transition(session, incident, "TAKEN_OVER", **fields)

    return {"status_reason": reason}
