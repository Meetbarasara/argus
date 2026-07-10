"""M11 grading matrix (07 §3): synthetic incidents × expectations → outcome, plus the RCA
keyword fallback and the PASS/PARTIAL/FAIL logic. No DB/network — grading is pure functions."""

from __future__ import annotations

from typing import Any

import pytest

from argus.agents.schemas import JudgeVerdict
from argus.evals.grade import (
    grade_case,
    grade_escalation,
    grade_remediation,
    judge_rca,
    outcome,
)

pytestmark = pytest.mark.unit

EXPECTED = {
    "root_cause_label": "a deploy changed shopapi's payment_url to an unreachable endpoint",
    "root_cause_keywords": ["payment_url", "deploy"],
    "remediation": {"tool": "rollback_deploy", "target_service": "shopapi"},
    "escalation_level": "APPROVE_ACTION",
}


def _incident(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "root_cause": "a bad deploy changed the payment_url on shopapi to a dead endpoint",
        "service": "shopapi",
        "escalation_level": "APPROVE_ACTION",
        "remediation": {
            "action": {"tool": "rollback_deploy", "target_service": "shopapi"},
            "result": {"ok": True},
        },
    }
    base.update(kw)
    return base


class _JudgeStub:
    def __init__(self, match: bool | None = None, boom: bool = False) -> None:
        self.match = match
        self.boom = boom

    def structured(self, _role: str, _messages: Any, _schema: Any, **_kw: Any) -> JudgeVerdict:
        if self.boom:
            raise RuntimeError("judge unavailable")
        return JudgeVerdict(match=bool(self.match), reason="stub")


def test_remediation_exact_match() -> None:
    assert grade_remediation(_incident(), EXPECTED) is True


def test_remediation_wrong_tool_fails() -> None:
    inc = _incident(
        remediation={"action": {"tool": "restart_service", "target_service": "shopapi"}}
    )
    assert grade_remediation(inc, EXPECTED) is False


def test_remediation_graded_from_proposed_when_not_executed() -> None:
    inc = _incident(
        remediation=None,
        approvals=[{"proposed_action": {"tool": "rollback_deploy", "target_service": "shopapi"}}],
    )
    assert grade_remediation(inc, EXPECTED) is True


def test_escalation_match_and_mismatch() -> None:
    assert grade_escalation(_incident(), EXPECTED) == ("APPROVE_ACTION", "APPROVE_ACTION", True)
    exp, actual, ok = grade_escalation(_incident(escalation_level="NOTIFY"), EXPECTED)
    assert exp == "APPROVE_ACTION" and actual == "NOTIFY" and ok is False


def test_rca_keyword_fallback_hit_and_miss() -> None:
    ok, reason = judge_rca(_JudgeStub(boom=True), _incident(), EXPECTED)  # type: ignore[arg-type]
    assert ok is True and reason == "keyword-fallback"
    ok2, reason2 = judge_rca(_JudgeStub(boom=True), _incident(root_cause="redis is down"), EXPECTED)  # type: ignore[arg-type]
    assert ok2 is False and reason2 == "keyword-fallback"


def test_rca_uses_judge_when_available() -> None:
    ok, reason = judge_rca(_JudgeStub(match=True), _incident(), EXPECTED)  # type: ignore[arg-type]
    assert ok is True and reason == "stub"


def test_outcome_matrix() -> None:
    assert outcome(True, True, True, True) == "PASS"
    assert outcome(True, True, False, True) == "PARTIAL"  # right cause, didn't recover
    assert outcome(True, False, True, True) == "PARTIAL"  # right cause, wrong fix
    assert outcome(False, True, True, True) == "FAIL"  # wrong cause is always FAIL


def test_grade_case_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("argus.evals.grade.rule_ok", lambda _alert: True)
    grade = grade_case(_JudgeStub(match=True), _incident(), {"rule": "x"}, EXPECTED)  # type: ignore[arg-type]
    assert grade.outcome == "PASS"
    assert grade.recovered is True and grade.escalation_correct is True


def test_grade_case_partial_when_not_recovered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("argus.evals.grade.rule_ok", lambda _alert: False)
    grade = grade_case(_JudgeStub(match=True), _incident(), {"rule": "x"}, EXPECTED)  # type: ignore[arg-type]
    assert grade.outcome == "PARTIAL" and grade.recovered is False
