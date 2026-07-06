"""GET /dashboard/summary (03 §4): pure-SQL rollups for the dashboard + interview narrative
(M09). Every figure is a GROUP BY / aggregate — no Python loops over incident rows; the only
comprehensions assemble already-aggregated group rows into the response."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from argus.db.models import Incident, LLMCall, Span
from argus.db.session import get_db

router = APIRouter()

# escalation = the incident reached a human (approval hold or take-over); NOTIFY/AUTO don't.
_HUMAN_LEVELS = ("APPROVE_ACTION", "APPROVE_PLAN", "TAKE_OVER")


class RoleCost(BaseModel):
    role: str
    model: str
    calls: int
    tokens_in: int
    tokens_out: int
    cost_usd: float


class IncidentCost(BaseModel):
    incident_id: str
    service: str
    status: str
    cost_usd: float
    llm_calls: int


class DashboardSummary(BaseModel):
    total_incidents: int
    incidents_by_status: dict[str, int]
    resolution_rate: float
    escalation_rate: float
    memory_used_share: float
    avg_mttr_s: float | None
    median_mttr_s: float | None
    steps_to_diagnosis_avg: float | None
    total_cost_usd: float
    total_tokens_in: int
    total_tokens_out: int
    cost_by_role: list[RoleCost]
    cost_per_incident: list[IncidentCost]


def _rate(numer: int, denom: int) -> float:
    return round(numer / denom, 4) if denom else 0.0


@router.get("/dashboard/summary", response_model=DashboardSummary)
def dashboard_summary(session: Session = Depends(get_db)) -> DashboardSummary:
    by_status = {
        str(s): int(c)
        for s, c in session.execute(
            select(Incident.status, func.count()).group_by(Incident.status)
        ).all()
    }
    total = sum(by_status.values())
    resolved = by_status.get("RESOLVED", 0)

    escalated = session.execute(
        select(func.count())
        .select_from(Incident)
        .where(Incident.escalation_level.in_(_HUMAN_LEVELS))
    ).scalar_one()
    mem_used = session.execute(
        select(func.count()).select_from(Incident).where(Incident.memory_used.is_(True))
    ).scalar_one()

    avg_mttr, median_mttr = session.execute(
        select(
            func.avg(Incident.mttr_seconds),
            func.percentile_cont(0.5).within_group(Incident.mttr_seconds.asc()),
        ).where(Incident.mttr_seconds.isnot(None))
    ).one()

    # steps-to-diagnosis: avg number of llm spans per incident (subquery — no Python looping)
    per_incident_llm = (
        select(func.count().label("n"))
        .where(Span.kind == "llm", Span.incident_id.isnot(None))
        .group_by(Span.incident_id)
        .subquery()
    )
    steps_avg = session.execute(select(func.avg(per_incident_llm.c.n))).scalar_one()

    tok_in, tok_out, cost = session.execute(
        select(
            func.coalesce(func.sum(LLMCall.tokens_in), 0),
            func.coalesce(func.sum(LLMCall.tokens_out), 0),
            func.coalesce(func.sum(LLMCall.cost_usd), 0),
        )
    ).one()

    role_rows = session.execute(
        select(
            LLMCall.role,
            LLMCall.model,
            func.count(),
            func.coalesce(func.sum(LLMCall.tokens_in), 0),
            func.coalesce(func.sum(LLMCall.tokens_out), 0),
            func.coalesce(func.sum(LLMCall.cost_usd), 0),
        )
        .group_by(LLMCall.role, LLMCall.model)
        .order_by(func.coalesce(func.sum(LLMCall.cost_usd), 0).desc())
    ).all()

    cost_rows = session.execute(
        select(
            Incident.id,
            Incident.service,
            Incident.status,
            Incident.cost_usd,
            Incident.llm_calls,
        )
        .order_by(Incident.created_at.desc())
        .limit(20)
    ).all()

    return DashboardSummary(
        total_incidents=total,
        incidents_by_status=by_status,
        resolution_rate=_rate(resolved, total),
        escalation_rate=_rate(int(escalated), total),
        memory_used_share=_rate(int(mem_used), total),
        avg_mttr_s=float(avg_mttr) if avg_mttr is not None else None,
        median_mttr_s=float(median_mttr) if median_mttr is not None else None,
        steps_to_diagnosis_avg=float(steps_avg) if steps_avg is not None else None,
        total_tokens_in=int(tok_in),
        total_tokens_out=int(tok_out),
        total_cost_usd=float(cost),
        cost_by_role=[
            RoleCost(
                role=r,
                model=m,
                calls=int(c),
                tokens_in=int(ti),
                tokens_out=int(to),
                cost_usd=float(cu),
            )
            for r, m, c, ti, to, cu in role_rows
        ],
        cost_per_incident=[
            IncidentCost(
                incident_id=i,
                service=svc,
                status=st,
                cost_usd=float(cu),
                llm_calls=int(lc),
            )
            for i, svc, st, cu, lc in cost_rows
        ],
    )
