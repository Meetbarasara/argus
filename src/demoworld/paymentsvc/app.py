"""paymentsvc — processes payments with a configurable base latency.

Fault surface: `POST /admin/chaos` injects extra in-memory latency (scenario S2). The
chaos value lives only in process memory — it is never written to config/deploys — so a
service restart clears it and S2 leaves no deploy-history trace (03 §2, 01 S2).
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from demoworld.common import settings
from demoworld.common.hotconfig import HotConfig
from demoworld.common.jsonlog import JsonLogger
from demoworld.common.stats import RollingStats
from demoworld.seed.defaults import ensure_config

SERVICE = "paymentsvc"


class ChaosBody(BaseModel):
    extra_latency_ms: int = 0


def create_app(*, start_polling: bool = True) -> FastAPI:
    cfg_path = settings.config_path(SERVICE)
    ensure_config(SERVICE, cfg_path)
    config = HotConfig(cfg_path)
    if start_polling:
        config.start(5.0)
    stats = RollingStats()
    log = JsonLogger(settings.logs_dir(), SERVICE)
    state: dict[str, Any] = {"chaos_extra_latency_ms": 0}

    app = FastAPI(title=SERVICE)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/pay")
    async def pay() -> dict[str, Any]:
        # The amount is irrelevant to the demo; /pay only simulates processing latency,
        # so it accepts any POST (with or without a body) to stay robust for callers.
        latency = float(config.get("base_latency_ms", 40)) + float(state["chaos_extra_latency_ms"])
        await asyncio.sleep(latency / 1000.0)
        stats.record(latency_ms=latency, is_error=False)
        return {"status": "ok", "latency_ms": latency}

    @app.get("/internal/stats")
    async def internal_stats() -> dict[str, Any]:
        snap = stats.snapshot()
        snap.update(
            {
                "service": SERVICE,
                "deps": {},
                "db_pool": {"in_use": 0, "size": 0},
                "config_version": config.version,
            }
        )
        return snap

    @app.post("/admin/chaos")
    async def chaos(body: ChaosBody) -> dict[str, Any]:
        state["chaos_extra_latency_ms"] = body.extra_latency_ms
        log.write("WARN", "chaos latency updated", extra_latency_ms=body.extra_latency_ms)
        return {"ok": True, "chaos_extra_latency_ms": body.extra_latency_ms}

    return app
