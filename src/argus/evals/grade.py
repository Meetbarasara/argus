"""Grading (07 §3). Deterministic checks first — remediation from the executed/proposed
action, escalation from the incident row, **recovery re-derived independently from
metrics.jsonl** (the graph never grades its own homework) — then an RCA judge (role=judge,
``JudgeVerdict``, logged to llm_calls for auditability) with a keyword fallback.

All grading functions take plain dicts (an incident as returned by the API + the scenario's
``expected`` block) so they unit-test with synthetic rows and no DB/network."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from argus.agents.schemas import JudgeVerdict
from argus.graph.verify import rule_ok
from argus.llm.router import LLMRouter


@dataclass
class CaseGrade:
    rca_correct: bool
    rca_judge_reason: str
    remediation_correct: bool
    recovered: bool
    escalation_expected: str
    escalation_actual: str | None
    escalation_correct: bool
    outcome: str  # PASS | PARTIAL | FAIL


def _action(incident: dict[str, Any]) -> dict[str, Any]:
    """The action to grade: the executed remediation if any, else the latest proposed action
    from an approvals row (a case that escalated but never executed still 'proposed a fix')."""
    remediation = incident.get("remediation") or {}
    action = remediation.get("action")
    if action:
        return dict(action)
    for approval in reversed(incident.get("approvals") or []):
        proposed = approval.get("proposed_action")
        if proposed:
            return dict(proposed)
    return {}


def grade_remediation(incident: dict[str, Any], expected: dict[str, Any]) -> bool:
    exp = expected.get("remediation") or {}
    action = _action(incident)
    return bool(
        action.get("tool") == exp.get("tool")
        and action.get("target_service") == exp.get("target_service")
    )


def grade_escalation(
    incident: dict[str, Any], expected: dict[str, Any]
) -> tuple[str, str | None, bool]:
    exp = str(expected.get("escalation_level", ""))
    actual = incident.get("escalation_level")
    return exp, actual, actual == exp


def grade_recovery(alert: dict[str, Any]) -> bool:
    """Re-evaluate the breached alert rule against the current metrics.jsonl — independent of
    the graph's verify_recovery. True only if the rule now reads OK (07 §3)."""
    return rule_ok(alert) is True


def judge_messages(label: str, diagnosis: str, service: str) -> list[BaseMessage]:
    system = SystemMessage(
        content=(
            "You grade an incident diagnosis. match=true only if the diagnosis identifies the "
            "same causal mechanism AND the same service — a correct symptom description with the "
            "wrong cause is false; extra correct detail is fine. Return JSON {match, reason}."
        )
    )
    human = HumanMessage(
        content=(
            f"Expected root cause: {label}\n"
            f"System diagnosis: {diagnosis or '(none)'} (affected service: {service})"
        )
    )
    return [system, human]


def judge_rca(
    router: LLMRouter, incident: dict[str, Any], expected: dict[str, Any]
) -> tuple[bool, str]:
    diagnosis = str(incident.get("root_cause") or "")
    label = str(expected.get("root_cause_label", ""))
    try:
        verdict = router.structured(
            "judge",
            judge_messages(label, diagnosis, str(incident.get("service", ""))),
            JudgeVerdict,
        )
        return bool(verdict.match), verdict.reason
    except Exception:  # judge unavailable → keyword heuristic (07 §3)
        text = diagnosis.lower()
        keywords = [str(k).lower() for k in expected.get("root_cause_keywords", [])]
        matched = bool(keywords) and all(k in text for k in keywords)
        return matched, "keyword-fallback"


def outcome(rca: bool, remediation: bool, recovered: bool, escalation: bool) -> str:
    """PASS = all four; PARTIAL = right root cause but something downstream failed; else FAIL."""
    if rca and remediation and recovered and escalation:
        return "PASS"
    return "PARTIAL" if rca else "FAIL"


def grade_case(
    router: LLMRouter,
    incident: dict[str, Any],
    alert: dict[str, Any],
    expected: dict[str, Any],
    recovered: bool | None = None,
) -> CaseGrade:
    rca, reason = judge_rca(router, incident, expected)
    remediation = grade_remediation(incident, expected)
    if recovered is None:  # host runner passes it (metrics read via actuator /tail); else local
        recovered = grade_recovery(alert)
    esc_exp, esc_actual, esc_ok = grade_escalation(incident, expected)
    return CaseGrade(
        rca_correct=rca,
        rca_judge_reason=reason,
        remediation_correct=remediation,
        recovered=recovered,
        escalation_expected=esc_exp,
        escalation_actual=esc_actual,
        escalation_correct=esc_ok,
        outcome=outcome(rca, remediation, recovered, esc_ok),
    )
