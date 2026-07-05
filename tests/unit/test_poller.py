import pytest

from demoworld.poller import parse_targets, stats_to_metrics

pytestmark = pytest.mark.unit


def test_parse_targets():
    assert parse_targets("shopapi=http://shopapi:8000,paymentsvc=http://paymentsvc:8000") == {
        "shopapi": "http://shopapi:8000",
        "paymentsvc": "http://paymentsvc:8000",
    }


def test_parse_targets_empty():
    assert parse_targets("") == {}
    assert parse_targets("  ") == {}


def test_stats_to_metrics_covers_all_names():
    snap = {
        "req_count_60s": 10,
        "err_rate_60s": 0.3,
        "latency_p95_ms_60s": 200,
        "deps": {"redis": "down", "payment": "up"},
        "db_pool": {"in_use": 1, "size": 2},
    }
    metrics = stats_to_metrics("shopapi", snap, "2026-07-05T00:00:00Z")
    by_key = {(m["name"], tuple(sorted(m["labels"].items()))): m["value"] for m in metrics}

    assert by_key[("req_count_60s", ())] == 10
    assert by_key[("err_rate_60s", ())] == 0.3
    assert by_key[("latency_p95_ms_60s", ())] == 200
    assert by_key[("dep_up", (("dep", "redis"),))] == 0
    assert by_key[("dep_up", (("dep", "payment"),))] == 1
    assert by_key[("db_pool_in_use", ())] == 1
    assert by_key[("db_pool_size", ())] == 2
    assert all(m["service"] == "shopapi" and m["ts"] == "2026-07-05T00:00:00Z" for m in metrics)
