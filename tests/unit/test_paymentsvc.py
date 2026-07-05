import pytest
from fastapi.testclient import TestClient

from demoworld.paymentsvc.app import create_app

pytestmark = pytest.mark.unit


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("WORLDSTATE_PATH", str(tmp_path))
    app = create_app(start_polling=False)
    return TestClient(app)


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_pay_ok_reports_base_latency(client):
    r = client.post("/pay", json={"amount": 10.0})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["latency_ms"] >= 40  # base_latency_ms baseline


def test_pay_accepts_empty_body(client):
    assert client.post("/pay").status_code == 200


def test_internal_stats_shape(client):
    client.post("/pay", json={})
    snap = client.get("/internal/stats").json()
    for key in (
        "req_count_60s",
        "err_count_60s",
        "err_rate_60s",
        "latency_p95_ms_60s",
        "config_version",
    ):
        assert key in snap
    assert snap["service"] == "paymentsvc"
    assert snap["req_count_60s"] >= 1
    assert snap["config_version"] == "d-0000"


def test_chaos_adds_latency(client):
    client.post("/admin/chaos", json={"extra_latency_ms": 150})
    r = client.post("/pay", json={})
    assert r.json()["latency_ms"] >= 190  # 40 base + 150 chaos
