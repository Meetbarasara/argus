"""Structured-output schemas (04 §3, verbatim). These are the contracts every LLM node
speaks; the router validates model output against them (validation-retry ≤2). Evidence
excerpts are capped here so checkpoints never bloat with raw tool dumps (08 #21)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class PlanStep(BaseModel):
    id: str  # "step-1"
    specialist: Literal["log_analyst", "metrics_analyst", "change_analyst"]
    objective: str  # one question to answer
    depends_on: list[str] = []


class InvestigationPlan(BaseModel):
    steps: list[PlanStep] = Field(min_length=1, max_length=5)
    rationale: str


class Evidence(BaseModel):
    kind: Literal["log", "metric", "deploy", "action", "memory"]
    ref: str  # e.g. "logs/shopapi.jsonl@2026-07-05T10:31Z" or "d-0042"
    excerpt: str = Field(max_length=500)


class Finding(BaseModel):
    step_id: str
    specialist: str
    summary: str
    evidence: list[Evidence] = Field(max_length=6)
    confidence: float = Field(ge=0, le=1)


class RemediationAction(BaseModel):
    tool: Literal["restart_service", "rollback_deploy"]  # the remediation catalog
    params: dict  # validated against the tool's arg schema
    target_service: str
    rationale: str


class Hypothesis(BaseModel):
    root_cause: str
    affected_services: list[str]
    confidence: float = Field(ge=0, le=1)
    supporting_evidence: list[Evidence] = Field(max_length=8)
    proposed_action: RemediationAction


class ReviewChecks(BaseModel):
    evidence_supported: bool  # does cited evidence actually support the root cause?
    action_safe: bool  # is the action from the catalog, targeting the right service?
    action_proportional: bool  # smallest action that plausibly fixes it?


class ReviewVerdict(BaseModel):
    verdict: Literal["approve", "revise", "reject"]
    checks: ReviewChecks
    feedback: str  # required when revise/reject


class PostmortemMemory(BaseModel):
    title: str
    content: str  # 3-6 sentence lesson: symptom -> cause -> fix
    kind: Literal["incident_pattern", "lesson"]


class JudgeVerdict(BaseModel):  # eval harness (07)
    match: bool
    reason: str
