import json

import httpx
import pytest

from demoworld.inject import SCENARIOS, apply_fault

pytestmark = pytest.mark.unit


def _mock_client(recorder: list) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        recorder.append((request.url.path, body))
        return httpx.Response(200, json={"deploy_id": "d-0001", "ok": True})

    return httpx.Client(
        base_url="http://actuator",
        transport=httpx.MockTransport(handler),
        headers={"X-Actuator-Token": "t"},
    )


def test_scenario_map_is_s1_to_s5():
    assert set(SCENARIOS) == {"S1", "S2", "S3", "S4", "S5"}


def test_s1_stops_shopredis():
    rec: list = []
    with _mock_client(rec) as c:
        apply_fault(c, "S1")
    assert rec[-1] == ("/admin/stop_container", {"service": "shopredis"})


def test_s2_sets_payment_chaos():
    rec: list = []
    with _mock_client(rec) as c:
        apply_fault(c, "S2")
    assert rec[-1][0] == "/chaos"
    assert rec[-1][1] == {"service": "paymentsvc", "extra_latency_ms": 3000}


def test_s3_deploys_bad_payment_url():
    rec: list = []
    with _mock_client(rec) as c:
        apply_fault(c, "S3")
    assert rec[-1][0] == "/deploy"
    assert rec[-1][1]["service"] == "shopapi"
    assert rec[-1][1]["changes"] == {"payment_url": "http://paymentsvc:9999"}


def test_s4_deploys_small_pool():
    rec: list = []
    with _mock_client(rec) as c:
        apply_fault(c, "S4")
    assert rec[-1][1]["changes"] == {"db_pool_size": 2}


def test_s5_deploys_broken_flag():
    rec: list = []
    with _mock_client(rec) as c:
        apply_fault(c, "S5")
    assert rec[-1][1]["changes"] == {"feature_flags.recs_v2": True}


def test_decoys_precede_the_fault():
    rec: list = []
    with _mock_client(rec) as c:
        apply_fault(c, "S3", decoy_deploys=2)
    assert len(rec) == 3
    assert all(r[0] == "/deploy" and "request_timeout_ms" in r[1]["changes"] for r in rec[:2])
    assert rec[2][1]["changes"] == {"payment_url": "http://paymentsvc:9999"}


def test_unknown_scenario_raises():
    rec: list = []
    with _mock_client(rec) as c, pytest.raises(ValueError):
        apply_fault(c, "S9")
