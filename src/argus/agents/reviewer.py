"""Reviewer agent (04 §4; role ``reviewer`` — a different provider than the specialists
by design). Independently checks whether the evidence supports the hypothesis and whether
the proposed action is safe and proportional, returning a structured verdict."""

from __future__ import annotations

from argus.agents import prompts
from argus.agents.schemas import Finding, Hypothesis, ReviewVerdict
from argus.llm.router import LLMRouter


def review(
    router: LLMRouter,
    hypothesis: Hypothesis,
    findings: list[Finding],
    *,
    incident_id: str,
    trace_id: str,
    parent_span_id: str,
) -> ReviewVerdict:
    messages = prompts.review_messages(hypothesis, findings)
    return router.structured(
        "reviewer",
        messages,
        ReviewVerdict,
        incident_id=incident_id,
        trace_id=trace_id,
        parent_span_id=parent_span_id,
    )
