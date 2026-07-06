"""M08 chaos tests (milestone acceptance a–e): the parallel fan-out degrades gracefully and
enforces budgets. FakeLLM + monkeypatched tools, no network.

  (a) a tool erroring twice → a failed-step finding → synthesize plans around it → resolves
  (b) a single specialist's provider giving up → one degraded finding, run still resolves
  (c) > 50% of steps degraded → escalate to take_over (TAKEN_OVER)
  (d) LLM-call budget tripped → take_over (TAKEN_OVER)
  (e) a 3-step independent wave → all three findings present (append reducer, no loss)
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from sqlalchemy import select

from argus.agents import specialists as specialist_agent
from argus.agents.schemas import Finding, PlanStep
from argus.db.models import Span
from argus.db.session import session_scope
from argus.graph.build import build_graph
from argus.graph.deps import GraphDeps
from argus.llm.fake import FakeLLM
from argus.llm.router import LLMRouter
from argus.policy.risk_gate import load_policy
from argus.repo import incidents as incident_repo
from argus.tools import telemetry_tools
from argus.tools.registry import ToolExecutor

pytestmark = pytest.mark.graph


# --- scripts -------------------------------------------------------------------------
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


def _good_finding(specialist: str) -> str:
    return json.dumps(
        {
            "step_id": "step-x",
            "specialist": specialist,
            "summary": f"{specialist} observed the fault",
            "evidence": [{"kind": "metric", "ref": "dep_up", "excerpt": "dep_up[redis]=0"}],
            "confidence": 0.9,
        }
    )


def _hypothesis_restart_redis() -> str:
    return json.dumps(
        {
            "root_cause": "shopredis is down, breaking shopapi's cache dependency",
            "affected_services": ["shopapi", "shopredis"],
            "confidence": 0.9,
            "supporting_evidence": [{"kind": "metric", "ref": "dep_up", "excerpt": "dep_up=0"}],
            "proposed_action": {
                "tool": "restart_service",
                "params": {"service": "shopredis"},
                "target_service": "shopredis",
                "rationale": "restart the cache to restore the dependency",
            },
        }
    )


def _approve() -> str:
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


def _happy_scripts() -> dict[str, list[Any]]:
    return {
        "supervisor": [_plan_three_steps(), _hypothesis_restart_redis()],
        "log_analyst": [_good_finding("log_analyst")],
        "metrics_analyst": [_good_finding("metrics_analyst")],
        "change_analyst": [_good_finding("change_analyst")],
        "reviewer": [_approve()],
    }


# --- harness -------------------------------------------------------------------------
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


def seed_metric(root: Path, service: str, name: str, value: float, dep: str | None = None) -> None:
    line = {
        "ts": datetime.now(UTC).isoformat(),
        "service": service,
        "name": name,
        "value": value,
        "labels": {"dep": dep} if dep else {},
    }
    with (root / "metrics" / "metrics.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(line) + "\n")


def _make_deps(scripts: dict[str, list[Any]], parallel: bool = True) -> GraphDeps:
    return GraphDeps(
        router=LLMRouter(mode="fake", fake=FakeLLM(scripts)),
        executor=ToolExecutor(),
        policy=load_policy(),
        recovery_interval_s=0.0,
        recovery_deadline_s=1.0,
        recovery_sleep=lambda _s: None,
        recall=lambda _a: ([], None),
        write_postmortem=lambda *a, **k: None,
        parallel_specialists=parallel,
    )


def _create_incident(alert: dict[str, Any]) -> str:
    with session_scope() as session:
        incident = incident_repo.create_incident(session, alert)
        session.flush()
        return str(incident.id)


def _cfg(incident_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": incident_id}}


def _initial(incident_id: str, alert: dict[str, Any], **budget: Any) -> dict[str, Any]:
    return {
        "incident_id": incident_id,
        "alert": alert,
        "service_catalog": {},
        "memory_hits": [],
        "findings": [],
        "spec_llm_calls": [],
        "review_history": [],
        "remediation_attempts": [],
        "budget": {"llm_calls_used": 0, "started_at_iso": datetime.now(UTC).isoformat(), **budget},
    }


def _run(deps: GraphDeps, incident_id: str, alert: dict[str, Any], **budget: Any) -> dict[str, Any]:
    graph = build_graph(deps, MemorySaver())
    return graph.invoke(_initial(incident_id, alert, **budget), config=_cfg(incident_id))


def _status(incident_id: str) -> str:
    with session_scope() as session:
        inc = incident_repo.get_incident(session, incident_id)
        return inc.status if inc is not None else "unknown"


def _specialist_spans(incident_id: str) -> list[Span]:
    names = ("node.log_analyst", "node.metrics_analyst", "node.change_analyst")
    with session_scope() as session:
        rows = list(
            session.scalars(
                select(Span).where(Span.incident_id == incident_id, Span.name.in_(names))
            ).all()
        )
        session.expunge_all()
        return rows


# --- (e) parallel wave: all findings present (append reducer, no loss) ----------------
def test_e_parallel_wave_keeps_all_findings(
    worldstate: Path, fake_actuator: list[tuple[str, dict[str, Any]]]
) -> None:
    service = f"shopapi-{uuid.uuid4().hex[:8]}"
    alert = _alert(service)
    seed_metric(worldstate, service, "dep_up", 1, dep="redis")
    incident_id = _create_incident(alert)

    final = _run(_make_deps(_happy_scripts()), incident_id, alert)

    assert _status(incident_id) == "RESOLVED"
    findings = final["findings"]
    assert len(findings) == 3
    # every planned step produced exactly one finding — the concurrent append lost none
    assert {f.step_id for f in findings} == {"step-1", "step-2", "step-3"}
    assert {f.specialist for f in findings} == {
        "log_analyst",
        "metrics_analyst",
        "change_analyst",
    }


# --- (d) budget trip -> take_over -> TAKEN_OVER ---------------------------------------
def test_d_budget_trip_takes_over(worldstate: Path) -> None:
    service = f"shopapi-{uuid.uuid4().hex[:8]}"
    alert = _alert(service)
    incident_id = _create_incident(alert)

    graph = build_graph(_make_deps(_happy_scripts()), MemorySaver())
    paused = graph.invoke(_initial(incident_id, alert, llm_calls_used=40), config=_cfg(incident_id))

    intr = paused.get("__interrupt__")
    assert intr and intr[0].value["kind"] == "takeover"
    assert "budget" in intr[0].value["reason"].lower()
    assert paused.get("findings", []) == []  # short-circuited before any specialist ran

    graph.invoke(
        Command(resume={"root_cause": "over budget", "action_taken": "manual"}),
        config=_cfg(incident_id),
    )
    assert _status(incident_id) == "TAKEN_OVER"


# --- (c) majority of steps degraded -> take_over -> TAKEN_OVER ------------------------
def test_c_majority_degraded_takes_over(worldstate: Path) -> None:
    service = f"shopapi-{uuid.uuid4().hex[:8]}"
    alert = _alert(service)
    incident_id = _create_incident(alert)

    scripts = _happy_scripts()
    # two of three specialists emit unparseable output → their forced Finding fails → conf 0.0
    scripts["log_analyst"] = ["not valid json at all"]
    scripts["metrics_analyst"] = ["also not json"]
    graph = build_graph(_make_deps(scripts), MemorySaver())
    paused = graph.invoke(_initial(incident_id, alert), config=_cfg(incident_id))

    intr = paused.get("__interrupt__")
    assert intr and intr[0].value["kind"] == "takeover"
    assert "degraded" in intr[0].value["reason"].lower()  # the degradation gate fired
    # all three findings were still gathered before escalating; two of them failed
    assert len(paused["findings"]) == 3
    assert sum(1 for f in paused["findings"] if f.confidence == 0.0) == 2

    graph.invoke(
        Command(resume={"root_cause": "manual triage", "action_taken": "by hand"}),
        config=_cfg(incident_id),
    )
    assert _status(incident_id) == "TAKEN_OVER"


# --- (b) a single provider failure degrades one finding but the run still resolves -----
def test_b_single_provider_failure_still_resolves(
    worldstate: Path, fake_actuator: list[tuple[str, dict[str, Any]]]
) -> None:
    service = f"shopapi-{uuid.uuid4().hex[:8]}"
    alert = _alert(service)
    seed_metric(worldstate, service, "dep_up", 1, dep="redis")
    incident_id = _create_incident(alert)

    scripts = _happy_scripts()
    scripts["metrics_analyst"] = ["provider exploded, definitely not json"]  # 1 of 3 degraded
    final = _run(_make_deps(scripts), incident_id, alert)

    assert _status(incident_id) == "RESOLVED"  # a minority failure does not stop the run
    degraded = [f for f in final["findings"] if f.confidence == 0.0]
    assert len(degraded) == 1 and degraded[0].specialist == "metrics_analyst"
    assert len(final["findings"]) == 3


# --- (a) a tool erroring twice -> failed-step finding -> synthesize around it -> resolves
def test_a_tool_error_degrades_step_but_resolves(
    worldstate: Path,
    fake_actuator: list[tuple[str, dict[str, Any]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = f"shopapi-{uuid.uuid4().hex[:8]}"
    alert = _alert(service)
    seed_metric(worldstate, service, "dep_up", 1, dep="redis")
    incident_id = _create_incident(alert)

    attempts = {"n": 0}

    def _boom(_args: Any) -> Any:
        attempts["n"] += 1
        raise RuntimeError("logstore unreachable")

    # patch the registry func before ToolExecutor() captures it in _make_deps
    monkeypatch.setattr(telemetry_tools, "search_logs", _boom)

    tool_call = {"tool_calls": [{"name": "search_logs", "args": {"service": service}}]}
    scripts = _happy_scripts()
    # two tool calls (both raise) then unparseable output → log_analyst degrades to conf 0.0
    scripts["log_analyst"] = [tool_call, tool_call, "not a finding either"]
    final = _run(_make_deps(scripts), incident_id, alert)

    assert _status(incident_id) == "RESOLVED"  # the run survived the tool failures
    assert attempts["n"] >= 2  # the tool was actually attempted (and raised) twice
    log_finding = next(f for f in final["findings"] if f.specialist == "log_analyst")
    assert log_finding.confidence == 0.0  # a failed step is evidence too
    assert len(final["findings"]) == 3  # synthesize planned around the failed step


# --- sequential fallback (PARALLEL_SPECIALISTS=false) preserves the behaviour contract ---
def test_sequential_fallback_resolves(
    worldstate: Path, fake_actuator: list[tuple[str, dict[str, Any]]]
) -> None:
    service = f"shopapi-{uuid.uuid4().hex[:8]}"
    alert = _alert(service)
    seed_metric(worldstate, service, "dep_up", 1, dep="redis")
    incident_id = _create_incident(alert)

    final = _run(_make_deps(_happy_scripts(), parallel=False), incident_id, alert)

    assert _status(incident_id) == "RESOLVED"
    # same contract as the parallel path: three findings, one per specialist
    assert {f.step_id for f in final["findings"]} == {"step-1", "step-2", "step-3"}
    assert {f.specialist for f in final["findings"]} == {
        "log_analyst",
        "metrics_analyst",
        "change_analyst",
    }


# --- parallelism proof: the three specialist spans overlap in wall-clock time ----------
def test_specialist_spans_overlap_under_parallel_fanout(
    worldstate: Path,
    fake_actuator: list[tuple[str, dict[str, Any]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deterministic parallelism proof: give each specialist a fixed delay and assert their
    node spans overlap (max start < min end). Sequential execution could not overlap — this
    is the host-side analogue of the live "specialist spans overlap" gate, without needing a
    live provider (the real build_graph + LangGraph thread pool drive the concurrency)."""

    def _slow_run_step(
        router: Any,
        executor: Any,
        specialist: str,
        alert: dict[str, Any],
        step: PlanStep,
        context: str = "",
        **_: Any,
    ) -> tuple[Finding, int]:
        time.sleep(0.3)
        finding = Finding(
            step_id=step.id, specialist=specialist, summary="ok", evidence=[], confidence=0.9
        )
        return finding, 1

    monkeypatch.setattr(specialist_agent, "run_step", _slow_run_step)

    service = f"shopapi-{uuid.uuid4().hex[:8]}"
    alert = _alert(service)
    seed_metric(worldstate, service, "dep_up", 1, dep="redis")
    incident_id = _create_incident(alert)

    _run(_make_deps(_happy_scripts()), incident_id, alert)

    spans = _specialist_spans(incident_id)
    assert len(spans) == 3
    ends = [s.ended_at for s in spans if s.ended_at is not None]
    assert len(ends) == 3  # all three completed
    latest_start = max(s.started_at for s in spans)
    earliest_end = min(ends)
    # a non-empty intersection across all three windows ⇒ they ran concurrently
    assert latest_start < earliest_end
