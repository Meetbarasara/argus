"""Celery tasks. M05: run_incident drives the compiled LangGraph pipeline with
``thread_id = incident_id``. Nodes own every status transition (via incident_repo); this
wrapper only starts the run, catches unhandled errors as FAILED, and reports the final
status. Resume (M06) will re-enter the same thread after a human decision."""

from __future__ import annotations

from typing import Any

import structlog
from celery.signals import worker_process_init

from argus.db.models import TERMINAL_STATUSES
from argus.db.session import session_scope
from argus.graph.runtime import get_compiled_graph
from argus.graph.support import now_iso
from argus.repo import incidents as incident_repo
from argus.worker.app import celery_app

log = structlog.get_logger(__name__)


@worker_process_init.connect
def _warm_graph(**_: Any) -> None:
    """Compile the graph + run the checkpointer .setup() once per worker child (08 #17)."""
    try:
        get_compiled_graph()
    except Exception:  # DB may not be ready yet; the first task will retry lazily
        log.warning("graph.warm_failed", exc_info=True)


def _initial_state(incident_id: str, alert: dict[str, Any]) -> dict[str, Any]:
    return {
        "incident_id": incident_id,
        "alert": alert,
        "service_catalog": {},
        "memory_hits": [],
        "findings": [],
        "review_history": [],
        "remediation_attempts": [],
        "budget": {"llm_calls_used": 0, "started_at_iso": now_iso()},
    }


@celery_app.task(name="argus.worker.tasks.run_incident")
def run_incident(incident_id: str) -> str:
    with session_scope() as session:
        incident = incident_repo.get_incident(session, incident_id)
        if incident is None:
            log.warning("run_incident.unknown", incident_id=incident_id)
            return "unknown"
        alert = dict(incident.alert)

    log.info("run_incident.start", incident_id=incident_id)
    try:
        graph = get_compiled_graph()
        graph.invoke(
            _initial_state(incident_id, alert),
            config={"configurable": {"thread_id": incident_id}},
        )
    except Exception as exc:
        log.exception("run_incident.failed", incident_id=incident_id)
        with session_scope() as session:
            incident = incident_repo.get_incident(session, incident_id)
            if incident is not None and incident.status not in TERMINAL_STATUSES:
                incident_repo.transition(
                    session, incident, "FAILED", status_reason=f"graph error: {exc}"
                )
        return "failed"

    with session_scope() as session:
        incident = incident_repo.get_incident(session, incident_id)
        final = incident.status if incident is not None else "unknown"
    log.info("run_incident.done", incident_id=incident_id, status=final)
    return final


@celery_app.task(name="argus.worker.tasks.resume_incident")
def resume_incident(incident_id: str, approval_id: str | None = None) -> str:
    raise NotImplementedError("resume_incident lands in M06")
