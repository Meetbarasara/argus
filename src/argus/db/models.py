"""SQLAlchemy 2 models — the complete platform schema (03 §1).

All tables are defined now so schema churn stays in this milestone; later milestones only
read/write these. Indexes (including the pgvector HNSW index and the partial-unique
dedupe index) live in ``__table_args__`` so the Alembic migration can build everything
with ``metadata.create_all`` after the vector extension exists.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Index,
    Integer,
    Numeric,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# statuses that are terminal — no non-terminal incident may share a service (dedupe)
TERMINAL_STATUSES = ("RESOLVED", "TAKEN_OVER", "FAILED")


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


def _pk() -> Mapped[str]:
    return mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), default=_now, server_default=func.now())


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[str] = _pk()
    trace_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    service: Mapped[str] = mapped_column(Text)  # denormalized from alert for dedupe/display
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now(), onupdate=_now
    )
    status: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    alert: Mapped[dict] = mapped_column(JSONB)
    alert_events: Mapped[list] = mapped_column(JSONB, default=list)
    root_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    remediation: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    escalation_level: Mapped[str | None] = mapped_column(Text, nullable=True)
    status_reason: Mapped[str | None] = mapped_column(Text, nullable=True)  # why FAILED/TAKEN_OVER
    memory_used: Mapped[bool] = mapped_column(Boolean, default=False)
    fast_path: Mapped[bool] = mapped_column(Boolean, default=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    mttr_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    llm_calls: Mapped[int] = mapped_column(Integer, default=0)
    tool_calls_count: Mapped[int] = mapped_column(Integer, default=0)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=0)
    eval_case_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)

    __table_args__ = (
        Index("ix_incidents_status", "status"),
        Index("ix_incidents_created_at", text("created_at DESC")),
        # at most one non-terminal incident per service (service-level dedupe, 08 #10)
        Index(
            "uq_incident_open_service",
            "service",
            unique=True,
            postgresql_where=text("status NOT IN ('RESOLVED', 'TAKEN_OVER', 'FAILED')"),
        ),
    )


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[str] = _pk()
    incident_id: Mapped[str] = mapped_column(UUID(as_uuid=False), index=True)
    created_at: Mapped[datetime] = _created()
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    level: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    proposed_action: Mapped[dict] = mapped_column(JSONB)
    context: Mapped[dict] = mapped_column(JSONB)
    decided_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    modified_action: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (Index("ix_approvals_status", "status"),)


class Span(Base):
    __tablename__ = "spans"

    span_id: Mapped[str] = mapped_column(Text, primary_key=True)
    trace_id: Mapped[str] = mapped_column(Text, index=True)
    incident_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), index=True, nullable=True)
    parent_span_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    name: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attrs: Mapped[dict] = mapped_column(JSONB, default=dict)


class LLMCall(Base):
    __tablename__ = "llm_calls"

    id: Mapped[str] = _pk()
    span_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    incident_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), index=True, nullable=True)
    role: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(Text)
    messages: Mapped[dict] = mapped_column(JSONB)
    response: Mapped[dict] = mapped_column(JSONB)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    validation_retries: Mapped[int] = mapped_column(Integer, default=0)
    mode: Mapped[str] = mapped_column(Text)
    cache_key: Mapped[str] = mapped_column(Text, index=True)
    created_at: Mapped[datetime] = _created()


class ToolCall(Base):
    __tablename__ = "tool_calls"

    id: Mapped[str] = _pk()
    span_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    incident_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), index=True, nullable=True)
    agent: Mapped[str] = mapped_column(Text)
    tool: Mapped[str] = mapped_column(Text)
    args: Mapped[dict] = mapped_column(JSONB)
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = _created()


class Memory(Base):
    __tablename__ = "memories"

    id: Mapped[str] = _pk()
    kind: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    fingerprint: Mapped[dict] = mapped_column(JSONB)
    embedding: Mapped[list[float]] = mapped_column(Vector(384))
    importance: Mapped[float] = mapped_column(Float, default=1.0)
    use_count: Mapped[int] = mapped_column(Integer, default=0)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_incident_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    created_at: Mapped[datetime] = _created()
    superseded_by: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)

    __table_args__ = (
        Index(
            "ix_memories_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id: Mapped[str] = _pk()
    started_at: Mapped[datetime] = _created()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    suite: Mapped[str] = mapped_column(Text)
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    git_sha: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class EvalCase(Base):
    __tablename__ = "eval_cases"

    id: Mapped[str] = _pk()
    run_id: Mapped[str] = mapped_column(UUID(as_uuid=False), index=True)
    scenario_id: Mapped[str] = mapped_column(Text)
    incident_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    rca_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    rca_judge_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    remediation_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    recovered: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    escalation_expected: Mapped[str | None] = mapped_column(Text, nullable=True)
    escalation_actual: Mapped[str | None] = mapped_column(Text, nullable=True)
    escalation_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    llm_calls: Mapped[int] = mapped_column(Integer, default=0)
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=0)
    mttr_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    outcome: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _created()
