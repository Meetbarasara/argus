"""remediate (deterministic executor): the ONLY node permitted to run mutating tools.
Moves the incident to REMEDIATING, executes the proposed action through the tool executor
(which enforces that mutating tools run only here), and records the attempt. A failed
attempt is not fatal — verify_recovery will find no recovery and route to replan/take_over."""

from __future__ import annotations

from typing import Any

from argus.agents.schemas import RemediationAction
from argus.db.session import session_scope
from argus.errors import ToolError
from argus.graph.support import now_iso, read_trace_id
from argus.obs.spans import span
from argus.repo import incidents as incident_repo
from argus.tools.registry import ToolContext


def _effective_action(state: dict[str, Any]) -> RemediationAction:
    """The action to execute: a human-approved/modified action (M06 resume payload) if
    present, otherwise the hypothesis's proposed action (AUTO/NOTIFY paths)."""
    raw = (state.get("approval_decision") or {}).get("action")
    if raw:
        return RemediationAction.model_validate(raw)
    return state["hypothesis"].proposed_action


def remediate(state: dict[str, Any], deps: Any) -> dict[str, Any]:
    incident_id = state["incident_id"]
    trace_id = read_trace_id(incident_id)
    action = _effective_action(state)

    with session_scope() as session:
        incident = incident_repo.get_incident(session, incident_id)
        if incident is not None and incident.status != "REMEDIATING":
            incident_repo.transition(session, incident, "REMEDIATING")

    result: dict[str, Any]
    status = "OK"
    with span("node.remediate", "node", incident_id=incident_id, trace_id=trace_id) as sp:
        try:
            result = deps.executor.run(
                "remediate",
                action.tool,
                dict(action.params),
                context=ToolContext(
                    node="remediate",
                    incident_id=incident_id,
                    trace_id=trace_id,
                    parent_span_id=sp.span_id,
                ),
            )
        except ToolError as exc:  # unexpected actuator failure — record, let verify decide
            result = {"ok": False, "error": str(exc)}
            status = "ERROR"
        sp.set(tool=action.tool, target=action.target_service, status=status)

    action_dump = action.model_dump(mode="json")
    with session_scope() as session:
        incident = incident_repo.get_incident(session, incident_id)
        if incident is not None:
            incident.remediation = {"action": action_dump, "result": result}
            session.add(incident)

    return {"remediation_attempts": [{"action": action_dump, "result": result, "ts": now_iso()}]}
