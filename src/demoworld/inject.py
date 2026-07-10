"""inject — CLI fault injector for the 5 demo-world scenarios (01, 03 §2).

Drives faults purely over the actuator's HTTP API, so it runs identically from the host
or from inside a container. Optional benign "decoy" deploys can be added before the fault
to exercise change-correlation (does the change_analyst pick the right deploy?).

    python -m demoworld.inject --scenario S3 [--decoy-deploys 1] [--warmup-seconds 30]
"""

from __future__ import annotations

import argparse
import json
import os
import time
from typing import Any

import httpx

# scenario id -> fault key (01 table)
SCENARIOS = {
    "S1": "redis_down",
    "S2": "payment_latency",
    "S3": "bad_deploy_env",
    "S4": "db_pool_exhaustion",
    "S5": "feature_flag_500",
}


def _deploy(client: httpx.Client, service: str, changes: dict[str, Any], message: str) -> dict:
    resp = client.post(
        "/deploy",
        json={"service": service, "changes": changes, "message": message, "author": "injector"},
    )
    resp.raise_for_status()
    return dict(resp.json())


def _decoys(client: httpx.Client, n: int) -> list[dict]:
    # benign deploys to an unrelated key — should NOT cause any fault
    out = []
    for i in range(n):
        out.append(
            _deploy(
                client,
                "shopapi",
                {"request_timeout_ms": 2500 + i * 100},
                f"routine request-timeout tuning #{i + 1}",
            )
        )
    return out


def _benign_restart(client: httpx.Client) -> dict[str, Any]:
    # a red-herring restart in the audit log (v3 noise) — benign, fixes nothing
    resp = client.post("/restart", json={"service": "paymentsvc"})
    resp.raise_for_status()
    return dict(resp.json())


def apply_fault(
    client: httpx.Client, scenario: str, decoy_deploys: int = 0, benign_restart: bool = False
) -> dict[str, Any]:
    key = SCENARIOS.get(scenario.upper(), scenario)
    decoys = _decoys(client, decoy_deploys) if decoy_deploys else []
    noise = _benign_restart(client) if benign_restart else None

    if key == "redis_down":
        resp = client.post("/admin/stop_container", json={"service": "shopredis"})
        resp.raise_for_status()
        fault = resp.json()
    elif key == "payment_latency":
        resp = client.post("/chaos", json={"service": "paymentsvc", "extra_latency_ms": 3000})
        resp.raise_for_status()
        fault = resp.json()
    elif key == "bad_deploy_env":
        fault = _deploy(
            client,
            "shopapi",
            {"payment_url": "http://paymentsvc:9999"},
            "repoint checkout payments",
        )
    elif key == "db_pool_exhaustion":
        fault = _deploy(client, "shopapi", {"db_pool_size": 2}, "trim db pool to cut connections")
    elif key == "feature_flag_500":
        fault = _deploy(
            client, "shopapi", {"feature_flags.recs_v2": True}, "enable recs_v2 recommender"
        )
    else:
        raise ValueError(f"unknown scenario: {scenario}")

    return {
        "scenario": key,
        "decoys": [d.get("deploy_id") for d in decoys],
        "benign_restart": bool(noise),
        "fault": fault,
    }


def inject(
    scenario: str,
    *,
    decoy_deploys: int = 0,
    warmup_seconds: int = 0,
    benign_restart: bool = False,
    actuator_url: str = "http://localhost:8010",
    token: str = "dev-actuator-token",
) -> dict[str, Any]:
    if warmup_seconds > 0:
        time.sleep(warmup_seconds)
    with httpx.Client(
        base_url=actuator_url, headers={"X-Actuator-Token": token}, timeout=15.0
    ) as client:
        return apply_fault(client, scenario, decoy_deploys, benign_restart)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="demoworld.inject")
    ap.add_argument("--scenario", required=True, help="S1..S5 or a fault key")
    ap.add_argument("--decoy-deploys", type=int, default=0)
    ap.add_argument("--warmup-seconds", type=int, default=0)
    ap.add_argument("--benign-restart", action="store_true", help="v3 noise: a red-herring restart")
    ap.add_argument(
        "--actuator-url", default=os.environ.get("ACTUATOR_URL", "http://localhost:8010")
    )
    ap.add_argument("--token", default=os.environ.get("ACTUATOR_TOKEN", "dev-actuator-token"))
    args = ap.parse_args(argv)
    out = inject(
        args.scenario,
        decoy_deploys=args.decoy_deploys,
        warmup_seconds=args.warmup_seconds,
        benign_restart=args.benign_restart,
        actuator_url=args.actuator_url,
        token=args.token,
    )
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
