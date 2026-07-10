"""M11 runner mechanics (07 §2): with stubbed platform I/O + a stub judge, the case loop
injects → awaits → grades → persists an eval_case — deterministically (same grading twice).
No docker, no LLM quota; needs only platform postgres."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import select

from argus.agents.schemas import JudgeVerdict
from argus.db.models import EvalCase, EvalRun
from argus.db.session import session_scope
from argus.evals.run import Platform, run_case

pytestmark = pytest.mark.graph


class _JudgeRouter:
    def structured(self, _role: str, _messages: Any, _schema: Any, **_kw: Any) -> JudgeVerdict:
        return JudgeVerdict(match=True, reason="stub")


def _incident() -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "status": "RESOLVED",
        "root_cause": "shopredis is down, breaking the redis cache dependency for shopapi",
        "service": "shopapi",
        "escalation_level": "NOTIFY",
        "llm_calls": 12,
        "cost_usd": 0.01,
        "mttr_seconds": 50,
        "tokens_in": 100,
        "tokens_out": 50,
        "remediation": {
            "action": {"tool": "restart_service", "target_service": "shopredis"},
            "result": {"ok": True},
        },
        "alert": {
            "rule": "dependency_down",
            "service": "shopapi",
            "observed": {"metric": "dep_up", "threshold": 0},
            "labels": {"dep": "redis"},
        },
    }


def _platform(incident: dict[str, Any]) -> Platform:
    return Platform(
        inject=lambda _k, _p: None,
        reset=lambda: None,
        await_incident=lambda _since, _t: incident["id"],
        fetch_incident=lambda _i: incident,
        await_terminal=lambda _i, _t: incident,
        recovered=lambda _alert: True,
    )


def _new_run() -> str:
    with session_scope() as session:
        run = EvalRun(suite="S1", config={"memory_enabled": False})
        session.add(run)
        session.flush()
        return str(run.id)


def test_run_case_grades_and_persists() -> None:
    inc = _incident()
    run_id = _new_run()
    outcome = run_case("S1-v1", _platform(inc), _JudgeRouter(), run_id)  # type: ignore[arg-type]
    assert outcome == "PASS"

    with session_scope() as session:
        cases = list(session.scalars(select(EvalCase).where(EvalCase.run_id == run_id)).all())
    assert len(cases) == 1
    c = cases[0]
    assert c.scenario_id == "S1-v1" and c.outcome == "PASS" and c.incident_id == inc["id"]
    assert c.rca_correct and c.remediation_correct and c.recovered and c.escalation_correct
    assert c.escalation_expected == "NOTIFY" and c.llm_calls == 12


def test_grading_is_deterministic_across_runs() -> None:
    inc = _incident()
    outcomes = []
    for _ in range(2):
        rid = _new_run()
        outcomes.append(run_case("S1-v1", _platform(inc), _JudgeRouter(), rid))  # type: ignore[arg-type]
    assert outcomes == ["PASS", "PASS"]  # identical mechanics → identical grading


def test_missing_incident_records_a_fail() -> None:
    run_id = _new_run()
    platform = Platform(
        inject=lambda _k, _p: None,
        reset=lambda: None,
        await_incident=lambda _since, _t: None,  # alert never fired
        fetch_incident=lambda _i: {},
        await_terminal=lambda _i, _t: {},
        recovered=lambda _alert: False,
    )
    outcome = run_case("S1-v1", platform, _JudgeRouter(), run_id)  # type: ignore[arg-type]
    assert outcome.startswith("FAIL")
    with session_scope() as session:
        c = session.scalars(select(EvalCase).where(EvalCase.run_id == run_id)).one()
    assert c.outcome == "FAIL" and c.incident_id is None
