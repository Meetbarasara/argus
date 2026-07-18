"""select_case_incident (07 §3): a case can spawn several incidents (alert re-fires + the
service-level dedupe gap), so grade the one the agent actually investigated (max llm_calls),
not a 0-call straggler await_incident happened to lock onto. Pure → no docker/DB."""

from __future__ import annotations

from typing import Any

import pytest

from argus.evals.run import select_case_incident

pytestmark = pytest.mark.unit


def _inc(iid: str, calls: int, created: str, status: str = "RESOLVED") -> dict[str, Any]:
    return {"id": iid, "llm_calls": calls, "created_at": created, "status": status}


def test_single_candidate_is_returned() -> None:
    cur = _inc("a", 12, "2026-07-18T10:00:00")
    assert select_case_incident([cur], cur)["id"] == "a"


def test_empty_candidates_falls_back_to_current() -> None:
    cur = _inc("a", 12, "2026-07-18T10:00:00")
    assert select_case_incident([], cur)["id"] == "a"


def test_picks_most_investigated_over_zero_call_straggler() -> None:
    # the real bug: await_incident locked onto the newest 0-call straggler; the 14-call incident is
    # the one the agent actually worked, so grade THAT (this is the S1-v3 / S2-v2 pattern).
    straggler = _inc("straggler", 0, "2026-07-18T10:05:00", status="FAILED")
    real = _inc("real", 14, "2026-07-18T10:01:00", status="RESOLVED")
    assert select_case_incident([real, straggler], straggler)["id"] == "real"


def test_ties_break_to_most_recent() -> None:
    older = _inc("older", 10, "2026-07-18T10:00:00")
    newer = _inc("newer", 10, "2026-07-18T10:03:00")
    assert select_case_incident([older, newer], older)["id"] == "newer"


def test_candidates_without_id_are_ignored() -> None:
    cur = _inc("cur", 5, "2026-07-18T10:00:00")
    noise = {"llm_calls": 99, "created_at": "2026-07-18T10:09:00"}  # no id → not a real incident
    assert select_case_incident([noise, cur], cur)["id"] == "cur"


def test_effort_based_not_outcome_biased() -> None:
    # a big FAILED investigation outranks a small RESOLVED one — we choose by EFFORT (llm_calls),
    # never by outcome, so this fix can't be accused of inflating the pass rate.
    big_fail = _inc("big", 25, "2026-07-18T10:04:00", status="FAILED")
    small_ok = _inc("small", 14, "2026-07-18T10:01:00", status="RESOLVED")
    assert select_case_incident([small_ok, big_fail], big_fail)["id"] == "big"
