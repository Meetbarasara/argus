"""M08 budget guard boundary (milestone: "unit-test the boundary (39th ok, 40th trips)").

The guard counts single-node calls (budget.llm_calls_used) plus the parallel specialists'
calls (spec_llm_calls reducer) via total_llm_calls, so the limit holds across the fan-out."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from argus.graph.support import budget_breach_reason, total_llm_calls

pytestmark = pytest.mark.unit

_POLICY = {"limits": {"max_llm_calls_per_incident": 40, "max_wall_seconds_per_incident": 420}}


def _state(
    used: int = 0, spec: list[int] | None = None, started: str | None = None
) -> dict[str, Any]:
    budget: dict[str, Any] = {"llm_calls_used": used}
    if started is not None:
        budget["started_at_iso"] = started
    return {"budget": budget, "spec_llm_calls": spec or []}


def test_total_llm_calls_folds_specialist_counts() -> None:
    assert total_llm_calls(_state(used=10, spec=[2, 3, 1])) == 16


def test_39th_call_ok_40th_trips() -> None:
    assert budget_breach_reason(_state(used=39), _POLICY) is None
    reason = budget_breach_reason(_state(used=40), _POLICY)
    assert reason is not None and "budget" in reason.lower()


def test_boundary_counts_specialist_calls_too() -> None:
    # 36 single-node + 3 specialist = 39 (ok); 37 + 3 = 40 (trips) even though the budget
    # dict alone is under the limit — the specialists' calls must count.
    assert budget_breach_reason(_state(used=36, spec=[1, 1, 1]), _POLICY) is None
    assert budget_breach_reason(_state(used=37, spec=[1, 1, 1]), _POLICY) is not None


def test_wall_clock_budget_trips() -> None:
    old = (datetime.now(UTC) - timedelta(seconds=500)).isoformat()
    reason = budget_breach_reason(_state(used=0, started=old), _POLICY)
    assert reason is not None and "wall" in reason.lower()


def test_within_wall_clock_ok() -> None:
    recent = (datetime.now(UTC) - timedelta(seconds=5)).isoformat()
    assert budget_breach_reason(_state(used=1, started=recent), _POLICY) is None
