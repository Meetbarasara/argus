"""human_approval (M06): a real LangGraph interrupt for APPROVE_ACTION / APPROVE_PLAN.

The node interior re-runs from the top when the graph resumes (LangGraph re-executes the
interrupted node), so all side effects — the PENDING approvals row and the
WAITING_APPROVAL status — live in the worker task (which runs once per invoke). Here we
only build the interrupt payload, then, on resume, emit the human span and route on the
decision. On reject we replan: the human comment becomes reviewer feedback and the attempt
is counted (04 §1 edge table)."""

from __future__ import annotations

from typing import Any

from langgraph.types import interrupt

from argus.agents.schemas import ReviewChecks, ReviewVerdict
from argus.db.session import session_scope
from argus.graph.support import approval_context, now_iso, read_trace_id
from argus.obs.spans import span
from argus.repo import incidents as incident_repo


def human_approval(state: dict[str, Any], deps: Any) -> dict[str, Any]:
    escalation = dict(state.get("escalation") or {})
    level = escalation.get("level", "APPROVE_ACTION")
    hypothesis = state.get("hypothesis")
    proposed = hypothesis.proposed_action.model_dump(mode="json") if hypothesis else None

    # first pass pauses here; on resume interrupt() returns the human decision dict
    decision: dict[str, Any] = interrupt(
        {
            "kind": "approval",
            "level": level,
            "proposed_action": proposed,
            "context": approval_context(state),
        }
    )

    # ---- resume only past this point ----
    incident_id = state["incident_id"]
    trace_id = read_trace_id(incident_id)
    verdict = str(decision.get("decision", "reject"))
    with span("node.human_approval", "human", incident_id=incident_id, trace_id=trace_id) as sp:
        sp.set(
            level=level,
            decision=verdict,
            approval_id=decision.get("approval_id"),
            human_review_seconds=decision.get("human_review_seconds"),
        )

    updates: dict[str, Any] = {"approval_decision": decision}
    if verdict == "reject":
        comment = str(decision.get("comment") or "human rejected the proposed action")
        with session_scope() as session:
            incident = incident_repo.get_incident(session, incident_id)
            if incident is not None and incident.status == "WAITING_APPROVAL":
                incident_repo.transition(
                    session, incident, "INVESTIGATING", status_reason="human rejected; replanning"
                )
        # feedback flows into the next synthesize; replan counts as a remediation attempt
        updates["review_history"] = [
            ReviewVerdict(
                verdict="revise",
                checks=ReviewChecks(
                    evidence_supported=False, action_safe=False, action_proportional=False
                ),
                feedback=f"Human reviewer rejected the proposed action: {comment}",
            )
        ]
        updates["remediation_attempts"] = [
            {
                "action": None,
                "result": {"rejected_by": "human", "comment": comment},
                "ts": now_iso(),
            }
        ]
    return updates
