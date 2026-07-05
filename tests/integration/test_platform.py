"""Platform integration (tester container): the alert→incident→worker pipe, service-level
dedupe via the partial unique index, and an Alembic upgrade→downgrade→upgrade roundtrip.

    docker compose --profile platform up -d
    docker compose run --rm tester pytest -q -m integration tests/integration/test_platform.py
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Any

import httpx
import psycopg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.integration

API = os.environ.get("PLATFORM_API_URL", "http://api:8080")
DB_URL = os.environ.get("DATABASE_URL", "postgresql+psycopg://argus:argus@postgres:5432/argus")


def _alert(rule: str = "dependency_down", service: str | None = None) -> dict[str, Any]:
    return {
        "alert_id": "a-" + uuid.uuid4().hex[:6],
        "rule": rule,
        "service": service or f"svc-{uuid.uuid4().hex[:8]}",
        "severity": "critical",
        "ts": "2026-07-05T00:00:00Z",
        "observed": {"metric": "dep_up", "value": 0, "threshold": 0},
        "summary": "integration test alert",
    }


def test_health_reports_ready() -> None:
    r = httpx.get(f"{API}/api/health", timeout=10)
    assert r.status_code == 200
    body = r.json()
    assert body["db"] is True
    assert body["redis"] is True
    assert body["worldstate_mounted"] is True
    assert body["config"]["supervisor_model"]  # echo present


def test_webhook_creates_incident_and_worker_reaches_failed_v0() -> None:
    r = httpx.post(f"{API}/api/alerts/webhook", json=_alert(), timeout=10)
    assert r.status_code == 201
    incident_id = r.json()["incident_id"]

    status = None
    deadline = time.time() + 25
    while time.time() < deadline:
        detail = httpx.get(f"{API}/api/incidents/{incident_id}", timeout=10).json()
        status = detail["status"]
        if status == "FAILED":
            assert "graph not implemented" in (detail["status_reason"] or "")
            break
        time.sleep(1)
    assert status == "FAILED"


def test_dedupe_partial_unique_index() -> None:
    from argus.db.session import get_sessionmaker
    from argus.repo import incidents as repo

    service = f"dedupe-{uuid.uuid4().hex[:8]}"
    session = get_sessionmaker()()
    try:
        first = repo.create_incident(session, _alert(service=service))
        found = repo.find_open_for_service(session, service)
        assert found is not None and found.id == first.id
        # a second non-terminal incident for the same service must violate the index
        with pytest.raises(IntegrityError):
            repo.create_incident(session, _alert(rule="high_error_rate", service=service))
        session.rollback()
    finally:
        session.close()


def test_migration_upgrade_downgrade_upgrade_roundtrip() -> None:
    url = make_url(DB_URL)
    tmp_db = f"argus_migtest_{uuid.uuid4().hex[:8]}"
    admin = psycopg.connect(
        host=url.host, port=url.port, user=url.username, password=url.password, dbname="postgres"
    )
    admin.autocommit = True
    try:
        admin.execute(f'CREATE DATABASE "{tmp_db}"')
        tmp_url = url.set(database=tmp_db).render_as_string(hide_password=False)
        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", tmp_url)
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "base")
        command.upgrade(cfg, "head")  # idempotent recreate
    finally:
        admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s", (tmp_db,)
        )
        admin.execute(f'DROP DATABASE IF EXISTS "{tmp_db}"')
        admin.close()
