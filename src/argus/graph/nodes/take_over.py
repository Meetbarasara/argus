"""take_over (M06): a real interrupt where a human takes ownership. Reached on reviewer
reject, budget breach, exhausted remediation, or a TAKE_OVER risk level. The node pauses
with the full investigation package; the worker task opens a PENDING TAKE_OVER approvals
row + parks WAITING_APPROVAL. On resume (a posted takeover_resolution), it records the
human's root cause, sets the terminal TAKEN_OVER status, and flows to postmortem/close.

The interior re-runs on resume, so status/counters are written only after interrupt()
returns (once) — side effects on the first pass live in the task."""

from __future__ import annotations

from typing import Any

from langgraph.types import interrupt

from argus.db.models import TERMINAL_STATUSES
from argus.db.session import session_scope
from argus.graph.support import (
    approval_context,
    counter_rollup,
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
    reason = _derive_reason(state)
    hypothesis = state.get("hypothesis")
    proposed = hypothesis.proposed_action.model_dump(mode="json") if hypothesis else None

    resolution: dict[str, Any] = interrupt(
        {
            "kind": "takeover",
            "reason": reason,
            "proposed_action": proposed,
            "context": approval_context(state),
        }
    )

    # ---- resume only past this point (a takeover_resolution was posted) ----
    incident_id = state["incident_id"]
    trace_id = read_trace_id(incident_id)
    root_cause = resolution.get("root_cause") or reason
    with span("node.take_over", "human", incident_id=incident_id, trace_id=trace_id) as sp:
        sp.set(
            decision="takeover",
            human_review_seconds=resolution.get("human_review_seconds"),
            action_taken=resolution.get("action_taken"),
        )

    with session_scope() as session:
        incident = incident_repo.get_incident(session, incident_id)
        if incident is not None and incident.status not in TERMINAL_STATUSES:
            fields = {
                "status_reason": f"human take-over: {root_cause}",
                "root_cause": root_cause,
                **escalation_field(incident, "TAKE_OVER"),
                **counter_rollup(session, incident_id, state.get("budget", {})),
            }
            incident_repo.transition(session, incident, "TAKEN_OVER", **fields)

    return {"approval_decision": resolution}
