"""Mutating tools (04 §5) — the only tools that change the world. They call the actuator
(the single audited choke point, ADR-03); the executor allows them only from the
remediate node."""

from __future__ import annotations

from typing import Any

import httpx

from argus.settings import get_settings
from argus.tools.schemas import RestartServiceArgs, RollbackDeployArgs


def _actuator_post(path: str, body: dict[str, Any]) -> dict[str, Any]:
    s = get_settings()
    with httpx.Client(
        base_url=s.actuator_url, headers={"X-Actuator-Token": s.actuator_token}, timeout=20.0
    ) as client:
        resp = client.post(path, json=body)
        resp.raise_for_status()
        return dict(resp.json())


def restart_service(args: RestartServiceArgs) -> dict[str, Any]:
    return _actuator_post("/restart", {"service": args.service})


def rollback_deploy(args: RollbackDeployArgs) -> dict[str, Any]:
    return _actuator_post("/rollback", {"deploy_id": args.deploy_id, "author": "agent"})
