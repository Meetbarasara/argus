import pytest

from demoworld.common.stats import RollingStats, percentile

pytestmark = pytest.mark.unit


def test_percentile_nearest_rank() -> None:
    assert percentile([], 95) == 0.0
    assert percentile([5], 95) == 5
    # 20 values 1..20 → ceil(0.95*20)=19th smallest = 19
    assert percentile([float(i) for i in range(1, 21)], 95) == 19


def test_empty_snapshot_is_all_zero() -> None:
    snap = RollingStats().snapshot(now=0.0)
    assert snap == {
        "req_count_60s": 0,
        "err_count_60s": 0,
        "err_rate_60s": 0.0,
        "latency_p95_ms_60s": 0.0,
    }


def test_counts_error_rate_and_p95() -> None:
    s = RollingStats()
    for i in range(20):
        s.record(latency_ms=float(i + 1), is_error=(i < 5), now=0.0)
    snap = s.snapshot(now=0.0)
    assert snap["req_count_60s"] == 20
    assert snap["err_count_60s"] == 5
    assert snap["err_rate_60s"] == 0.25
    assert snap["latency_p95_ms_60s"] == 19.0


def test_events_evicted_past_window() -> None:
    s = RollingStats(window_seconds=60.0)
    s.record(latency_ms=100.0, is_error=True, now=0.0)
    assert s.snapshot(now=30.0)["req_count_60s"] == 1  # still inside window
    assert s.snapshot(now=61.0)["req_count_60s"] == 0  # aged out
