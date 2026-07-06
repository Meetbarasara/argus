"""Pure fan-out helpers for the M08 parallel specialists (04 §1: "M08 switches to parallel
fan-out with LangGraph's Send API and a joining reducer").

The dispatch is *per step, dependency-aware*: after ``plan`` the steps with no unmet
``depends_on`` run as one wave (Send fan-out); any dependent steps run in a following wave
with their dependencies' findings already in state (≤2 waves in practice — the plan schema
caps at 5 steps). These functions are deterministic and LangGraph-free so ``build.py`` can
turn their output into ``Send`` objects and the unit tests can exercise the wave logic
directly.

Cycle scoping: ``plan`` records ``cycle_findings_baseline = len(findings)`` when it runs, so
after a replan (verify_recovery → plan) the join still measures only the *current* cycle's
findings — prior attempts' findings stay as evidence but don't confuse wave/degradation
accounting."""

from __future__ import annotations

from typing import Any

from argus.agents.schemas import Finding, PlanStep


def cycle_findings(state: dict[str, Any]) -> list[Finding]:
    """The findings produced in the current plan cycle (from the baseline plan set)."""
    findings = state.get("findings", [])
    baseline = int(state.get("cycle_findings_baseline", 0))
    return list(findings[baseline:])


def _processed_step_ids(state: dict[str, Any]) -> set[str]:
    """Step ids that already produced a finding this cycle — including failed steps, whose
    confidence-0 finding still counts as "ran" so we neither re-run nor block dependents."""
    return {f.step_id for f in cycle_findings(state)}


def remaining_steps(state: dict[str, Any]) -> list[PlanStep]:
    """The next wave: plan steps not yet run this cycle whose ``depends_on`` are all satisfied.

    Called both right after ``plan`` (no findings yet → the no-dependency steps) and at the
    join after each wave (dependent steps whose prerequisites just completed)."""
    plan = state.get("plan")
    if plan is None:
        return []
    done = _processed_step_ids(state)
    return [
        step
        for step in plan.steps
        if step.id not in done and all(dep in done for dep in step.depends_on)
    ]


def dependency_context(step: PlanStep, state: dict[str, Any]) -> str:
    """Summaries of the findings this step depends on, injected into the specialist prompt so
    a dependent step sees its prerequisites' output (04 §4 ``context_from_dependencies``)."""
    if not step.depends_on:
        return ""
    wanted = set(step.depends_on)
    lines = [
        f"- [{f.specialist}] {f.summary}" for f in cycle_findings(state) if f.step_id in wanted
    ]
    if not lines:
        return ""
    return "Context from earlier investigation steps:\n" + "\n".join(lines)


def investigation_degraded(state: dict[str, Any]) -> bool:
    """True when > 50% of this cycle's findings are failed (confidence 0.0). The join escalates
    to take_over rather than synthesizing a hypothesis on mostly-empty evidence (M08)."""
    cycle = cycle_findings(state)
    if not cycle:
        return False
    degraded = sum(1 for f in cycle if f.confidence <= 0.0)
    return degraded * 2 > len(cycle)
