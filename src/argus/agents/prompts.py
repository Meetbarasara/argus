"""All prompt text lives here (04 §4) — one file so it can be shown/reviewed at a glance.
Prompts never contain secrets; evidence excerpts are already capped by the schemas.

The router prepends its own "respond with JSON matching this schema" system message for
structured calls, so these builders focus on the role framing and the concrete task.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from argus.agents.schemas import Finding, Hypothesis, InvestigationPlan

FAST_PATH_SIMILARITY = 0.92

SPECIALIST_BLURBS = (
    "log_analyst (searches service logs), metrics_analyst (queries metrics and health), "
    "change_analyst (reviews deploys, config diffs, operator actions)"
)


def _alert_summary(alert: dict[str, Any]) -> str:
    observed = alert.get("observed", {})
    return (
        f"[{alert.get('severity', '?')}] rule={alert.get('rule')} "
        f"service={alert.get('service')} at {alert.get('ts')}: "
        f"{alert.get('summary') or observed}"
    )


def _memory_block(memory_hits: list[dict[str, Any]]) -> str:
    if not memory_hits:
        return "No similar past incidents."
    lines = ["Similar past incidents:"]
    for hit in memory_hits:
        lines.append(f"- ({hit.get('similarity', 0):.2f}) {hit.get('title')}: {hit.get('content')}")
    return "\n".join(lines)


# --- supervisor: plan ----------------------------------------------------------------
def plan_messages(
    alert: dict[str, Any],
    service_catalog: dict[str, Any],
    memory_hits: list[dict[str, Any]],
    fast_path_hint: dict[str, Any] | None = None,
) -> list[BaseMessage]:
    fast_path = ""
    if fast_path_hint and fast_path_hint.get("similarity", 0) > FAST_PATH_SIMILARITY:
        fast_path = (
            f"\nA nearly identical resolved incident exists: {fast_path_hint.get('title')}; "
            f"fix was {fast_path_hint.get('previous_remediation')}. Plan a minimal 1-2 step "
            "verification that this is the same cause - do not skip verification."
        )
    system = SystemMessage(
        content=(
            "You are the supervisor of an incident-response team. An alert fired:\n"
            f"{_alert_summary(alert)}\n"
            f"Services: {json.dumps(service_catalog)}\n"
            f"Specialists: {SPECIALIST_BLURBS}.\n"
            f"{_memory_block(memory_hits)}"
        )
    )
    human = HumanMessage(
        content=(
            "Create the smallest investigation plan (1-5 steps) that can identify the root "
            "cause. Each step: one specialist, one concrete objective. Use depends_on only "
            "when a step truly needs another's output. Return JSON matching InvestigationPlan."
            f"{fast_path}"
        )
    )
    return [system, human]


# --- supervisor: synthesize ----------------------------------------------------------
def _finding_block(findings: list[Finding]) -> str:
    if not findings:
        return "No findings were produced."
    out: list[str] = []
    for f in findings:
        ev = "; ".join(f"{e.kind}:{e.ref} — {e.excerpt}" for e in f.evidence)
        out.append(
            f"[{f.specialist}/{f.step_id}] (confidence {f.confidence:.2f}) {f.summary}\n"
            f"    evidence: {ev or 'none'}"
        )
    return "\n".join(out)


def synthesize_messages(
    alert: dict[str, Any],
    findings: list[Finding],
    memory_hits: list[dict[str, Any]],
    review_feedback: str | None = None,
) -> list[BaseMessage]:
    feedback = ""
    if review_feedback:
        feedback = (
            "\nThe reviewer asked you to revise the previous hypothesis with this "
            f"feedback:\n{review_feedback}\nAddress it directly."
        )
    system = SystemMessage(
        content=(
            "You are the supervisor synthesizing a root-cause hypothesis from your "
            "specialists' findings. Choose exactly one remediation from the catalog: "
            "restart_service (params: {service}) or rollback_deploy (params: {deploy_id}). "
            "The action must target the right service and be the smallest fix that plausibly "
            "resolves the cause. Set confidence honestly (low if evidence is thin)."
        )
    )
    human = HumanMessage(
        content=(
            f"Alert: {_alert_summary(alert)}\n"
            f"{_memory_block(memory_hits)}\n\n"
            f"Findings:\n{_finding_block(findings)}\n"
            f"{feedback}\n\n"
            "Return JSON matching Hypothesis."
        )
    )
    return [system, human]


# --- specialists: tool loop ----------------------------------------------------------
def specialist_messages(
    specialist: str,
    alert: dict[str, Any],
    objective: str,
    dependency_context: str = "",
) -> list[BaseMessage]:
    system = SystemMessage(
        content=(
            f"You are the {specialist} investigating an incident.\n"
            f"Alert: {_alert_summary(alert)}\n"
            f"Your objective: {objective}\n"
            f"{dependency_context}\n"
            "Use your tools to gather evidence. Be surgical: narrow time windows (the alert "
            f"fired at {alert.get('ts')}), filter by service, prefer summaries over raw dumps. "
            "When you can answer the objective, stop calling tools. If evidence is "
            "inconclusive, say so with confidence < 0.5 - never invent evidence."
        )
    )
    return [system]


def specialist_observations_message(summary: str) -> BaseMessage:
    return HumanMessage(content=f"Your investigation gathered:\n{summary}")


def specialist_finish_message(specialist: str, step_id: str) -> BaseMessage:
    return HumanMessage(
        content=(
            "Based only on the evidence you gathered, return a Finding as JSON with "
            f"step_id='{step_id}', specialist='{specialist}', a concise summary, an evidence "
            "list (each: kind, ref, excerpt), and a confidence 0-1. Do not call more tools."
        )
    )


# --- reviewer ------------------------------------------------------------------------
def review_messages(hypothesis: Hypothesis, findings: list[Finding]) -> list[BaseMessage]:
    system = SystemMessage(
        content=("You are an independent incident reviewer. You did not perform the investigation.")
    )
    human = HumanMessage(
        content=(
            f"Hypothesis: {json.dumps(hypothesis.model_dump(mode='json'))}\n"
            f"Evidence gathered:\n{_finding_block(findings)}\n\n"
            "Check: (1) does the cited evidence actually support the root cause - quote what "
            "does or note what's missing; (2) is the proposed action in the allowed catalog "
            "and aimed at the right service; (3) is it the smallest action that plausibly "
            "fixes the cause. Approve only if all three hold. Otherwise return 'revise' (or "
            "'reject' if the approach is unsalvageable) with specific, actionable feedback. "
            "Return JSON matching ReviewVerdict."
        )
    )
    return [system, human]


def plan_summary(plan: InvestigationPlan | None) -> str:
    if plan is None:
        return ""
    return plan.rationale


# --- memory writer (postmortem) ------------------------------------------------------
def postmortem_messages(
    alert: dict[str, Any],
    root_cause: str,
    affected_services: list[str],
    remediation: dict[str, Any] | None,
    recovery: dict[str, Any] | None,
    human_note: str = "",
) -> list[BaseMessage]:
    system = SystemMessage(
        content=(
            "You are the incident memory-writer. Write a concise, reusable lesson (3-6 "
            "sentences): symptom -> root cause -> fix, so a future responder recognizes this "
            "fault faster. Pick kind: 'incident_pattern' for a recurring failure signature, "
            "'lesson' for a general takeaway. Return JSON matching PostmortemMemory."
        )
    )
    human = HumanMessage(
        content=(
            f"Alert: {_alert_summary(alert)}\n"
            f"Root cause: {root_cause}\n"
            f"Affected services: {affected_services}\n"
            f"Remediation executed: {json.dumps(remediation, default=str)}\n"
            f"Recovery: {json.dumps(recovery, default=str)}\n"
            f"{human_note}"
        )
    )
    return [system, human]
