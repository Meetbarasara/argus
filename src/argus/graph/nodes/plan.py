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
    # record where this cycle's findings begin so the fan-out join (M08) can scope wave and
    # degradation checks to the current plan, not evidence carried over from a prior replan.
    baseline = len(state.get("findings", []))
    return {
        "plan": investigation_plan,
        "cycle_findings_baseline": baseline,
        "budget": bump_budget(state, 1),
    }
