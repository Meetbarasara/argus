from typing import Any

import pytest

from demoworld.alertwatch import AlertWatcher, Rule, check_rules, evaluate_rule, latest_values

pytestmark = pytest.mark.unit


def _metric(service: str, name: str, value: Any, labels: dict[str, str] | None = None) -> dict:
    return {"service": service, "name": name, "value": value, "labels": labels or {}}


ERR_RULE = Rule("high_error_rate", "err_rate_60s", ">", 0.2, 2, "critical")
DEP_RULE = Rule("dependency_down", "dep_up", "==", 0, 2, "critical")


def test_evaluate_rule_gt_and_eq():
    assert evaluate_rule(ERR_RULE, 0.4) is True
    assert evaluate_rule(ERR_RULE, 0.1) is False
    assert evaluate_rule(DEP_RULE, 0) is True
    assert evaluate_rule(DEP_RULE, 1) is False


def test_latest_values_keeps_most_recent():
    lines = [_metric("shopapi", "err_rate_60s", 0.1), _metric("shopapi", "err_rate_60s", 0.5)]
    latest = latest_values(lines)
    assert latest[("shopapi", "err_rate_60s", ())]["value"] == 0.5


def test_check_rules_finds_breach_with_dep_label():
    latest = latest_values([_metric("shopapi", "dep_up", 0, {"dep": "redis"})])
    breaches = check_rules([DEP_RULE], latest)
    assert len(breaches) == 1
    assert breaches[0].service == "shopapi"
    assert breaches[0].dep == "redis"


def test_watcher_fires_after_for_checks_then_cooldown():
    w = AlertWatcher([ERR_RULE], cooldown_s=600)
    lines = [_metric("shopapi", "err_rate_60s", 0.4)]
    assert w.tick(lines, now=0, ts="t0") == []  # first breach, count 1
    fired = w.tick(lines, now=10, ts="t1")  # count 2 -> fire
    assert len(fired) == 1
    assert fired[0]["rule"] == "high_error_rate"
    assert fired[0]["service"] == "shopapi"
    assert fired[0]["severity"] == "critical"
    assert w.tick(lines, now=20, ts="t2") == []  # within cooldown -> no refire


def test_watcher_resets_on_recovery():
    w = AlertWatcher([ERR_RULE], cooldown_s=600)
    breach = [_metric("shopapi", "err_rate_60s", 0.4)]
    ok = [_metric("shopapi", "err_rate_60s", 0.0)]
    w.tick(breach, now=0, ts="t0")  # count 1
    w.tick(ok, now=10, ts="t1")  # reset to 0
    assert w.tick(breach, now=20, ts="t2") == []  # count 1 again, no fire


def test_watcher_dependency_alert_carries_dep_label():
    w = AlertWatcher([DEP_RULE], cooldown_s=600)
    lines = [_metric("shopapi", "dep_up", 0, {"dep": "redis"})]
    w.tick(lines, now=0, ts="t0")
    fired = w.tick(lines, now=10, ts="t1")
    assert len(fired) == 1
    assert fired[0]["labels"]["dep"] == "redis"
    assert fired[0]["rule"] == "dependency_down"
