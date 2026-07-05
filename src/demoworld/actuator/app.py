"""actuator — token-guarded control API (03 §5).

The only component holding the Docker socket and write access to worldstate. The platform
never gets credentials; it calls these audited capabilities (ADR-03). Every mutating call
is written to deploys/actions.jsonl or deploys/history.jsonl so the change_analyst can see
exactly what happened.
"""

from __future__ import annotations

import json
import os
import shutil
from typing import Any

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel

from demoworld.actuator import docker_ops
from demoworld.actuator.deploys import DeployManager
from demoworld.common import settings
from demoworld.common.jsonlog import append_jsonl, now_iso, read_jsonl
from demoworld.seed.defaults import DEFAULTS, config_default

TAIL_WHITELIST = {
    "alerts/sent.jsonl",
    "logs/shopapi.jsonl",
    "logs/paymentsvc.jsonl",
    "metrics/metrics.jsonl",
    "deploys/history.jsonl",
    "deploys/actions.jsonl",
}
RESET_TRUNCATE = [
    "logs/shopapi.jsonl",
    "logs/paymentsvc.jsonl",
    "metrics/metrics.jsonl",
    "alerts/sent.jsonl",
    "deploys/history.jsonl",
    "deploys/actions.jsonl",
]


class RestartBody(BaseModel):
    service: str


class DeployBody(BaseModel):
    service: str
    changes: dict[str, Any]
    message: str = ""
    author: str = "injector"


class RollbackBody(BaseModel):
    deploy_id: str
    author: str = "human"


class ChaosBody(BaseModel):
    service: str
    extra_latency_ms: int = 0


def create_app() -> FastAPI:
    ws = settings.worldstate_path()
    token = os.environ.get("ACTUATOR_TOKEN", "dev-actuator-token")
    project = os.environ.get("COMPOSE_PROJECT", "argus")
    dm = DeployManager(ws)
    actions_file = ws / "deploys" / "actions.jsonl"

    def auth(x_actuator_token: str = Header(default="")) -> None:
        if x_actuator_token != token:
            raise HTTPException(status_code=401, detail="bad or missing actuator token")

    app = FastAPI(title="actuator")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/restart", dependencies=[Depends(auth)])
    def restart(body: RestartBody) -> dict[str, Any]:
        result = docker_ops.restart_service(body.service, project=project)
        append_jsonl(
            actions_file,
            {"ts": now_iso(), "action": "restart", "service": body.service, "result": result},
        )
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error", "restart failed"))
        return result

    @app.post("/deploy", dependencies=[Depends(auth)])
    def deploy(body: DeployBody) -> dict[str, Any]:
        return dm.deploy(body.service, body.changes, body.message, body.author)

    @app.post("/rollback", dependencies=[Depends(auth)])
    def rollback(body: RollbackBody) -> dict[str, Any]:
        try:
            return dm.rollback(body.deploy_id, body.author)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/deploys", dependencies=[Depends(auth)])
    def deploys(service: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        return dm.list_deploys(service=service, limit=limit)

    @app.get("/actions", dependencies=[Depends(auth)])
    def actions(limit: int = 50) -> list[dict[str, Any]]:
        return list(reversed(read_jsonl(actions_file)))[:limit]

    @app.post("/chaos", dependencies=[Depends(auth)])
    def chaos(body: ChaosBody) -> dict[str, Any]:
        detail: Any
        try:
            with httpx.Client(timeout=3.0) as client:
                resp = client.post(
                    f"http://{body.service}:8000/admin/chaos",
                    json={"extra_latency_ms": body.extra_latency_ms},
                )
                resp.raise_for_status()
            ok, detail = True, resp.json()
        except Exception as exc:
            ok, detail = False, str(exc)
        append_jsonl(
            actions_file,
            {
                "ts": now_iso(),
                "action": "chaos",
                "service": body.service,
                "extra_latency_ms": body.extra_latency_ms,
                "ok": ok,
            },
        )
        if not ok:
            raise HTTPException(status_code=502, detail=detail)
        return {"ok": True, "detail": detail}

    @app.get("/tail", dependencies=[Depends(auth)])
    def tail(file: str = Query(...), last: int = 50) -> dict[str, Any]:
        if file not in TAIL_WHITELIST:
            raise HTTPException(status_code=400, detail="file not in tail whitelist")
        return {"file": file, "lines": read_jsonl(ws / file, limit=last)}

    @app.post("/admin/reset_worldstate", dependencies=[Depends(auth)])
    def reset_worldstate() -> dict[str, Any]:
        for rel in RESET_TRUNCATE:
            (ws / rel).unlink(missing_ok=True)
        shutil.rmtree(ws / "deploys" / "snapshots", ignore_errors=True)
        for svc in DEFAULTS:
            p = ws / "config" / f"{svc}.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(config_default(svc), indent=2) + "\n", encoding="utf-8")
        # best-effort: clear paymentsvc's in-memory chaos so a reset is truly clean
        try:
            with httpx.Client(timeout=2.0) as client:
                client.post("http://paymentsvc:8000/admin/chaos", json={"extra_latency_ms": 0})
        except Exception:
            pass
        return {"ok": True, "reset": True}

    return app
