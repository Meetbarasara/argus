"""M08 fan-out wave logic (dependency-aware dispatch + degradation gate), unit-tested pure.

``remaining_steps`` drives both the first wave (after plan) and each dependent wave (at the
join); ``investigation_degraded`` is the > 50%-failed escalation predicate."""

from __future__ import annotations

from typing import Any

import pytest

from argus.agents.schemas import Finding, InvestigationPlan, PlanStep
from argus.graph import fanout

pytestmark = pytest.mark.unit


def _step(step_id: str, specialist: str, deps: list[str] | None = None) -> PlanStep:
    return PlanStep(id=step_id, specialist=specialist, objective="x", depends_on=deps or [])


def _finding(step_id: str, specialist: str, confidence: float = 0.9) -> Finding:
    return Finding(
        step_id=step_id, specialist=specialist, summary="s", evidence=[], confidence=confidence
    )


def _state(
    steps: list[PlanStep], findings: list[Finding] | None = None, baseline: int = 0
) -> dict[str, Any]:
    return {
        "plan": InvestigationPlan(steps=steps, rationale="r"),
        "findings": findings or [],
        "cycle_findings_baseline": baseline,
    }


def test_wave_one_is_the_independent_steps() -> None:
    steps = [_step("step-1", "log_analyst"), _step("step-2", "metrics_analyst", ["step-1"])]
    remaining = fanout.remaining_steps(_state(steps))
    assert [s.id for s in remaining] == ["step-1"]  # step-2 waits on its dependency


def test_wave_two_dispatches_after_dependency_completes() -> None:
    steps = [_step("step-1", "log_analyst"), _step("step-2", "metrics_analyst", ["step-1"])]
    state = _state(steps, findings=[_finding("step-1", "log_analyst")])
    assert [s.id for s in fanout.remaining_steps(state)] == ["step-2"]


def test_no_remaining_when_all_steps_done() -> None:
    steps = [_step("step-1", "log_analyst"), _step("step-2", "metrics_analyst", ["step-1"])]
    findings = [_finding("step-1", "log_analyst"), _finding("step-2", "metrics_analyst")]
    assert fanout.remaining_steps(_state(steps, findings)) == []


def test_failed_dependency_still_unblocks_dependents() -> None:
    # a confidence-0 finding still counts as "ran" so a dependent step isn't wedged
    steps = [_step("step-1", "log_analyst"), _step("step-2", "metrics_analyst", ["step-1"])]
    state = _state(steps, findings=[_finding("step-1", "log_analyst", 0.0)])
    assert [s.id for s in fanout.remaining_steps(state)] == ["step-2"]


def test_baseline_scopes_remaining_to_current_cycle() -> None:
    # a prior cycle's finding sits before the baseline, so this cycle must re-run the step
    steps = [_step("step-1", "log_analyst")]
    state = _state(steps, findings=[_finding("step-1", "log_analyst")], baseline=1)
    assert [s.id for s in fanout.remaining_steps(state)] == ["step-1"]


def test_investigation_degraded_when_majority_failed() -> None:
    steps = [_step(f"step-{i}", "log_analyst") for i in (1, 2, 3)]
    findings = [
        _finding("step-1", "log_analyst", 0.0),
        _finding("step-2", "log_analyst", 0.0),
        _finding("step-3", "log_analyst", 0.9),
    ]
    assert fanout.investigation_degraded(_state(steps, findings)) is True  # 2/3 > 50%


def test_investigation_not_degraded_at_exactly_half() -> None:
    steps = [_step("step-1", "log_analyst"), _step("step-2", "metrics_analyst")]
    findings = [_finding("step-1", "log_analyst", 0.0), _finding("step-2", "metrics_analyst", 0.9)]
    assert fanout.investigation_degraded(_state(steps, findings)) is False  # exactly 50%


def test_dependency_context_only_includes_named_deps() -> None:
    steps = [_step("step-2", "metrics_analyst", ["step-1"])]
    findings = [_finding("step-1", "log_analyst"), _finding("step-9", "change_analyst")]
    ctx = fanout.dependency_context(steps[0], _state(steps, findings))
    assert "log_analyst" in ctx and "change_analyst" not in ctx


def test_dependency_context_empty_without_deps() -> None:
    step = _step("step-1", "log_analyst")
    assert fanout.dependency_context(step, _state([step])) == ""
