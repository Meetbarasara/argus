"""plan (LLM supervisor): produce the InvestigationPlan. Budget guarding happens in the
build.py wrapper before this runs, so the node body assumes it is within budget."""

from __future__ import annotations

from typing import Any

from argus.agents import supervisor
from argus.graph.support import bump_budget, read_trace_id
from argus.obs.spans import span


def plan(state: dict[str, Any], deps: Any) -> dict[str, Any]:
    incident_id = state["incident_id"]
    trace_id = read_trace_id(incident_id)
    with span("node.plan", "node", incident_id=incident_id, trace_id=trace_id) as sp:
        investigation_plan = supervisor.plan(
            deps.router,
            state["alert"],
            state.get("service_catalog", {}),
            state.get("memory_hits", []),
            state.get("fast_path_hint"),
            incident_id=incident_id,
            trace_id=trace_id,
            parent_span_id=sp.span_id,
        )
        sp.set(steps=len(investigation_plan.steps))
    return {"plan": investigation_plan, "budget": bump_budget(state, 1)}
