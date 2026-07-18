"""M12 demo storyline (01 §demo): the memory-lift comparison renderer + the two-act beat
orchestration run without docker or LLM quota — a stub Platform drives the arc."""

from __future__ import annotations

from typing import Any

import pytest

from argus.demo import comparison_table, run_demo
from argus.evals.run import Platform

pytestmark = pytest.mark.unit


def test_comparison_table_shows_memory_lift() -> None:
    cold = {"llm_calls": 13, "mttr_seconds": 120, "memory_used": False}
    warm = {"llm_calls": 6, "mttr_seconds": 60, "memory_used": True}
    t = comparison_table(cold, warm)
    assert "Memory lift" in t
    assert "13" in t and "6" in t
    assert "54% fewer" in t  # round(100 * (13 - 6) / 13) == 54
    assert "True" in t  # memory_used on the warm (repeat) run


def test_comparison_table_handles_zero_cold_calls() -> None:
    t = comparison_table({"llm_calls": 0}, {"llm_calls": 0})
    assert "—" in t  # no ZeroDivisionError


def _stub_platform() -> tuple[Platform, list[str]]:
    seen: list[str] = []
    inc: dict[str, Any] = {
        "id": "abc12345",
        "status": "RESOLVED",
        "mttr_seconds": 50,
        "llm_calls": 7,
        "memory_used": True,
    }
    return (
        Platform(
            inject=lambda k, _p: seen.append(k),
            reset=lambda: None,
            await_incident=lambda _s, _t: inc["id"],
            fetch_incident=lambda _i: inc,
            await_terminal=lambda _i, _t: inc,
            recovered=lambda _a: True,
        ),
        seen,
    )


def test_run_demo_auto_runs_both_acts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("argus.demo.time.sleep", lambda _s: None)  # no narration pauses in tests
    platform, seen = _stub_platform()
    out = run_demo(platform, auto=True, approve=lambda _i: None, ui_url="http://ui")
    assert out["first"]["status"] == "RESOLVED"
    assert out["second"]["status"] == "RESOLVED"
    assert seen == ["db_pool_exhaustion", "db_pool_exhaustion"]  # S4 injected in both acts
