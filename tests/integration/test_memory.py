"""Memory integration (tester; needs platform postgres + the baked embedder). Real
pgvector round trip, delete, consolidation, and the repeat test — run #1 seeds a memory
via the real writer, run #2 recalls it (memory_used=true and the plan prompt carries the
memory block). Deterministic: FakeLLM router, real recall/writer/embedder/pgvector."""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg import Connection
from psycopg.rows import dict_row
from sqlalchemy import select, text

from argus.db.models import LLMCall
from argus.db.session import session_scope
from argus.graph.build import build_graph
from argus.graph.deps import GraphDeps
from argus.llm.fake import FakeLLM
from argus.llm.router import LLMRouter
from argus.memory.embedder import embed
from argus.memory.fingerprint import fingerprint, memory_embed_text
from argus.memory.pgvector_store import PgVectorStore
from argus.policy.risk_gate import load_policy
from argus.repo import incidents as incident_repo
from argus.tools import remediation_tools
from argus.tools.registry import ToolExecutor

pytestmark = pytest.mark.integration

store = PgVectorStore()


@pytest.fixture(autouse=True)
def _clean_memories() -> None:
    with session_scope() as session:
        session.execute(text("DELETE FROM memories"))


@pytest.fixture
def worldstate(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    from argus.settings import get_settings

    root = tmp_path / "worldstate"
    (root / "metrics").mkdir(parents=True)
    (root / "logs").mkdir()
    monkeypatch.setenv("WORLDSTATE_PATH", str(root))
    get_settings.cache_clear()
    return root


@pytest.fixture
def fake_actuator(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(remediation_tools, "_actuator_post", lambda p, b: {"ok": True})


def _add(title: str, content: str, source: str | None = None) -> str:
    fp = fingerprint(alert_rule="dependency_down", services=["shopapi", "shopredis"], templates=[])
    return store.add(
        kind="incident_pattern",
        title=title,
        content=content,
        fingerprint=fp,
        embedding=embed(memory_embed_text(title, content, [])),
        source_incident_id=source,
    )


def _alert(service: str) -> dict[str, Any]:
    return {
        "alert_id": "a-" + uuid.uuid4().hex[:6],
        "rule": "dependency_down",
        "service": service,
        "severity": "critical",
        "ts": "2026-07-05T10:00:00.000Z",
        "observed": {"metric": "dep_up", "value": 0, "threshold": 0},
        "labels": {"dep": "redis"},
        "summary": f"{service} dep_up[redis]=0 breached == 0",
    }


# --- write -> recall round trip ------------------------------------------------------
def test_write_recall_roundtrip() -> None:
    from argus.memory.recall import recall

    _add("shopredis outage", "shopredis went down; restarting the cache restored service")
    hits, _ = recall(_alert("shopapi"))
    assert hits and hits[0]["title"] == "shopredis outage"
    assert 0.0 <= hits[0]["similarity"] <= 1.0


# --- delete stops recall -------------------------------------------------------------
def test_delete_removes_from_recall() -> None:
    from argus.memory.recall import recall

    memory_id = _add("cache outage", "restart the cache to recover")
    assert recall(_alert("shopapi"))[0]  # present
    assert store.delete(memory_id) is True
    assert recall(_alert("shopapi"))[0] == []  # gone


# --- consolidation merges a near-duplicate pair --------------------------------------
def test_consolidate_merges_near_duplicates() -> None:
    from argus.memory.consolidate import consolidate

    _add("redis down", "shopredis crashed and a restart fixed it")
    _add("redis down", "shopredis crashed and a restart fixed it")  # near-identical
    result = consolidate(store=store)
    assert result["merged"] >= 1
    assert len(store.all()) == 1  # originals superseded, one merged memory remains


# --- the repeat test: run #1 seeds, run #2 recalls -----------------------------------
def _saver() -> PostgresSaver:
    conn_str = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
    saver = PostgresSaver(Connection.connect(conn_str, autocommit=True, row_factory=dict_row))
    saver.setup()
    return saver


def _scripts() -> dict[str, list[str]]:
    plan = json.dumps(
        {
            "steps": [{"id": "step-1", "specialist": "metrics_analyst", "objective": "deps"}],
            "rationale": "check dependency health",
        }
    )
    finding = json.dumps(
        {
            "step_id": "step-1",
            "specialist": "metrics_analyst",
            "summary": "redis dependency down",
            "evidence": [{"kind": "metric", "ref": "dep_up", "excerpt": "dep_up[redis]=0"}],
            "confidence": 0.9,
        }
    )
    hyp = json.dumps(
        {
            "root_cause": "shopredis is down",
            "affected_services": ["shopapi", "shopredis"],
            "confidence": 0.9,
            "supporting_evidence": [{"kind": "metric", "ref": "dep_up", "excerpt": "0"}],
            "proposed_action": {
                "tool": "restart_service",
                "params": {"service": "shopredis"},
                "target_service": "shopredis",
                "rationale": "restart the cache",
            },
        }
    )
    approve = json.dumps(
        {
            "verdict": "approve",
            "checks": {
                "evidence_supported": True,
                "action_safe": True,
                "action_proportional": True,
            },
            "feedback": "",
        }
    )
    postmortem = json.dumps(
        {
            "title": "shopredis dependency outage",
            "content": "shopredis was down; a restart restored the cache dependency",
            "kind": "incident_pattern",
        }
    )
    return {
        "supervisor": [plan, hyp],
        "metrics_analyst": [finding],
        "reviewer": [approve],
        "memory_writer": [postmortem],
    }


def _run(incident_id: str, alert: dict[str, Any]) -> None:
    deps = GraphDeps(  # default recall + write_postmortem = the REAL memory functions
        router=LLMRouter(mode="fake", fake=FakeLLM(_scripts())),
        executor=ToolExecutor(),
        policy=load_policy(),
        recovery_interval_s=0.0,
        recovery_deadline_s=1.0,
        recovery_sleep=lambda _s: None,
    )
    graph = build_graph(deps, _saver())
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
    graph.invoke(initial, config={"configurable": {"thread_id": incident_id}})


def _create(alert: dict[str, Any]) -> str:
    with session_scope() as session:
        incident = incident_repo.create_incident(session, alert)
        session.flush()
        return str(incident.id)


def _plan_prompt(incident_id: str) -> str:
    with session_scope() as session:
        call = session.scalars(
            select(LLMCall)
            .where(LLMCall.incident_id == incident_id, LLMCall.role == "supervisor")
            .order_by(LLMCall.created_at)
        ).first()
        return json.dumps(call.messages) if call else ""


def test_repeat_run_recalls_seeded_memory(worldstate: Any, fake_actuator: None) -> None:
    def _metric(root: Any, service: str) -> None:
        line = {
            "ts": datetime.now(UTC).isoformat(),
            "service": service,
            "name": "dep_up",
            "value": 1,
            "labels": {"dep": "redis"},
        }
        (root / "metrics" / "metrics.jsonl").write_text(json.dumps(line) + "\n", encoding="utf-8")

    _metric(worldstate, "shopapi")

    # run #1 — seeds a memory via the real postmortem writer
    run1 = _create(_alert("shopapi"))
    _run(run1, _alert("shopapi"))
    with session_scope() as s:
        assert incident_repo.get_incident(s, run1).status == "RESOLVED"
    assert len(store.all()) == 1  # one memory written

    # run #2 — the same fault; recall should surface run #1's lesson
    run2 = _create(_alert("shopapi"))
    _run(run2, _alert("shopapi"))
    with session_scope() as s:
        inc2 = incident_repo.get_incident(s, run2)
        assert inc2.memory_used is True

    # the plan prompt for run #2 carries the recalled memory block
    assert "shopredis dependency outage" in _plan_prompt(run2)
