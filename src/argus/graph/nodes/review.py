"""review (LLM reviewer, different provider than the specialists): independently judge the
hypothesis and append the verdict to review_history. Routing (approve -> gate, revise ->
resynthesize, reject/exhausted -> take_over) is decided in build.py from review_history."""

from __future__ import annotations

from typing import Any

from argus.agents import reviewer
from argus.graph.support import bump_budget, read_trace_id
from argus.obs.spans import span


def review(state: dict[str, Any], deps: Any) -> dict[str, Any]:
    incident_id = state["incident_id"]
    trace_id = read_trace_id(incident_id)
    with span("node.review", "node", incident_id=incident_id, trace_id=trace_id) as sp:
        verdict = reviewer.review(
            deps.router,
            state["hypothesis"],
            state.get("findings", []),
            incident_id=incident_id,
            trace_id=trace_id,
            parent_span_id=sp.span_id,
        )
        sp.set(verdict=verdict.verdict)
    return {"review_history": [verdict], "budget": bump_budget(state, 1)}
