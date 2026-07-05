"""Celery tasks. v0 (M02): prove the alert→incident→worker pipe end-to-end. The real
LangGraph run lands in M05; until then run_incident marks the incident INVESTIGATING then
FAILED with a clear reason."""

from __future__ import annotations

import structlog

from argus.db.session import session_scope
from argus.repo import incidents as incident_repo
from argus.worker.app import celery_app

log = structlog.get_logger(__name__)


@celery_app.task(name="argus.worker.tasks.run_incident")
def run_incident(incident_id: str) -> str:
    with session_scope() as session:
        incident = incident_repo.get_incident(session, incident_id)
        if incident is None:
            log.warning("run_incident.unknown", incident_id=incident_id)
            return "unknown"
        incident_repo.transition(session, incident, "INVESTIGATING")
    log.info("run_incident.investigating", incident_id=incident_id)

    # v0 terminal: the graph is not wired yet (M05).
    with session_scope() as session:
        incident = incident_repo.get_incident(session, incident_id)
        if incident is not None:
            incident_repo.transition(
                session, incident, "FAILED", status_reason="graph not implemented (M05)"
            )
    return "failed_v0"


@celery_app.task(name="argus.worker.tasks.resume_incident")
def resume_incident(incident_id: str, approval_id: str | None = None) -> str:
    raise NotImplementedError("resume_incident lands in M06")
