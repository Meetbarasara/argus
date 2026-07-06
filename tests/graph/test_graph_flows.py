"""Scripted, deterministic full-graph runs on a FakeLLM (05, M05 acceptance a-e). These
exercise the wiring — statuses, spans, approvals, routing loops, budget guard — without a
single network call. Specialists produce no tool calls under the FakeLLM (the fake emits
no tool_calls); the tool span comes from the remediate node against the mocked actuator.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy import select

from argus.db.models import Approval, Span
from argus.db.session import session_scope
from argus.graph.build import build_graph
from argus.graph.deps import GraphDeps
from argus.llm.fake import FakeLLM
from argus.llm.router import LLMRouter
from argus.policy.risk_gate import evaluate_risk, load_policy
from argus.repo import incidents as incident_repo
from argus.tools.registry import ToolExecutor

pytestmark = pytest.mark.graph


def seed_metric(root: Path, service: str, name: str, value: float, dep: str | None = None) -> None:
    """Append a recent metric sample so verify_recovery's 5-minute window reads it."""
    line = {
        "ts": datetime.now(UTC).isoformat(),
        "service": service,
        "name": name,
        "value": value,
        "labels": {"dep": dep} if dep else {},
    }
    with (root / "metrics" / "metrics.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(line) + "\n")


# --- script builders -----------------------------------------------------------------
def _plan_three_steps() -> str:
    return json.dumps(
        {
            "steps": [
                {"id": "step-1", "specialist": "log_analyst", "objective": "find errors"},
                {"id": "step-2", "specialist": "metrics_analyst", "objective": "check deps"},
                {"id": "step-3", "specialist": "change_analyst", "objective": "recent changes"},
            ],
            "rationale": "cover logs, metrics, and changes",
        }
    )


def _finding(specialist: str, kind: str, ref: str) -> str:
    return json.dumps(
        {
            "step_id": "step-x",
            "specialist": specialist,
            "summary": f"{specialist} observed the fault",
            "evidence": [{"kind": kind, "ref": ref, "excerpt": "redis connection refused"}],
            "confidence": 0.9,
        }
    )


def _hypothesis_restart_redis() -> str:
    return json.dumps(
        {
            "root_cause": "shopredis is down, breaking shopapi's cache dependency",
            "affected_services": ["shopapi", "shopredis"],
            "confidence": 0.9,
            "supporting_evidence": [
                {"kind": "metric", "ref": "dep_up", "excerpt": "dep_up[redis]=0"}
            ],
            "proposed_action": {
                "tool": "restart_service",
                "params": {"service": "shopredis"},
                "target_service": "shopredis",
                "rationale": "restart the cache to restore the dependency",
            },
        }
    )


def _verdict(verdict: str) -> str:
    return json.dumps(
        {
            "verdict": verdict,
            "checks": {
                "evidence_supported": verdict == "approve",
                "action_safe": True,
                "action_proportional": True,
            },
            "feedback": "" if verdict == "approve" else f"please {verdict} the hypothesis",
        }
    )


def _happy_path_scripts() -> dict[str, list[str]]:
    return {
        "supervisor": [_plan_three_steps(), _hypothesis_restart_redis()],
        "log_analyst": [_finding("log_analyst", "log", "logs/shopapi.jsonl")],
        "metrics_analyst": [_finding("metrics_analyst", "metric", "dep_up")],
        "change_analyst": [_finding("change_analyst", "deploy", "d-0001")],
        "reviewer": [_verdict("approve")],
    }


def _make_deps(scripts: dict[str, list[str]]) -> GraphDeps:
    return GraphDeps(
        router=LLMRouter(mode="fake", fake=FakeLLM(scripts)),
        executor=ToolExecutor(),
        policy=load_policy(),
        recovery_interval_s=0.0,
        recovery_deadline_s=1.0,
        recovery_sleep=lambda _s: None,
    )


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
        "summary": f"{service} dep_up[redis]=0 breached == 0",
    }


def _create_incident(alert: dict[str, Any]) -> str:
    with session_scope() as session:
        incident = incident_repo.create_incident(session, alert)
        session.flush()
        return str(incident.id)


def _run(deps: GraphDeps, incident_id: str, alert: dict[str, Any], **budget: Any) -> dict[str, Any]:
    graph = build_graph(deps, MemorySaver())
    initial = {
        "incident_id": incident_id,
        "alert": alert,
        "service_catalog": {},
        "memory_hits": [],
        "findings": [],
        "review_history": [],
        "remediation_attempts": [],
        "budget": {"llm_calls_used": 0, "started_at_iso": datetime.now(UTC).isoformat(), **budget},
    }
    return graph.invoke(initial, config={"configurable": {"thread_id": incident_id}})


def _incident(incident_id: str) -> Any:
    with session_scope() as session:
        inc = incident_repo.get_incident(session, incident_id)
        session.expunge_all()
        return inc


def _spans(incident_id: str) -> list[Span]:
    with session_scope() as session:
        rows = list(session.scalars(select(Span).where(Span.incident_id == incident_id)).all())
        session.expunge_all()
        return rows


def _approvals(incident_id: str) -> list[Approval]:
    with session_scope() as session:
        rows = list(
            session.scalars(select(Approval).where(Approval.incident_id == incident_id)).all()
        )
        session.expunge_all()
        return rows


# --- (a) S1 happy path: autonomous resolution ----------------------------------------
def test_a_happy_path_resolves_autonomously(
    worldstate: Path, fake_actuator: list[tuple[str, dict[str, Any]]]
) -> None:
    service = f"shopapi-{uuid.uuid4().hex[:8]}"
    alert = _alert(service)
    seed_metric(worldstate, service, "dep_up", 1, dep="redis")  # recovered
    incident_id = _create_incident(alert)

    final = _run(_make_deps(_happy_path_scripts()), incident_id, alert)

    inc = _incident(incident_id)
    assert inc.status == "RESOLVED"
    assert inc.escalation_level == "NOTIFY"
    assert inc.memory_used is False
    assert inc.resolved_at is not None and inc.mttr_seconds is not None
    assert inc.llm_calls > 0
    # remediation executed against the (mocked) actuator
    assert inc.remediation["action"]["tool"] == "restart_service"
    assert inc.remediation["result"]["ok"] is True
    assert ("/restart", {"service": "shopredis"}) in fake_actuator
    # three specialists ran -> three findings
    assert len(final["findings"]) == 3

    # NOTIFY inserts an informational AUTO approvals row
    approvals = _approvals(incident_id)
    assert any(a.level == "NOTIFY" and a.status == "AUTO" for a in approvals)

    # span tree is complete: node + llm + tool + policy kinds, all under one trace
    spans = _spans(incident_id)
    kinds = {s.kind for s in spans}
    assert {"node", "llm", "tool", "policy"} <= kinds
    assert len(spans) > 15
    assert len({s.trace_id for s in spans}) == 1


# --- (b) reviewer revise loop then approve --------------------------------------------
def test_b_revise_then_approve(
    worldstate: Path, fake_actuator: list[tuple[str, dict[str, Any]]]
) -> None:
    service = f"shopapi-{uuid.uuid4().hex[:8]}"
    alert = _alert(service)
    seed_metric(worldstate, service, "dep_up", 1, dep="redis")
    incident_id = _create_incident(alert)

    scripts = _happy_path_scripts()
    scripts["reviewer"] = [_verdict("revise"), _verdict("approve")]
    final = _run(_make_deps(scripts), incident_id, alert)

    inc = _incident(incident_id)
    assert inc.status == "RESOLVED"
    assert inc.escalation_level == "NOTIFY"
    # exactly two reviews: one revise, then approve
    verdicts = [v.verdict for v in final["review_history"]]
    assert verdicts == ["revise", "approve"]


# --- (c) reviewer rejects twice -> TAKEN_OVER -----------------------------------------
def test_c_reject_twice_takes_over(worldstate: Path) -> None:
    service = f"shopapi-{uuid.uuid4().hex[:8]}"
    alert = _alert(service)
    incident_id = _create_incident(alert)

    scripts = _happy_path_scripts()
    scripts["reviewer"] = [_verdict("reject")]  # length-1 repeats -> both reviews reject
    final = _run(_make_deps(scripts), incident_id, alert)

    inc = _incident(incident_id)
    assert inc.status == "TAKEN_OVER"
    assert inc.status_reason and "reviewer" in inc.status_reason
    assert [v.verdict for v in final["review_history"]] == ["reject", "reject"]
    # a PENDING TAKE_OVER approvals row is opened for the human
    approvals = _approvals(incident_id)
    assert any(a.level == "TAKE_OVER" and a.status == "PENDING" for a in approvals)
    assert inc.remediation is None


# --- (d) budget breach -> TAKEN_OVER --------------------------------------------------
def test_d_budget_breach_takes_over(worldstate: Path) -> None:
    service = f"shopapi-{uuid.uuid4().hex[:8]}"
    alert = _alert(service)
    incident_id = _create_incident(alert)

    # start already at the LLM-call limit: the first LLM node (plan) guard trips
    final = _run(_make_deps(_happy_path_scripts()), incident_id, alert, llm_calls_used=40)

    inc = _incident(incident_id)
    assert inc.status == "TAKEN_OVER"
    assert inc.status_reason and "budget" in inc.status_reason.lower()
    # guard short-circuited before any specialist ran
    assert final.get("findings", []) == []


# --- (e) risk-gate levels for all five scenarios (pure, grouped with the graph suite) --
@pytest.mark.parametrize(
    ("tool", "target", "expected"),
    [
        ("restart_service", "shopredis", "NOTIFY"),  # S1
        ("restart_service", "paymentsvc", "APPROVE_ACTION"),  # S2
        ("rollback_deploy", "shopapi", "APPROVE_ACTION"),  # S3
        ("rollback_deploy", "shopapi", "APPROVE_ACTION"),  # S4
        ("rollback_deploy", "shopapi", "APPROVE_ACTION"),  # S5
    ],
)
def test_e_scenario_risk_levels(tool: str, target: str, expected: str) -> None:
    decision = evaluate_risk(tool=tool, target_service=target, confidence=0.9, policy=load_policy())
    assert decision.level == expected
