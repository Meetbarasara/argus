"""API request/response models (03 §4). Pydantic everywhere; from_attributes maps ORM rows."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class AlertPayload(BaseModel):
    """Alert webhook body (03 §2). Lenient: extra keys are kept."""

    model_config = ConfigDict(extra="allow")

    alert_id: str
    rule: str
    service: str
    severity: str
    ts: str
    window_seconds: int = 60
    observed: dict[str, Any] = {}
    labels: dict[str, Any] = {}
    summary: str = ""


class WebhookResponse(BaseModel):
    incident_id: str
    deduped: bool = False


class IncidentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    service: str
    status: str
    severity: str
    title: str
    created_at: datetime
    updated_at: datetime
    escalation_level: str | None = None
    memory_used: bool = False
    fast_path: bool = False
    llm_calls: int = 0
    cost_usd: float = 0.0


class IncidentDetail(IncidentSummary):
    trace_id: str | None = None
    alert: dict[str, Any] = {}
    alert_events: list[Any] = []
    root_cause: str | None = None
    confidence: float | None = None
    remediation: dict[str, Any] | None = None
    status_reason: str | None = None
    resolved_at: datetime | None = None
    mttr_seconds: int | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    tool_calls_count: int = 0
    approvals: list[dict[str, Any]] = []


class ApprovalDecision(BaseModel):
    """Body for POST /approvals/{id}/decision (03 §4)."""

    decision: Literal["approve", "reject", "modify", "ack"]
    comment: str | None = None
    modified_action: dict[str, Any] | None = None  # required when decision == "modify"


class TakeoverResolution(BaseModel):
    """Body for POST /incidents/{id}/takeover_resolution (03 §4)."""

    root_cause: str
    action_taken: str


class HealthConfig(BaseModel):
    llm_mode: str
    auto_approve: str
    memory_enabled: bool
    supervisor_model: str


class HealthResponse(BaseModel):
    status: str
    db: bool
    redis: bool
    worldstate_mounted: bool
    config: HealthConfig
