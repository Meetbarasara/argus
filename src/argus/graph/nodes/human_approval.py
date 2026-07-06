"""human_approval (M05 hold; becomes a real interrupt in M06). For APPROVE_ACTION /
APPROVE_PLAN levels the graph would suspend for a human. Until M06 there is no interrupt:
this node creates the PENDING approvals row, parks the incident at WAITING_APPROVAL with a
clear status_reason, rolls up counters, and the graph run ends cleanly."""

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

HOLD_REASON = "waiting for human approval (HITL lands in M06)"


def human_approval(state: dict[str, Any], deps: Any) -> dict[str, Any]:
    incident_id = state["incident_id"]
    trace_id = read_trace_id(incident_id)
    escalation = dict(state.get("escalation") or {})
    level = escalation.get("level", "APPROVE_ACTION")
    hypothesis = state.get("hypothesis")
    proposed = hypothesis.proposed_action.model_dump(mode="json") if hypothesis else None

    with span("node.human_approval", "human", incident_id=incident_id, trace_id=trace_id) as sp:
        approval_id = create_approval(
            incident_id,
            level=level,
            status="PENDING",
            proposed_action=proposed,
            context=approval_context(state),
        )
        sp.set(level=level, approval_id=approval_id, note="HITL lands in M06")

    with session_scope() as session:
        incident = incident_repo.get_incident(session, incident_id)
        if incident is not None:
            fields = {
                "status_reason": HOLD_REASON,
                **escalation_field(incident, level),
                **counter_rollup(session, incident_id, state.get("budget", {})),
            }
            incident_repo.transition(session, incident, "WAITING_APPROVAL", **fields)

    escalation["approval_id"] = approval_id
    return {"escalation": escalation, "status_reason": HOLD_REASON}
