"""M09 dashboard reconciliation (tester container, real platform Postgres + API). Runs a
FakeLLM incident in-process (reject → take-over → TAKEN_OVER, so no worldstate/recovery is
needed), then asserts GET /dashboard/summary reconciles with direct SQL on incidents/llm_calls
and that the real emitted spans satisfy the per-kind attr contract."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from sqlalchemy import func, select

from argus.api.app import create_app
from argus.db.models import Incident, LLMCall, Span
from argus.db.session import session_scope
from argus.graph.build import build_graph
from argus.graph.deps import GraphDeps
from argus.llm.fake import FakeLLM
from argus.llm.router import LLMRouter
from argus.policy.risk_gate import load_policy
from argus.repo import incidents as incident_repo
from argus.tools.registry import ToolExecutor

pytestmark = pytest.mark.integration

REQUIRED_ATTRS = {
    "llm": {"role", "provider", "model", "tokens_in", "tokens_out", "cost_usd"},
    "tool": {"agent", "tool", "status"},
    "policy": {"level", "rule_trace"},
    "human": {"decision", "human_review_seconds"},
    "node": set(),
}


def _scripts() -> dict[str, list[Any]]:
    plan = json.dumps(
        {
            "steps": [
                {"id": "step-1", "specialist": "log_analyst", "objective": "logs"},
                {"id": "step-2", "specialist": "metrics_analyst", "objective": "deps"},
                {"id": "step-3", "specialist": "change_analyst", "objective": "changes"},
            ],
            "rationale": "cover it",
        }
    )
    finding = lambda s: json.dumps(  # noqa: E731
        {
            "step_id": "step-x",
            "specialist": s,
            "summary": f"{s} looked",
            "evidence": [{"kind": "log", "ref": "logs/x", "excerpt": "boom"}],
            "confidence": 0.8,
        }
    )
    hypo = json.dumps(
        {
            "root_cause": "redis down",
            "affected_services": ["shopapi"],
            "confidence": 0.8,
            "supporting_evidence": [{"kind": "metric", "ref": "dep_up", "excerpt": "0"}],
            "proposed_action": {
                "tool": "restart_service",
                "params": {"service": "shopredis"},
                "target_service": "shopredis",
                "rationale": "restart",
            },
        }
    )
    reject = json.dumps(
        {
            "verdict": "reject",
            "checks": {
                "evidence_supported": False,
                "action_safe": True,
                "action_proportional": True,
            },
            "feedback": "no",
        }
    )
    return {
        "supervisor": [plan, hypo],
        "log_analyst": [finding("log_analyst")],
        "metrics_analyst": [finding("metrics_analyst")],
        "change_analyst": [finding("change_analyst")],
        "reviewer": [reject],  # length-1 repeats → both reviews reject → take_over
    }


def _alert(service: str) -> dict[str, Any]:
    return {
        "alert_id": "a-" + uuid.uuid4().hex[:6],
        "rule": "dependency_down",
        "service": service,
        "severity": "critical",
        "ts": "2026-07-05T10:00:00.000Z",
        "window_seconds": 60,
        "observed": {"metric": "dep_up", "value": 0, "threshold": 0},
        "labels": {"dep": "redis"},
        "summary": f"{service} dep_up[redis]=0",
    }


def _seed_takenover_incident() -> str:
    alert = _alert(f"shopapi-{uuid.uuid4().hex[:8]}")
    with session_scope() as session:
        incident_id = str(incident_repo.create_incident(session, alert).id)
    deps = GraphDeps(
        router=LLMRouter(mode="fake", fake=FakeLLM(_scripts())),
        executor=ToolExecutor(),
        policy=load_policy(),
        recall=lambda _a: ([], None),
        write_postmortem=lambda *a, **k: None,
    )
    graph = build_graph(deps, MemorySaver())
    cfg = {"configurable": {"thread_id": incident_id}}
    initial = {
        "incident_id": incident_id,
        "alert": alert,
        "service_catalog": {},
        "memory_hits": [],
        "findings": [],
        "spec_llm_calls": [],
        "review_history": [],
        "remediation_attempts": [],
        "budget": {"llm_calls_used": 0, "started_at_iso": datetime.now(UTC).isoformat()},
    }
    graph.invoke(initial, config=cfg)  # runs to the take_over interrupt
    graph.invoke(
        Command(resume={"root_cause": "manual", "action_taken": "by hand"}), config=cfg
    )  # → TAKEN_OVER
    return incident_id


def test_dashboard_reconciles_with_sql() -> None:
    incident_id = _seed_takenover_incident()

    with session_scope() as session:
        assert incident_repo.get_incident(session, incident_id).status == "TAKEN_OVER"

    client = TestClient(create_app())
    body = client.get("/api/dashboard/summary").json()

    # --- self-consistency (race-free) ---
    assert sum(body["incidents_by_status"].values()) == body["total_incidents"]
    resolved = body["incidents_by_status"].get("RESOLVED", 0)
    assert body["resolution_rate"] == round(resolved / body["total_incidents"], 4)
    role_sum = round(sum(r["cost_usd"] for r in body["cost_by_role"]), 6)
    assert abs(role_sum - round(body["total_cost_usd"], 6)) < 1e-6
    assert 0.0 <= body["escalation_rate"] <= 1.0
    assert 0.0 <= body["memory_used_share"] <= 1.0

    # --- reconcile with direct SQL over the same table ---
    with session_scope() as session:
        total = session.execute(select(func.count()).select_from(Incident)).scalar_one()
        takenover = session.execute(
            select(func.count()).select_from(Incident).where(Incident.status == "TAKEN_OVER")
        ).scalar_one()
        llm_cost = session.execute(
            select(func.coalesce(func.sum(LLMCall.cost_usd), 0))
        ).scalar_one()
    assert body["total_incidents"] == total
    assert body["incidents_by_status"].get("TAKEN_OVER", 0) == takenover
    assert abs(body["total_cost_usd"] - float(llm_cost)) < 1e-6
    # our seeded incident is reflected
    assert takenover >= 1 and total >= 1


def test_real_spans_satisfy_attr_contract() -> None:
    incident_id = _seed_takenover_incident()
    with session_scope() as session:
        rows = list(session.scalars(select(Span).where(Span.incident_id == incident_id)).all())
        session.expunge_all()

    kinds = {s.kind for s in rows}
    assert {"llm", "node"} <= kinds  # this flow emits at least node + llm spans
    for span in rows:
        required = REQUIRED_ATTRS.get(span.kind)
        if required:
            missing = required - set(span.attrs or {})
            assert missing == set(), f"{span.name} ({span.kind}) missing attrs {missing}"
