"""The three specialist nodes (log_analyst, metrics_analyst, change_analyst).

M08 fans them out with the Send API: ``plan`` dispatches one Send per ready step, so a node
invocation runs exactly the step in ``state["current_step"]`` and appends a single finding.
Findings accumulate through the ``operator.add`` reducer (parallel-safe); the LLM-call count
lands in the ``spec_llm_calls`` reducer, NEVER the ``budget`` dict — three concurrent nodes
writing the non-reducer ``budget`` channel in one superstep would raise InvalidUpdateError.
The join (``gather``) folds those counts back into the running total.

The sequential fallback (``PARALLEL_SPECIALISTS=false``) keeps the M05 shape — each node runs
all of its assigned steps in one call — so the A/B latency demo stays runnable.

Resilience (M08 / 04 §1): a failed step is evidence too. ``run_step`` already degrades an LLM
or tool failure to a confidence-0.0 finding; this node adds an outer guard so an
infrastructure error (span/DB) can never crash the run with a naked raise either."""

from __future__ import annotations

from typing import Any

import structlog

from argus.agents import specialists as specialist_agent
from argus.agents.schemas import Finding, PlanStep
from argus.graph import fanout
from argus.graph.support import read_trace_id
from argus.obs.spans import span

log = structlog.get_logger(__name__)


def _failed_finding(specialist: str, step_id: str, exc: Exception) -> Finding:
    return Finding(
        step_id=step_id,
        specialist=specialist,
        summary=f"specialist failed: {exc}",
        evidence=[],
        confidence=0.0,
    )


def _run_step(
    state: dict[str, Any], deps: Any, specialist: str, step: PlanStep
) -> tuple[Finding, int]:
    """Run one plan step under its own node span. Never raises: any failure — provider,
    tool, or infrastructure — becomes a confidence-0.0 finding (04 §1 edge table)."""
    incident_id = state["incident_id"]
    context = fanout.dependency_context(step, state)
    try:
        trace_id = read_trace_id(incident_id)
        with span(f"node.{specialist}", "node", incident_id=incident_id, trace_id=trace_id) as sp:
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
            sp.set(step=step.id, confidence=finding.confidence, llm_calls=calls)
        return finding, calls
    except Exception as exc:  # node-level safety net beyond run_step's own degrade path
        log.warning("specialist.node_failed", specialist=specialist, step=step.id, error=str(exc))
        return _failed_finding(specialist, step.id, exc), 0


def _dispatch(state: dict[str, Any], deps: Any, specialist: str) -> dict[str, Any]:
    step = state.get("current_step")
    if step is not None:  # M08 parallel fan-out: exactly one assigned step this invocation
        finding, calls = _run_step(state, deps, specialist, step)
        return {"findings": [finding], "spec_llm_calls": [calls]}

    # sequential fallback: run every step assigned to this specialist in one call
    plan = state.get("plan")
    if plan is None:
        return {}
    steps = [s for s in plan.steps if s.specialist == specialist]
    if not steps:
        return {}
    findings: list[Finding] = []
    total_calls = 0
    for step in steps:
        finding, calls = _run_step(state, deps, specialist, step)
        findings.append(finding)
        total_calls += calls
    return {"findings": findings, "spec_llm_calls": [total_calls]}


def log_analyst(state: dict[str, Any], deps: Any) -> dict[str, Any]:
    return _dispatch(state, deps, "log_analyst")


def metrics_analyst(state: dict[str, Any], deps: Any) -> dict[str, Any]:
    return _dispatch(state, deps, "metrics_analyst")


def change_analyst(state: dict[str, Any], deps: Any) -> dict[str, Any]:
    return _dispatch(state, deps, "change_analyst")
