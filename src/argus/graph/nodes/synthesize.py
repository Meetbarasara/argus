"""synthesize (LLM supervisor): fuse the findings into a root-cause Hypothesis with a
proposed remediation. On a reviewer revise loop the latest feedback is fed back in. The
latest hypothesis is mirrored onto the incident row (root_cause + confidence) for the UI;
that is not a status change, so it bypasses the state machine."""

from __future__ import annotations

from typing import Any

from argus.agents import supervisor
from argus.db.session import session_scope
from argus.graph.support import bump_budget, read_trace_id
from argus.obs.spans import span
from argus.repo import incidents as incident_repo


def synthesize(state: dict[str, Any], deps: Any) -> dict[str, Any]:
    incident_id = state["incident_id"]
    trace_id = read_trace_id(incident_id)
    review_history = state.get("review_history", [])
    feedback = review_history[-1].feedback if review_history else None

    with span("node.synthesize", "node", incident_id=incident_id, trace_id=trace_id) as sp:
        hypothesis = supervisor.synthesize(
            deps.router,
            state["alert"],
            state.get("findings", []),
            state.get("memory_hits", []),
            feedback,
            incident_id=incident_id,
            trace_id=trace_id,
            parent_span_id=sp.span_id,
        )
        sp.set(root_cause=hypothesis.root_cause[:120], confidence=hypothesis.confidence)

    with session_scope() as session:
        incident = incident_repo.get_incident(session, incident_id)
        if incident is not None:
            incident.root_cause = hypothesis.root_cause
            incident.confidence = hypothesis.confidence
            session.add(incident)

    return {"hypothesis": hypothesis, "budget": bump_budget(state, 1)}
