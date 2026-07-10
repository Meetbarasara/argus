"""Eval runs API (03 §4, M11): list runs + run detail. Powers the UI Dashboard eval panel.
Read-only — runs are launched from the host CLI (`python -m argus.evals.run`), never the UI
(keeps docker access host-side)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from argus.db.models import EvalCase, EvalRun
from argus.db.session import get_db

router = APIRouter()


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None


def _case_dict(c: EvalCase) -> dict[str, Any]:
    return {
        "id": c.id,
        "scenario_id": c.scenario_id,
        "incident_id": c.incident_id,
        "outcome": c.outcome,
        "rca_correct": c.rca_correct,
        "rca_judge_reason": c.rca_judge_reason,
        "remediation_correct": c.remediation_correct,
        "recovered": c.recovered,
        "escalation_expected": c.escalation_expected,
        "escalation_actual": c.escalation_actual,
        "escalation_correct": c.escalation_correct,
        "llm_calls": c.llm_calls,
        "cost_usd": float(c.cost_usd),
        "mttr_seconds": c.mttr_seconds,
    }


@router.get("/evals/runs")
def list_eval_runs(session: Session = Depends(get_db)) -> list[dict[str, Any]]:
    runs = session.scalars(select(EvalRun).order_by(EvalRun.started_at.desc())).all()
    out: list[dict[str, Any]] = []
    for r in runs:
        cases = session.execute(
            select(func.count(), func.count().filter(EvalCase.outcome == "PASS")).where(
                EvalCase.run_id == r.id
            )
        ).one()
        out.append(
            {
                "id": r.id,
                "suite": r.suite,
                "started_at": _iso(r.started_at),
                "finished_at": _iso(r.finished_at),
                "config": r.config,
                "git_sha": r.git_sha,
                "notes": r.notes,
                "cases": int(cases[0]),
                "passes": int(cases[1]),
            }
        )
    return out


@router.get("/evals/runs/{run_id}")
def get_eval_run(run_id: str, session: Session = Depends(get_db)) -> dict[str, Any]:
    run = session.get(EvalRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="eval run not found")
    cases = session.scalars(
        select(EvalCase).where(EvalCase.run_id == run_id).order_by(EvalCase.scenario_id)
    ).all()
    return {
        "id": run.id,
        "suite": run.suite,
        "started_at": _iso(run.started_at),
        "finished_at": _iso(run.finished_at),
        "config": run.config,
        "git_sha": run.git_sha,
        "notes": run.notes,
        "cases": [_case_dict(c) for c in cases],
    }
