"""The three specialist nodes (log_analyst, metrics_analyst, change_analyst). In M05 they
run sequentially (M08 fans them out with the Send API). Each node runs only the plan steps
assigned to its specialist, appends the resulting findings, and bills the LLM calls it
made to the budget. A specialist with no assigned steps is a no-op."""

from __future__ import annotations

from typing import Any

from argus.agents import specialists as specialist_agent
from argus.agents.schemas import Finding
from argus.graph.support import bump_budget, read_trace_id
from argus.obs.spans import span


def _dependency_context(prior_findings: list[Finding]) -> str:
    if not prior_findings:
        return ""
    lines = [f"- [{f.specialist}] {f.summary}" for f in prior_findings]
    return "Context from earlier investigation steps:\n" + "\n".join(lines)


def _run(state: dict[str, Any], deps: Any, specialist: str) -> dict[str, Any]:
    investigation_plan = state.get("plan")
    if investigation_plan is None:
        return {}
    steps = [step for step in investigation_plan.steps if step.specialist == specialist]
    if not steps:
        return {}

    incident_id = state["incident_id"]
    trace_id = read_trace_id(incident_id)
    context = _dependency_context(state.get("findings", []))

    findings: list[Finding] = []
    llm_calls = 0
    with span(f"node.{specialist}", "node", incident_id=incident_id, trace_id=trace_id) as sp:
        for step in steps:
            finding, calls = specialist_agent.run_step(
                deps.router,
                deps.executor,
                specialist,
                state["alert"],
                step,
                context,
                incident_id=incident_id,
                trace_id=trace_id,
                parent_span_id=sp.span_id,
            )
            findings.append(finding)
            llm_calls += calls
        sp.set(steps=len(steps), findings=len(findings), llm_calls=llm_calls)

    return {"findings": findings, "budget": bump_budget(state, llm_calls)}


def log_analyst(state: dict[str, Any], deps: Any) -> dict[str, Any]:
    return _run(state, deps, "log_analyst")


def metrics_analyst(state: dict[str, Any], deps: Any) -> dict[str, Any]:
    return _run(state, deps, "metrics_analyst")


def change_analyst(state: dict[str, Any], deps: Any) -> dict[str, Any]:
    return _run(state, deps, "change_analyst")
