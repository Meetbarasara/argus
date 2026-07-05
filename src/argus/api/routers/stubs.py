"""Not-yet-implemented endpoints (03 §4) declared now so the API surface is complete and
the UI has stable paths. Each returns 501 with the milestone that fills it in."""

from __future__ import annotations

from typing import Any, NoReturn

from fastapi import APIRouter

router = APIRouter()


def _todo(feature: str, milestone: str) -> NoReturn:
    from fastapi import HTTPException

    raise HTTPException(status_code=501, detail=f"{feature} is implemented in {milestone}")


@router.get("/approvals")
def list_approvals(status: str | None = None) -> Any:
    _todo("approvals queue", "M06")


@router.post("/approvals/{approval_id}/decision")
def approval_decision(approval_id: str) -> Any:
    _todo("approval decisions", "M06")


@router.post("/incidents/{incident_id}/takeover_resolution")
def takeover_resolution(incident_id: str) -> Any:
    _todo("takeover resolution", "M06")


@router.get("/memories")
def list_memories(query: str | None = None, kind: str | None = None) -> Any:
    _todo("memory browsing", "M07")


@router.delete("/memories/{memory_id}")
def delete_memory(memory_id: str) -> Any:
    _todo("memory deletion", "M07")


@router.post("/memories/consolidate")
def consolidate_memories() -> Any:
    _todo("memory consolidation", "M07")


@router.get("/dashboard/summary")
def dashboard_summary() -> Any:
    _todo("dashboard summary", "M09")


@router.get("/evals/runs")
def list_eval_runs() -> Any:
    _todo("eval runs", "M11")


@router.get("/evals/runs/{run_id}")
def get_eval_run(run_id: str) -> Any:
    _todo("eval run detail", "M11")
