"""Fixtures for the graph tier (host + platform postgres only, 05). Everything the graph
touches is either the real test database (incidents/spans/approvals/llm_calls/tool_calls)
or a fixture: a FakeLLM-backed router (deterministic, no network), a tmp worldstate, and a
mocked actuator so remediation never hits Docker."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from argus.db.session import get_engine
from argus.settings import get_settings
from argus.tools import remediation_tools


@pytest.fixture(scope="session", autouse=True)
def _require_platform_db() -> None:
    """Skip the whole tier cleanly if the platform postgres isn't reachable."""
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:  # pragma: no cover - environment guard
        pytest.skip("platform postgres not reachable (bring up the platform profile)")


@pytest.fixture
def worldstate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A tmp worldstate volume; WORLDSTATE_PATH points here so verify_recovery reads it."""
    root = tmp_path / "worldstate"
    for sub in ("logs", "metrics", "deploys", "deploys/snapshots", "alerts"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("WORLDSTATE_PATH", str(root))
    get_settings.cache_clear()
    return root


@pytest.fixture
def fake_actuator(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    """Record + stub actuator POSTs so remediate() never touches Docker."""
    calls: list[tuple[str, dict[str, Any]]] = []

    def _fake_post(path: str, body: dict[str, Any]) -> dict[str, Any]:
        calls.append((path, body))
        if path == "/restart":
            return {"ok": True, "restarted": [f"argus-{body.get('service')}-1"]}
        if path == "/rollback":
            return {"ok": True, "deploy_id": "d-9999", "restored": body.get("deploy_id")}
        return {"ok": True}

    monkeypatch.setattr(remediation_tools, "_actuator_post", _fake_post)
    return calls
