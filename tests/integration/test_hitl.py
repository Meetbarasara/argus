"""Human-in-the-loop integration (tester; needs platform postgres + api up). Drives the
compiled graph in-process with a per-test FakeLLM router (deterministic) but a REAL
Postgres checkpointer + the REAL approvals/takeover API + the real task helpers, so the
interrupt -> park -> decide -> resume machinery, atomic flip, modify re-gate, idempotency,
and checkpoint durability are all exercised end to end. (The live celery worker path is
proven separately by the M06 live gate.)

    docker compose --profile platform --profile world up -d
    docker compose run --rm tester pytest tests/integration/test_hitl.py -q
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import Command
from psycopg import Connection
from psycopg.rows import dict_row

from argus.db.session import session_scope
from argus.graph.build import build_graph
from argus.graph.deps import GraphDeps
from argus.llm.fake import FakeLLM
from argus.llm.router import LLMRouter
from argus.policy.risk_gate import load_policy
from argus.repo import incidents as incident_repo
from argus.tools import remediation_tools
from argus.tools.registry import ToolExecutor
from argus.worker import tasks

pytestmark = pytest.mark.integration

API = os.environ.get("PLATFORM_API_URL", "http://api:8080")


# --- fixtures ------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _require_api() -> None:
    try:
        httpx.get(f"{API}/api/health", timeout=5).raise_for_status()
    except Exception:  # pragma: no cover - environment guard
        pytest.skip("platform api not reachable")


@pytest.fixture
def worldstate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from argus.settings import get_settings

    root = tmp_path / "worldstate"
    (root / "metrics").mkdir(parents=True)
    monkeypatch.setenv("WORLDSTATE_PATH", str(root))
    get_settings.cache_clear()
    return root


@pytest.fixture
def fake_actuator(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    calls: list[tuple[str, dict[str, Any]]] = []

    def _post(path: str, body: dict[str, Any]) -> dict[str, Any]:
        calls.append((path, body))
        return {"ok": True, "path": path}

    monkeypatch.setattr(remediation_tools, "_actuator_post", _post)
    return calls


# --- helpers -------------------------------------------------------------------------
def _saver() -> PostgresSaver:
    conn_str = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
    saver = PostgresSaver(Connection.connect(conn_str, autocommit=True, row_factory=dict_row))
    saver.setup()
    return saver


def _deps(scripts: dict[str, list[str]]) -> GraphDeps:
    return GraphDeps(
        router=LLMRouter(mode="fake", fake=FakeLLM(scripts)),
        executor=ToolExecutor(),
        policy=load_policy(),
        recovery_interval_s=0.0,
        recovery_deadline_s=1.0,
        recovery_sleep=lambda _s: None,
        recall=lambda _a: ([], None),
        write_postmortem=lambda *a, **k: None,
    )


def _graph(scripts: dict[str, list[str]]) -> Any:
    return build_graph(_deps(scripts), _saver())


def _cfg(incident_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": incident_id}}


def _initial(incident_id: str, alert: dict[str, Any]) -> dict[str, Any]:
    return {
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


def _plan() -> str:
    return json.dumps(
        {
            "steps": [{"id": "step-1", "specialist": "change_analyst", "objective": "deploys"}],
            "rationale": "check recent deploys",
        }
    )


def _finding() -> str:
    return json.dumps(
        {
            "step_id": "step-1",
            "specialist": "change_analyst",
            "summary": "bad deploy d-0001 changed payment_url",
            "evidence": [{"kind": "deploy", "ref": "d-0001", "excerpt": "payment_url -> :9999"}],
            "confidence": 0.9,
        }
    )


def _hyp(deploy_id: str = "d-0001") -> str:
    return json.dumps(
        {
            "root_cause": f"bad deploy {deploy_id}",
            "affected_services": ["shopapi"],
            "confidence": 0.9,
            "supporting_evidence": [{"kind": "deploy", "ref": deploy_id, "excerpt": "payment_url"}],
            "proposed_action": {
                "tool": "rollback_deploy",
                "params": {"deploy_id": deploy_id},
                "target_service": "shopapi",
                "rationale": "roll back",
            },
        }
    )


def _approve_verdict() -> str:
    return json.dumps(
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


def _scripts() -> dict[str, list[str]]:
    return {
        "supervisor": [_plan(), _hyp(), _plan(), _hyp()],  # plan/hyp twice for a replan cycle
        "change_analyst": [_finding()],
        "reviewer": [_approve_verdict()],
    }


def _alert(service: str) -> dict[str, Any]:
    return {
        "alert_id": "a-" + uuid.uuid4().hex[:6],
        "rule": "high_error_rate",
        "service": service,
        "severity": "critical",
        "ts": "2026-07-05T10:00:00.000Z",
        "observed": {"metric": "err_rate_60s", "value": 0.42, "threshold": 0.2},
        "labels": {},
        "summary": "high error rate",
    }


def _seed_recovered(root: Path, service: str) -> None:
    line = {
        "ts": datetime.now(UTC).isoformat(),
        "service": service,
        "name": "err_rate_60s",
        "value": 0.0,
        "labels": {},
    }
    (root / "metrics" / "metrics.jsonl").write_text(json.dumps(line) + "\n", encoding="utf-8")


def _new_incident(service: str) -> tuple[str, dict[str, Any]]:
    alert = _alert(service)
    with session_scope() as s:
        inc = incident_repo.create_incident(s, alert)
        s.flush()
        return str(inc.id), alert


def _park_if_paused(incident_id: str, result: dict[str, Any]) -> dict[str, Any] | None:
    intr = result.get("__interrupt__")
    if intr:
        tasks._park_for_human(incident_id, dict(intr[0].value))
        return dict(intr[0].value)
    return None


def _pending(incident_id: str) -> dict[str, Any]:
    rows = httpx.get(f"{API}/api/approvals", params={"status": "PENDING"}, timeout=10).json()
    return next(r for r in rows if r["incident_id"] == incident_id)


def _decide(approval_id: str, body: dict[str, Any]) -> httpx.Response:
    return httpx.post(f"{API}/api/approvals/{approval_id}/decision", json=body, timeout=10)


def _status(incident_id: str) -> str:
    return str(httpx.get(f"{API}/api/incidents/{incident_id}", timeout=10).json()["status"])


def _resume(graph: Any, incident_id: str, approval_id: str) -> dict[str, Any]:
    payload = tasks._resume_payload(incident_id, approval_id)
    assert payload is not None
    return graph.invoke(Command(resume=payload), config=_cfg(incident_id))


# --- (i) approve -> resume -> remediate -> RESOLVED ----------------------------------
def test_i_approve_resumes_to_resolved(worldstate: Path, fake_actuator: list) -> None:
    service = f"shopapi-{uuid.uuid4().hex[:8]}"
    incident_id, alert = _new_incident(service)
    _seed_recovered(worldstate, service)
    graph = _graph(_scripts())

    _park_if_paused(
        incident_id, graph.invoke(_initial(incident_id, alert), config=_cfg(incident_id))
    )
    assert _status(incident_id) == "WAITING_APPROVAL"
    approval = _pending(incident_id)
    assert approval["level"] == "APPROVE_ACTION"
    assert approval["proposed_action"]["tool"] == "rollback_deploy"

    assert _decide(approval["id"], {"decision": "approve", "comment": "lgtm"}).status_code == 200
    _resume(graph, incident_id, approval["id"])

    assert _status(incident_id) == "RESOLVED"
    assert ("/rollback", {"deploy_id": "d-0001", "author": "agent"}) in fake_actuator


# --- (ii) reject -> replan (attempt counted, feedback recorded) -> approve -> RESOLVED
def test_ii_reject_replans_then_approves(worldstate: Path, fake_actuator: list) -> None:
    service = f"shopapi-{uuid.uuid4().hex[:8]}"
    incident_id, alert = _new_incident(service)
    _seed_recovered(worldstate, service)
    graph = _graph(_scripts())

    _park_if_paused(
        incident_id, graph.invoke(_initial(incident_id, alert), config=_cfg(incident_id))
    )
    first = _pending(incident_id)
    assert (
        _decide(first["id"], {"decision": "reject", "comment": "wrong deploy"}).status_code == 200
    )
    _park_if_paused(incident_id, _resume(graph, incident_id, first["id"]))

    # replanned and paused again on a fresh approval
    assert _status(incident_id) == "WAITING_APPROVAL"
    second = _pending(incident_id)
    assert second["id"] != first["id"]
    assert _decide(second["id"], {"decision": "approve"}).status_code == 200
    final = _resume(graph, incident_id, second["id"])

    assert _status(incident_id) == "RESOLVED"
    # the rejection counted as a remediation attempt
    assert any(a.get("action") is None for a in final["remediation_attempts"])


# --- (iii) modify -> the modified action is executed verbatim ------------------------
def test_iii_modify_executes_modified_action(worldstate: Path, fake_actuator: list) -> None:
    service = f"shopapi-{uuid.uuid4().hex[:8]}"
    incident_id, alert = _new_incident(service)
    _seed_recovered(worldstate, service)
    graph = _graph(_scripts())

    _park_if_paused(
        incident_id, graph.invoke(_initial(incident_id, alert), config=_cfg(incident_id))
    )
    approval = _pending(incident_id)
    modified = {
        "tool": "rollback_deploy",
        "params": {"deploy_id": "d-0002"},  # human corrected the deploy id
        "target_service": "shopapi",
        "rationale": "actually roll back d-0002",
    }
    resp = _decide(approval["id"], {"decision": "modify", "modified_action": modified})
    assert resp.status_code == 200
    _resume(graph, incident_id, approval["id"])

    assert _status(incident_id) == "RESOLVED"
    assert ("/rollback", {"deploy_id": "d-0002", "author": "agent"}) in fake_actuator


# --- (iv) double decision -> second is 409 -------------------------------------------
def test_iv_double_decision_conflicts(worldstate: Path, fake_actuator: list) -> None:
    service = f"shopapi-{uuid.uuid4().hex[:8]}"
    incident_id, alert = _new_incident(service)
    graph = _graph(_scripts())
    _park_if_paused(
        incident_id, graph.invoke(_initial(incident_id, alert), config=_cfg(incident_id))
    )
    approval = _pending(incident_id)

    assert _decide(approval["id"], {"decision": "approve"}).status_code == 200
    assert _decide(approval["id"], {"decision": "approve"}).status_code == 409


# --- (v) duplicate resume task -> no-op ----------------------------------------------
def test_v_duplicate_resume_is_noop(worldstate: Path, fake_actuator: list) -> None:
    service = f"shopapi-{uuid.uuid4().hex[:8]}"
    incident_id, alert = _new_incident(service)
    _seed_recovered(worldstate, service)
    graph = _graph(_scripts())
    _park_if_paused(
        incident_id, graph.invoke(_initial(incident_id, alert), config=_cfg(incident_id))
    )
    approval = _pending(incident_id)
    _decide(approval["id"], {"decision": "approve"})
    _resume(graph, incident_id, approval["id"])
    assert _status(incident_id) == "RESOLVED"

    # the resume task guard no-ops once the incident is no longer WAITING_APPROVAL
    assert tasks.resume_incident(incident_id, approval["id"]) == "noop:RESOLVED"


# --- (vi) take_over -> takeover_resolution closes as TAKEN_OVER ----------------------
def test_vi_takeover_resolution_closes(worldstate: Path, fake_actuator: list) -> None:
    service = f"shopapi-{uuid.uuid4().hex[:8]}"
    incident_id, alert = _new_incident(service)
    scripts = _scripts()
    scripts["reviewer"] = [
        json.dumps(
            {
                "verdict": "reject",
                "checks": {
                    "evidence_supported": False,
                    "action_safe": False,
                    "action_proportional": False,
                },
                "feedback": "no",
            }
        )
    ]
    graph = _graph(scripts)
    payload = _park_if_paused(
        incident_id, graph.invoke(_initial(incident_id, alert), config=_cfg(incident_id))
    )
    assert payload and payload["kind"] == "takeover"
    assert _status(incident_id) == "WAITING_APPROVAL"

    resp = httpx.post(
        f"{API}/api/incidents/{incident_id}/takeover_resolution",
        json={"root_cause": "manual finding", "action_taken": "fixed by hand"},
        timeout=10,
    )
    assert resp.status_code == 200
    approval = next(
        a
        for a in httpx.get(f"{API}/api/incidents/{incident_id}", timeout=10).json()["approvals"]
        if a["level"] == "TAKE_OVER"
    )
    _resume(graph, incident_id, approval["id"])
    assert _status(incident_id) == "TAKEN_OVER"


# --- (vii) checkpoint durability: a fresh graph object resumes from Postgres ----------
def test_vii_checkpoint_survives_new_graph(worldstate: Path, fake_actuator: list) -> None:
    service = f"shopapi-{uuid.uuid4().hex[:8]}"
    incident_id, alert = _new_incident(service)
    _seed_recovered(worldstate, service)

    scripts = _scripts()
    _park_if_paused(
        incident_id, _graph(scripts).invoke(_initial(incident_id, alert), config=_cfg(incident_id))
    )
    approval = _pending(incident_id)
    _decide(approval["id"], {"decision": "approve"})

    # brand-new graph object + new Postgres connection (as after `restart worker`)
    fresh = _graph(scripts)
    _resume(fresh, incident_id, approval["id"])
    assert _status(incident_id) == "RESOLVED"
