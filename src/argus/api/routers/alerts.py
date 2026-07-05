"""Alert webhook → incident intake (02 flow 1). Service-level dedupe with a race guard;
new incidents enqueue the worker only after the row is durably committed."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from argus.api.schemas import AlertPayload, WebhookResponse
from argus.db.session import get_db
from argus.repo import incidents as incident_repo
from argus.worker.app import celery_app

router = APIRouter()


@router.post("/alerts/webhook", response_model=WebhookResponse)
def alert_webhook(
    payload: AlertPayload, response: Response, session: Session = Depends(get_db)
) -> WebhookResponse:
    alert = payload.model_dump()

    existing = incident_repo.find_open_for_service(session, payload.service)
    if existing is not None:
        incident_repo.append_alert_event(session, existing, alert)
        response.status_code = 200
        return WebhookResponse(incident_id=existing.id, deduped=True)

    try:
        incident = incident_repo.create_incident(session, alert)  # flush may hit the unique index
        incident_id = incident.id
        session.commit()  # commit before enqueue so the worker sees a durable row
    except IntegrityError:
        session.rollback()
        existing = incident_repo.find_open_for_service(session, payload.service)
        if existing is None:
            raise
        incident_repo.append_alert_event(session, existing, alert)
        response.status_code = 200
        return WebhookResponse(incident_id=existing.id, deduped=True)

    celery_app.send_task("argus.worker.tasks.run_incident", args=[incident_id])
    response.status_code = 201
    return WebhookResponse(incident_id=incident_id, deduped=False)
