"""In-process rolling 60s telemetry backing each service's ``/internal/stats`` (03 §2).

Each service records one event per request (latency + error flag). The poller reads the
resulting window every 5s. Time is injectable (``now``) so the window logic is unit
tested deterministically without sleeping (a service restart resets the window — which
is exactly why verify_recovery waits for two consecutive healthy checks).
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from typing import Any


def percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile. Empty input yields 0.0."""
    if not values:
        return 0.0
    ordered = sorted(values)
    k = math.ceil(pct / 100.0 * len(ordered))
    k = max(1, min(k, len(ordered)))
    return ordered[k - 1]


class RollingStats:
    """Thread-safe rolling window of (timestamp, latency_ms, is_error) events."""

    def __init__(self, window_seconds: float = 60.0) -> None:
        self._window = window_seconds
        self._events: deque[tuple[float, float, bool]] = deque()
        self._lock = threading.Lock()

    def record(self, latency_ms: float, is_error: bool, *, now: float | None = None) -> None:
        t = time.monotonic() if now is None else now
        with self._lock:
            self._events.append((t, latency_ms, is_error))
            self._evict(t)

    def _evict(self, now: float) -> None:
        cutoff = now - self._window
        while self._events and self._events[0][0] < cutoff:
            self._events.popleft()

    def snapshot(self, *, now: float | None = None) -> dict[str, Any]:
        t = time.monotonic() if now is None else now
        with self._lock:
            self._evict(t)
            latencies = [e[1] for e in self._events]
            errors = sum(1 for e in self._events if e[2])
            count = len(self._events)
        return {
            "req_count_60s": count,
            "err_count_60s": errors,
            "err_rate_60s": round(errors / count, 4) if count else 0.0,
            "latency_p95_ms_60s": round(percentile(latencies, 95), 2),
        }
