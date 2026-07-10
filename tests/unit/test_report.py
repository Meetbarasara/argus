"""M11 report rendering (07 §5): metrics + EVALUATION.md sections render from fixture rows."""

from __future__ import annotations

from typing import Any

import pytest

from argus.evals.report import (
    memory_lift_table,
    model_comparison_table,
    render_report,
    summarize,
)

pytestmark = pytest.mark.unit

CASES: list[dict[str, Any]] = [
    {
        "scenario_id": "S1-v1",
        "outcome": "PASS",
        "rca_correct": True,
        "remediation_correct": True,
        "recovered": True,
        "escalation_expected": "NOTIFY",
        "escalation_actual": "NOTIFY",
        "escalation_correct": True,
        "llm_calls": 12,
        "mttr_seconds": 50,
        "cost_usd": 0.01,
        "root_cause": "shopredis down",
        "rca_judge_reason": "match",
        "incident_id": "abc12345",
    },
    {
        "scenario_id": "S3-v1",
        "outcome": "FAIL",
        "rca_correct": False,
        "remediation_correct": False,
        "recovered": False,
        "escalation_expected": "APPROVE_ACTION",
        "escalation_actual": "NOTIFY",
        "escalation_correct": False,
        "llm_calls": 20,
        "mttr_seconds": None,
        "cost_usd": 0.02,
        "root_cause": "guessed wrong",
        "rca_judge_reason": "different mechanism",
        "incident_id": "def45678",
    },
]
RUN = {
    "id": "run12345678",
    "started_at": "2026-07-07T10:00:00",
    "git_sha": "deadbeefcafe",
    "config": {"memory_enabled": True, "supervisor_model": "gemini-2.5-flash"},
}


def test_summarize_metrics() -> None:
    s = summarize(CASES)
    assert s["n"] == 2 and s["rca"] == 1 and s["remediation"] == 1 and s["passes"] == 1
    assert s["recovered"] == 1 and s["remediated"] == 1
    # S3 warranted a human but stayed NOTIFY → recall 0; no over-escalation → precision 1
    assert s["esc_recall"] == 0.0 and s["esc_precision"] == 1.0


def test_render_report_has_all_sections() -> None:
    md = render_report(RUN, CASES)
    assert "# Argus Evaluation Report" in md
    assert "RCA accuracy" in md and "1/2" in md
    assert "## Per-case" in md and "S1-v1" in md and "S3-v1" in md
    assert "## Failures" in md and "S3-v1" in md
    assert "policy_sim" in md  # AUTO_APPROVE disclosure in the method note
    assert "memory=on" in md


def test_empty_suite_renders_without_crashing() -> None:
    md = render_report(RUN, [])
    assert "N=0" in md and "## Failures" in md


def test_memory_lift_table_measures_v2_and_aggregates() -> None:
    on = [
        {"scenario_id": "S1-v1", "llm_calls": 13, "mttr_seconds": 60, "rca_correct": True},  # seed
        {"scenario_id": "S1-v2", "llm_calls": 6, "mttr_seconds": 40, "rca_correct": True},
        {"scenario_id": "S2-v2", "llm_calls": 8, "mttr_seconds": 50, "rca_correct": True},
    ]
    off = [
        {"scenario_id": "S1-v2", "llm_calls": 12, "mttr_seconds": 70, "rca_correct": True},
        {"scenario_id": "S2-v2", "llm_calls": 12, "mttr_seconds": 55, "rca_correct": False},
    ]
    md = memory_lift_table(on, off)
    assert "## Ablation: memory lift" in md
    # only the repeat (v2) cases are measured; the v1 seed row is excluded
    assert "S1-v2" in md and "S2-v2" in md and "S1-v1" not in md
    # ON 6+8=14 vs OFF 12+12=24 → round(100*10/24)=42% fewer
    assert "42% fewer with memory ON" in md
    assert "-6" in md  # S1-v2 Δ = 6-12 (ON−OFF)


def test_memory_lift_table_handles_no_off_data() -> None:
    md = memory_lift_table([{"scenario_id": "S1-v2", "llm_calls": 6}], [])
    assert "## Ablation: memory lift" in md and "insufficient data" in md


def test_model_comparison_table_side_by_side() -> None:
    md = model_comparison_table(
        [
            ("gemini-2.5-flash", {"memory_enabled": False}, CASES),
            ("groq:llama-3.3-70b-versatile", {"memory_enabled": False}, CASES),
        ]
    )
    assert "## Ablation: supervisor model" in md
    assert "gemini-2.5-flash" in md and "groq:llama-3.3-70b-versatile" in md
    assert "median cost" in md
