"""Health + config echo (03 §4). The config block lets the eval runner confirm the
platform is running with the settings it asked for."""

from __future__ import annotations

from pathlib import Path

import redis
import yaml
from fastapi import APIRouter
from sqlalchemy import text

from argus.api.schemas import HealthConfig, HealthResponse
from argus.db.session import get_engine
from argus.settings import get_settings

router = APIRouter()


def _supervisor_model() -> str:
    # M03 replaces this with the real LLM config (incl. env overrides); for now echo the default.
    try:
        data = yaml.safe_load(Path("config/models.yaml").read_text(encoding="utf-8"))
        return str(data["roles"]["supervisor"]["model"])
    except Exception:
        return "unknown"


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    s = get_settings()

    db_ok = False
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass

    redis_ok = False
    try:
        redis.Redis.from_url(s.redis_url, socket_connect_timeout=1).ping()
        redis_ok = True
    except Exception:
        pass

    ws_ok = Path(s.worldstate_path).exists()

    return HealthResponse(
        status="ok" if (db_ok and redis_ok) else "degraded",
        db=db_ok,
        redis=redis_ok,
        worldstate_mounted=ws_ok,
        config=HealthConfig(
            llm_mode=s.llm_mode,
            auto_approve=s.auto_approve,
            memory_enabled=s.memory_enabled,
            supervisor_model=_supervisor_model(),
        ),
    )
