"""risk_gate (deterministic, ADR-04): map the hypothesis's proposed action + confidence
to an escalation level via policy.yaml, emit a ``policy`` span carrying the rule trace,
record the highest level reached, and (for NOTIFY) drop an informational AUTO approvals
row. Routing on the returned level happens in build.py. This node changes no incident
status, so it does not touch the incident repository."""

from __future__ import annotations

from typing import Any

from argus.db.session import session_scope
from argus.graph.support import approval_context, create_approval, read_trace_id
from argus.obs.spans import span
from argus.policy.risk_gate import evaluate_risk, stricter
from argus.repo.incidents import get_incident


def risk_gate(state: dict[str, Any], deps: Any) -> dict[str, Any]:
    incident_id = state["incident_id"]
    trace_id = read_trace_id(incident_id)
    hypothesis = state["hypothesis"]
    action = hypothesis.proposed_action

    decision = evaluate_risk(
        tool=action.tool,
        target_service=action.target_service,
        confidence=hypothesis.confidence,
        policy=deps.policy,
    )

    with span("policy.risk_gate", "policy", incident_id=incident_id, trace_id=trace_id) as sp:
        sp.set(
            level=decision.level,
            rule_trace=decision.rule_trace,
            confidence=hypothesis.confidence,
            tool=action.tool,
            target=action.target_service,
        )

    # escalation_level is a display counter (highest reached), not a status transition
    with session_scope() as session:
        incident = get_incident(session, incident_id)
        if incident is not None:
            incident.escalation_level = stricter(
                incident.escalation_level or "AUTO", decision.level
            )
            session.add(incident)

    escalation: dict[str, Any] = {
        "level": decision.level,
        "rule_trace": decision.rule_trace,
        "approval_id": None,
    }
    # NOTIFY inserts an AUTO approvals row as the info feed (04 §1 edge table).
    if decision.level == "NOTIFY":
        escalation["approval_id"] = create_approval(
            incident_id,
            level="NOTIFY",
            status="AUTO",
            proposed_action=action.model_dump(mode="json"),
            context=approval_context(state),
            decided_by="policy",
        )
    return {"escalation": escalation}
