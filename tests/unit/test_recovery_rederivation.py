"""M11 recovery re-derivation (07 §3): the runner grades recovery from raw metric lines,
independently of the graph's own verify_recovery. ``_rule_ok_from_lines`` maps
(breached alert, metrics.jsonl lines) → recovered? — pure, so it unit-tests directly."""

from __future__ import annotations

from typing import Any

import pytest

from argus.evals.run import _rule_ok_from_lines

pytestmark = pytest.mark.unit


def _dep_alert() -> dict[str, Any]:
    return {
        "rule": "dependency_down",
        "service": "shopapi",
        "labels": {"dep": "payment"},
        "observed": {"metric": "dep_up", "threshold": 0},
    }


def _metric(name: str, value: float, dep: str | None = None) -> dict[str, Any]:
    return {
        "service": "shopapi",
        "name": name,
        "value": value,
        "labels": {"dep": dep} if dep else {},
    }


def test_dependency_recovered_when_dep_up_returns_to_one() -> None:
    lines = [_metric("dep_up", 0, "payment"), _metric("dep_up", 1, "payment")]  # latest = 1
    assert _rule_ok_from_lines(_dep_alert(), lines) is True


def test_dependency_not_recovered_while_dep_down() -> None:
    lines = [_metric("dep_up", 1, "payment"), _metric("dep_up", 0, "payment")]  # latest = 0
    assert _rule_ok_from_lines(_dep_alert(), lines) is False


def test_dependency_matches_only_the_breached_dep_label() -> None:
    # redis back up but the breached payment dep still down → not recovered
    lines = [_metric("dep_up", 1, "redis"), _metric("dep_up", 0, "payment")]
    assert _rule_ok_from_lines(_dep_alert(), lines) is False


def test_error_rate_recovered_below_threshold() -> None:
    alert = {
        "rule": "high_error_rate",
        "service": "shopapi",
        "observed": {"metric": "err_rate_60s", "threshold": 0.2},
    }
    below = [_metric("err_rate_60s", 0.5), _metric("err_rate_60s", 0.0)]  # latest 0.0
    above = [_metric("err_rate_60s", 0.0), _metric("err_rate_60s", 0.5)]  # latest 0.5
    assert _rule_ok_from_lines(alert, below) is True
    assert _rule_ok_from_lines(alert, above) is False


def test_no_matching_metric_is_not_recovered() -> None:
    assert _rule_ok_from_lines(_dep_alert(), [_metric("req_count_60s", 100)]) is False
