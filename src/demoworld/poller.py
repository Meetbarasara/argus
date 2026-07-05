"""poller — samples each service's /internal/stats every 5s and writes 03 §2 metric
lines to worldstate/metrics/metrics.jsonl. This file-based telemetry is what the
platform's metrics tools read (ADR-09)."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import httpx

from demoworld.common import settings
from demoworld.common.jsonlog import append_jsonl, now_iso

POLL_INTERVAL_S = 5.0
HEARTBEAT = Path("/tmp/heartbeat")  # noqa: S108 - container-local liveness marker


def parse_targets(raw: str) -> dict[str, str]:
    """Parse ``name=url,name=url`` into a mapping."""
    targets: dict[str, str] = {}
    for part in raw.split(","):
        name, _, url = part.strip().partition("=")
        if name and url:
            targets[name.strip()] = url.strip()
    return targets


def stats_to_metrics(service: str, snap: dict[str, Any], ts: str) -> list[dict[str, Any]]:
    """Flatten an /internal/stats snapshot into 03 §2 metric records."""
    out: list[dict[str, Any]] = []
    for name in ("req_count_60s", "err_rate_60s", "latency_p95_ms_60s"):
        out.append(
            {"ts": ts, "service": service, "name": name, "value": snap.get(name, 0), "labels": {}}
        )
    for dep, status in snap.get("deps", {}).items():
        out.append(
            {
                "ts": ts,
                "service": service,
                "name": "dep_up",
                "value": 1 if status == "up" else 0,
                "labels": {"dep": dep},
            }
        )
    pool = snap.get("db_pool", {})
    out.append(
        {
            "ts": ts,
            "service": service,
            "name": "db_pool_in_use",
            "value": pool.get("in_use", 0),
            "labels": {},
        }
    )
    out.append(
        {
            "ts": ts,
            "service": service,
            "name": "db_pool_size",
            "value": pool.get("size", 0),
            "labels": {},
        }
    )
    return out


def poll_once(targets: dict[str, str], metrics_file: Path, client: httpx.Client) -> int:
    """Poll all targets once; return how many metric lines were written."""
    ts = now_iso()
    written = 0
    for service, base in targets.items():
        try:
            resp = client.get(f"{base}/internal/stats", timeout=3.0)
            resp.raise_for_status()
            snap = resp.json()
        except Exception:
            continue  # service unreachable this cycle — skip, keep polling
        for metric in stats_to_metrics(service, snap, ts):
            append_jsonl(metrics_file, metric)
            written += 1
    return written


def main() -> None:
    targets = parse_targets(os.environ.get("TARGETS", ""))
    metrics_file = settings.metrics_file()
    with httpx.Client() as client:
        while True:
            poll_once(targets, metrics_file, client)
            HEARTBEAT.write_text(str(time.time()))
            time.sleep(POLL_INTERVAL_S)


if __name__ == "__main__":
    main()
