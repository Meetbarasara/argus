"""Tiny env accessor for demo-world processes (05: demoworld owns its own settings)."""

from __future__ import annotations

import os
from pathlib import Path


def worldstate_path() -> Path:
    return Path(os.environ.get("WORLDSTATE_PATH", "/worldstate"))


def service_name() -> str:
    return os.environ.get("SERVICE_NAME", "unknown")


def logs_dir() -> Path:
    return worldstate_path() / "logs"


def config_path(service: str) -> Path:
    return worldstate_path() / "config" / f"{service}.json"


def shopdb_url() -> str:
    return os.environ.get("SHOPDB_URL", "postgresql://shop:shop@localhost:5434/shop")


def shopredis_url() -> str:
    return os.environ.get("SHOPREDIS_URL", "redis://localhost:6379/0")
