"""Not-yet-implemented endpoints (03 §4) declared now so the API surface is complete and
the UI has stable paths. Each returns 501 with the milestone that fills it in."""

from __future__ import annotations

from typing import Any, NoReturn

from fastapi import APIRouter

router = APIRouter()


def _todo(feature: str, milestone: str) -> NoReturn:
    from fastapi import HTTPException

    raise HTTPException(status_code=501, detail=f"{feature} is implemented in {milestone}")


@router.get("/evals/runs")
def list_eval_runs() -> Any:
    _todo("eval runs", "M11")


@router.get("/evals/runs/{run_id}")
def get_eval_run(run_id: str) -> Any:
    _todo("eval run detail", "M11")
