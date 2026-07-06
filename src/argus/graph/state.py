"""IncidentState — the graph's shared state (04 §2, verbatim shape).

Reducer channels (``operator.add``) make appends parallel-safe for M08's fan-out; M05
runs specialists sequentially but uses the same shape. Pydantic models are stored
directly and round-trip through the checkpointer's serializer; excerpts are capped by the
schemas so checkpoints never carry raw tool dumps (08 #21)."""

from __future__ import annotations

import operator
from typing import Annotated, Any, NotRequired, TypedDict

from argus.agents.schemas import Finding, Hypothesis, InvestigationPlan, ReviewVerdict


class MemoryHit(TypedDict):
    memory_id: str
    title: str
    content: str
    similarity: float
    kind: str


class IncidentState(TypedDict):
    incident_id: str
    alert: dict[str, Any]  # payload from 03 §2
    service_catalog: dict[str, Any]  # {service: {class, description}} from policy.yaml
    memory_hits: list[MemoryHit]  # [{memory_id, title, content, similarity, kind}]
    fast_path_hint: NotRequired[dict[str, Any]]  # {memory_id, previous_remediation, similarity}
    plan: NotRequired[InvestigationPlan]
    findings: Annotated[list[Finding], operator.add]  # append reducer (parallel-safe)
    hypothesis: NotRequired[Hypothesis]
    review_history: Annotated[list[ReviewVerdict], operator.add]
    escalation: NotRequired[dict[str, Any]]  # {level, rule_trace, approval_id}
    approval_decision: NotRequired[dict[str, Any]]  # resume payload (M06)
    remediation_attempts: Annotated[list[dict[str, Any]], operator.add]  # {action, result, ts}
    recovery: NotRequired[dict[str, Any]]  # {recovered: bool, checks: [...]}
    budget: dict[str, Any]  # {llm_calls_used, started_at_iso}
    status_reason: NotRequired[str]
