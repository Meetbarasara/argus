"""Tool layer against the live world (tester; needs BOTH platform + world profiles up).
Permission enforcement, read tools surfacing a scenario's evidence, and mutating tools
recovering the world — every call logged to tool_calls.

    docker compose --profile platform --profile world up -d
    docker compose run --rm tester pytest -q tests/integration/test_tools_world.py
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator

import httpx
import pytest

from argus.tools.registry import ToolContext, ToolExecutor
from demoworld.inject import apply_fault

pytestmark = pytest.mark.world

ACTUATOR = os.environ.get("ACTUATOR_URL", "http://actuator:8000")
TOKEN = os.environ.get("ACTUATOR_TOKEN", "dev-actuator-token")
executor = ToolExecutor()


@pytest.fixture
def client() -> Iterator[httpx.Client]:
    with httpx.Client(base_url=ACTUATOR, headers={"X-Actuator-Token": TOKEN}, timeout=20.0) as c:
        yield c


def _reset(client: httpx.Client) -> None:
    client.post("/restart", json={"service": "shopredis"})
    time.sleep(3)
    client.post("/admin/reset_worldstate")
    time.sleep(12)  # let metrics/logs settle to baseline


def test_permission_enforcement() -> None:
    # a specialist may not call a mutating tool
    r1 = executor.run(
        "log_analyst",
        "restart_service",
        {"service": "shopredis"},
        context=ToolContext(node="log_analyst"),
    )
    assert r1["ok"] is False and "not allowed" in r1["error"]

    # even the remediate-allowed tool is refused outside the remediate node (defense in depth)
    r2 = executor.run(
        "remediate",
        "restart_service",
        {"service": "shopredis"},
        context=ToolContext(node="planning"),
    )
    assert r2["ok"] is False and "remediate node" in r2["error"]

    # wrong agent for a read tool
    r3 = executor.run(
        "metrics_analyst",
        "search_logs",
        {"service": "shopapi"},
        context=ToolContext(node="metrics_analyst"),
    )
    assert r3["ok"] is False

    # invalid args (missing required 'service')
    r4 = executor.run(
        "metrics_analyst",
        "query_metrics",
        {"metric": "err_rate_60s"},
        context=ToolContext(node="metrics_analyst"),
    )
    assert r4["ok"] is False and "invalid args" in r4["error"]


def test_s3_evidence_across_tools_and_rollback(client: httpx.Client) -> None:
    _reset(client)
    deploy_id = apply_fault(client, "S3")["fault"]["deploy_id"]
    time.sleep(25)  # loadgen produces checkout 502s + metrics move

    log_ctx = ToolContext(node="log_analyst")
    errs = executor.run(
        "log_analyst",
        "search_logs",
        {"service": "shopapi", "level": "ERROR", "contains": "checkout"},
        context=log_ctx,
    )
    assert errs["ok"] and len(errs["result"]) > 0
    summary = executor.run(
        "log_analyst", "log_error_summary", {"service": "shopapi"}, context=log_ctx
    )
    assert summary["ok"] and summary["result"]

    change_ctx = ToolContext(node="change_analyst")
    deploys = executor.run(
        "change_analyst", "list_deploys", {"service": "shopapi"}, context=change_ctx
    )
    assert any(d["deploy_id"] == deploy_id for d in deploys["result"])
    diff = executor.run(
        "change_analyst", "deploy_diff", {"deploy_id": deploy_id}, context=change_ctx
    )
    assert "payment_url" in diff["result"]["changes"]
    actions = executor.run(
        "change_analyst", "recent_actions", {"since_minutes": 120}, context=change_ctx
    )
    assert actions["ok"] is True

    metrics_ctx = ToolContext(node="metrics_analyst")
    err_rate = executor.run(
        "metrics_analyst",
        "query_metrics",
        {"service": "shopapi", "metric": "err_rate_60s"},
        context=metrics_ctx,
    )
    assert err_rate["ok"] and err_rate["result"]["value"] is not None
    health = executor.run("metrics_analyst", "service_health", {}, context=metrics_ctx)
    assert health["ok"] and "shopapi" in health["result"]

    # remediate: rollback the faulty deploy
    rb = executor.run(
        "remediate",
        "rollback_deploy",
        {"deploy_id": deploy_id},
        context=ToolContext(node="remediate"),
    )
    assert rb["ok"] and rb["result"]
    _reset(client)


def test_s1_restart_via_tool(client: httpx.Client) -> None:
    _reset(client)
    apply_fault(client, "S1")
    time.sleep(4)
    r = executor.run(
        "remediate",
        "restart_service",
        {"service": "shopredis"},
        context=ToolContext(node="remediate"),
    )
    assert r["ok"] and r["result"]
    _reset(client)
