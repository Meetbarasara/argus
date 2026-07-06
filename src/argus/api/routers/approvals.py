"""Approvals queue + decision endpoint (03 §4, M06).

The decision flip is atomic (``UPDATE ... WHERE status='PENDING'`` — 08 #19): only a
winning flip enqueues the resume, so a double-decide is a 409 and duplicate resumes no-op.
``modify`` revalidates the new action against the tool's arg schema and re-runs the risk
gate — a modification that *raises* scrutiny above the approved level is rejected 422 (a
human can only narrow risk, never widen it past what policy allowed)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from argus.agents.schemas import RemediationAction
from argus.api.schemas import ApprovalDecision
from argus.db.models import Approval
from argus.db.session import get_db
from argus.policy.risk_gate import LEVEL_ORDER, evaluate_risk, load_policy
from argus.tools.registry import build_registry
from argus.worker.app import celery_app

router = APIRouter()


def _approval_dict(a: Approval) -> dict[str, Any]:
    return {
        "id": a.id,
        "incident_id": a.incident_id,
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "decided_at": a.decided_at.isoformat() if a.decided_at else None,
        "level": a.level,
        "status": a.status,
        "proposed_action": a.proposed_action,
        "context": a.context,
        "decided_by": a.decided_by,
        "decision_comment": a.decision_comment,
        "modified_action": a.modified_action,
    }


@router.get("/approvals")
def list_approvals(
    status: str | None = None, session: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    stmt = select(Approval).order_by(Approval.created_at.desc())
    if status:
        stmt = stmt.where(Approval.status == status)
    return [_approval_dict(a) for a in session.scalars(stmt).all()]


def _revalidate_and_regate(approval: Approval, modified_action: dict[str, Any] | None) -> None:
    """Validate a modified action against its tool schema and re-run the risk gate; reject
    (422) a modification that raises the escalation level above what was approved."""
    if not modified_action:
        raise HTTPException(status_code=422, detail="modify requires modified_action")
    try:
        action = RemediationAction.model_validate(modified_action)
        spec = build_registry().get(action.tool)
        if spec is None:
            raise HTTPException(status_code=422, detail=f"unknown tool: {action.tool}")
        spec.args_schema.model_validate(action.params)  # params must fit the tool schema
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=f"invalid modified_action: {exc}") from exc

    confidence = float((approval.context or {}).get("hypothesis", {}).get("confidence", 0.5))
    regated = evaluate_risk(
        tool=action.tool,
        target_service=action.target_service,
        confidence=confidence,
        policy=load_policy(),
    )
    if LEVEL_ORDER.index(regated.level) > LEVEL_ORDER.index(approval.level):
        raise HTTPException(
            status_code=422,
            detail=f"modification raises risk to {regated.level} above approved {approval.level}",
        )


@router.post("/approvals/{approval_id}/decision")
def decide(
    approval_id: str, body: ApprovalDecision, session: Session = Depends(get_db)
) -> dict[str, Any]:
    approval = session.get(Approval, approval_id)
    if approval is None:
        raise HTTPException(status_code=404, detail="approval not found")

    # NOTIFY info feed: AUTO -> ACK, no resume
    if body.decision == "ack":
        flipped = session.execute(
            update(Approval)
            .where(Approval.id == approval_id, Approval.status == "AUTO")
            .values(status="ACK", decided_at=datetime.now(UTC), decided_by="human")
            .returning(Approval.id)
        ).first()
        if flipped is None:
            raise HTTPException(status_code=409, detail="approval is not an AUTO row to ack")
        session.commit()
        return {"status": "ACK"}

    status_map = {"approve": "APPROVED", "reject": "REJECTED", "modify": "MODIFIED"}
    new_status = status_map[body.decision]
    modified = body.modified_action if body.decision == "modify" else None
    if body.decision == "modify":
        _revalidate_and_regate(approval, modified)  # 422 if invalid or riskier

    # atomic PENDING -> decided flip; only the winner enqueues the resume (08 #19)
    flipped = session.execute(
        update(Approval)
        .where(Approval.id == approval_id, Approval.status == "PENDING")
        .values(
            status=new_status,
            decided_at=datetime.now(UTC),
            decided_by="human",
            decision_comment=body.comment,
            modified_action=modified,
        )
        .returning(Approval.id)
    ).first()
    if flipped is None:
        raise HTTPException(status_code=409, detail="approval already decided or not pending")
    session.commit()  # durably decided before the resume task can read it

    celery_app.send_task(
        "argus.worker.tasks.resume_incident", args=[approval.incident_id, approval_id]
    )
    return {"status": new_status}
