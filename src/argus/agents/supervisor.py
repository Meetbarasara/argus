"""Supervisor agent (04 §4; role ``supervisor``): plans the investigation and later
synthesizes the findings into a root-cause hypothesis with a proposed remediation. Both
are single structured calls; validation-retry lives in the router."""

from __future__ import annotations

from typing import Any

from argus.agents import prompts
from argus.agents.schemas import Finding, Hypothesis, InvestigationPlan
from argus.llm.router import LLMRouter


def plan(
    router: LLMRouter,
    alert: dict[str, Any],
    service_catalog: dict[str, Any],
    memory_hits: list[dict[str, Any]],
    fast_path_hint: dict[str, Any] | None = None,
    *,
    incident_id: str,
    trace_id: str,
    parent_span_id: str,
) -> InvestigationPlan:
    messages = prompts.plan_messages(alert, service_catalog, memory_hits, fast_path_hint)
    return router.structured(
        "supervisor",
        messages,
        InvestigationPlan,
        incident_id=incident_id,
        trace_id=trace_id,
        parent_span_id=parent_span_id,
    )


def synthesize(
    router: LLMRouter,
    alert: dict[str, Any],
    findings: list[Finding],
    memory_hits: list[dict[str, Any]],
    review_feedback: str | None = None,
    *,
    incident_id: str,
    trace_id: str,
    parent_span_id: str,
) -> Hypothesis:
    messages = prompts.synthesize_messages(alert, findings, memory_hits, review_feedback)
    return router.structured(
        "supervisor",
        messages,
        Hypothesis,
        incident_id=incident_id,
        trace_id=trace_id,
        parent_span_id=parent_span_id,
    )
