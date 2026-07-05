"""World gate — the M01 finish line.

For each of the 5 fault scenarios: reset the world, inject the fault, assert its expected
alert fires and its evidence trail exists, remediate, and assert the world recovers. This
is the ground truth the whole platform later builds on, so it runs against the real
running world (in the tester container):

    docker compose --profile world up -d
    docker compose run --rm tester pytest -q -m world tests/integration/test_scenarios.py
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from demoworld.common.jsonlog import read_jsonl
from demoworld.inject import apply_fault

pytestmark = pytest.mark.world

ACTUATOR = os.environ.get("ACTUATOR_URL", "http://actuator:8000")
TOKEN = os.environ.get("ACTUATOR_TOKEN", "dev-actuator-token")
WS = Path(os.environ.get("WORLDSTATE_PATH", "/worldstate"))


@pytest.fixture
def client() -> Iterator[httpx.Client]:
    with httpx.Client(base_url=ACTUATOR, headers={"X-Actuator-Token": TOKEN}, timeout=20.0) as c:
        yield c


# --------------------------------------------------------------- worldstate readers
def _alerts() -> list[dict[str, Any]]:
    return read_jsonl(WS / "alerts" / "sent.jsonl")


def _shopapi_errors() -> list[dict[str, Any]]:
    return [ln for ln in read_jsonl(WS / "logs" / "shopapi.jsonl") if ln.get("level") == "ERROR"]


def _deploys() -> list[dict[str, Any]]:
    return read_jsonl(WS / "deploys" / "history.jsonl")


def _latest_metric(service: str, name: str, labels: dict[str, str] | None = None) -> Any:
    val: Any = None
    for m in read_jsonl(WS / "metrics" / "metrics.jsonl"):
        matches = m.get("service") == service and m.get("name") == name
        if matches and (labels is None or (m.get("labels") or {}) == labels):
            val = m.get("value")
    return val


# --------------------------------------------------------------- polling helpers
def _wait_for_alert(service: str, rules: set[str], timeout: float = 90) -> dict[str, Any] | None:
    end = time.time() + timeout
    while time.time() < end:
        for a in _alerts():
            if a.get("service") == service and a.get("rule") in rules:
                return a
        time.sleep(3)
    return None


def _healthy(*, need_redis_up: bool = False) -> bool:
    err = _latest_metric("shopapi", "err_rate_60s")
    lat = _latest_metric("shopapi", "latency_p95_ms_60s")
    if err is None or err >= 0.2:
        return False
    if lat is not None and lat >= 1500:
        return False
    if need_redis_up:
        return _latest_metric("shopapi", "dep_up", {"dep": "redis"}) == 1
    return True


def _wait_for_recovery(timeout: float = 130, *, need_redis_up: bool = False) -> bool:
    end = time.time() + timeout
    consecutive = 0
    while time.time() < end:
        consecutive = consecutive + 1 if _healthy(need_redis_up=need_redis_up) else 0
        if consecutive >= 2:  # two consecutive healthy checks (verify_recovery semantics)
            return True
        time.sleep(6)
    return False


def _reset(client: httpx.Client) -> None:
    """Return the world to a clean baseline before a scenario."""
    client.post("/restart", json={"service": "shopredis"})  # undo S1 if a prior run left it stopped
    time.sleep(4)
    client.post("/admin/reset_worldstate")  # clear worldstate, reseed baseline config, clear chaos
    client.post("/restart", json={"service": "alertwatch"})  # clear cooldown/consecutive state
    end = time.time() + 45  # settle: config reloads, metrics repopulate, err_rate returns to ~0
    while time.time() < end:
        if _healthy():
            return
        time.sleep(4)


@pytest.fixture(scope="module", autouse=True)
def _cleanup() -> Iterator[None]:
    yield
    with httpx.Client(base_url=ACTUATOR, headers={"X-Actuator-Token": TOKEN}, timeout=20.0) as c:
        c.post("/restart", json={"service": "shopredis"})
        c.post("/admin/reset_worldstate")


# --------------------------------------------------------------- scenarios
def test_s1_redis_down(client: httpx.Client) -> None:
    _reset(client)
    apply_fault(client, "S1")
    alert = _wait_for_alert("shopapi", {"dependency_down", "high_error_rate"})
    assert alert is not None, "S1: no alert fired within 90s"
    assert _latest_metric("shopapi", "dep_up", {"dep": "redis"}) == 0
    assert any(e.get("err_type") == "ConnectionError" for e in _shopapi_errors()), (
        "S1: no redis error log"
    )
    client.post("/restart", json={"service": "shopredis"})  # remediation
    assert _wait_for_recovery(need_redis_up=True), "S1 did not recover after restart"


def test_s2_payment_latency(client: httpx.Client) -> None:
    _reset(client)
    apply_fault(client, "S2")
    alert = _wait_for_alert("shopapi", {"high_latency_p95", "high_error_rate"})
    assert alert is not None, "S2: no alert fired within 90s"
    assert any(e.get("path") == "/checkout" for e in _shopapi_errors()), "S2: no checkout error log"
    assert _deploys() == [], "S2 must leave no deploy in history (its signature)"
    client.post("/restart", json={"service": "paymentsvc"})  # restart clears in-memory chaos
    assert _wait_for_recovery(), "S2 did not recover after paymentsvc restart"


def test_s3_bad_deploy_env(client: httpx.Client) -> None:
    _reset(client)
    out = apply_fault(client, "S3")
    deploy_id = out["fault"]["deploy_id"]
    alert = _wait_for_alert("shopapi", {"high_error_rate"})
    assert alert is not None, "S3: no alert fired within 90s"
    assert any("payment_url" in d.get("changes", {}) for d in _deploys()), (
        "S3: no payment_url deploy"
    )
    assert any(e.get("path") == "/checkout" for e in _shopapi_errors()), "S3: no checkout error log"
    client.post("/rollback", json={"deploy_id": deploy_id, "author": "human"})
    assert _wait_for_recovery(), "S3 did not recover after rollback"


def test_s4_db_pool_exhaustion(client: httpx.Client) -> None:
    _reset(client)
    out = apply_fault(client, "S4")
    deploy_id = out["fault"]["deploy_id"]
    alert = _wait_for_alert("shopapi", {"high_error_rate", "high_latency_p95"})
    assert alert is not None, "S4: no alert fired within 90s"
    assert any(e.get("err_type") == "PoolTimeout" for e in _shopapi_errors()), (
        "S4: no pool-timeout log"
    )
    assert any("db_pool_size" in d.get("changes", {}) for d in _deploys()), (
        "S4: no db_pool_size deploy"
    )
    client.post("/rollback", json={"deploy_id": deploy_id, "author": "human"})
    assert _wait_for_recovery(), "S4 did not recover after rollback"


def test_s5_feature_flag_500(client: httpx.Client) -> None:
    _reset(client)
    out = apply_fault(client, "S5")
    deploy_id = out["fault"]["deploy_id"]
    alert = _wait_for_alert("shopapi", {"high_error_rate"})
    assert alert is not None, "S5: no alert fired within 90s"
    assert any("feature_flags.recs_v2" in d.get("changes", {}) for d in _deploys()), (
        "S5: no recs_v2 deploy"
    )
    assert any(e.get("path") == "/products" for e in _shopapi_errors()), "S5: no products error log"
    client.post("/rollback", json={"deploy_id": deploy_id, "author": "human"})
    assert _wait_for_recovery(), "S5 did not recover after rollback"
