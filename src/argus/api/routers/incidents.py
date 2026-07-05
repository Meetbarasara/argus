"""Incident list/detail + span & llm_call drill-down (03 §4). Spans and llm_calls are
empty until M03+ populate them, but the endpoints exist now so the UI has stable paths."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from argus.api.schemas import IncidentDetail, IncidentSummary
from argus.db.models import Approval, LLMCall, Span
from argus.db.session import get_db
from argus.repo import incidents as incident_repo

router = APIRouter()


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None


def _approval_dict(a: Approval) -> dict[str, Any]:
    return {
        "id": a.id,
        "incident_id": a.incident_id,
        "created_at": _iso(a.created_at),
        "decided_at": _iso(a.decided_at),
        "level": a.level,
        "status": a.status,
        "proposed_action": a.proposed_action,
        "context": a.context,
        "decided_by": a.decided_by,
        "decision_comment": a.decision_comment,
        "modified_action": a.modified_action,
    }


def _span_dict(s: Span) -> dict[str, Any]:
    return {
        "span_id": s.span_id,
        "trace_id": s.trace_id,
        "incident_id": s.incident_id,
        "parent_span_id": s.parent_span_id,
        "name": s.name,
        "kind": s.kind,
        "status": s.status,
        "started_at": _iso(s.started_at),
        "ended_at": _iso(s.ended_at),
        "duration_ms": s.duration_ms,
        "attrs": s.attrs,
    }


@router.get("/incidents", response_model=list[IncidentSummary])
def list_incidents(
    status: str | None = None, limit: int = 50, session: Session = Depends(get_db)
) -> list[Any]:
    return incident_repo.list_incidents(session, status=status, limit=limit)


@router.get("/incidents/{incident_id}", response_model=IncidentDetail)
def get_incident(incident_id: str, session: Session = Depends(get_db)) -> IncidentDetail:
    incident = incident_repo.get_incident(session, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="incident not found")
    detail = IncidentDetail.model_validate(incident)
    approvals = session.scalars(
        select(Approval).where(Approval.incident_id == incident_id).order_by(Approval.created_at)
    ).all()
    detail.approvals = [_approval_dict(a) for a in approvals]
    return detail


@router.get("/incidents/{incident_id}/spans")
def get_incident_spans(
    incident_id: str, session: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    spans = session.scalars(
        select(Span).where(Span.incident_id == incident_id).order_by(Span.started_at)
    ).all()
    return [_span_dict(s) for s in spans]


@router.get("/llm_calls/{llm_call_id}")
def get_llm_call(llm_call_id: str, session: Session = Depends(get_db)) -> dict[str, Any]:
    call = session.get(LLMCall, llm_call_id)
    if call is None:
        raise HTTPException(status_code=404, detail="llm_call not found")
    return {
        "id": call.id,
        "incident_id": call.incident_id,
        "span_id": call.span_id,
        "role": call.role,
        "provider": call.provider,
        "model": call.model,
        "messages": call.messages,
        "response": call.response,
        "tokens_in": call.tokens_in,
        "tokens_out": call.tokens_out,
        "cost_usd": float(call.cost_usd),
        "latency_ms": call.latency_ms,
        "validation_retries": call.validation_retries,
        "mode": call.mode,
        "created_at": _iso(call.created_at),
    }
