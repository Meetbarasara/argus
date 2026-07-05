"""Incident repository — the single writer of incident status, enforcing the 03 §1
state machine. Any illegal transition raises PolicyError rather than silently corrupting
an incident's lifecycle."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from argus.db.models import TERMINAL_STATUSES, Incident
from argus.errors import PolicyError

# Legal transitions (03 §1). Terminal states have no outgoing edges.
STATE_TRANSITIONS: dict[str, set[str]] = {
    "OPEN": {"INVESTIGATING", "TAKEN_OVER", "FAILED"},
    "INVESTIGATING": {"WAITING_APPROVAL", "REMEDIATING", "TAKEN_OVER", "FAILED"},
    "WAITING_APPROVAL": {"INVESTIGATING", "REMEDIATING", "TAKEN_OVER", "FAILED"},
    "REMEDIATING": {"RECOVERED", "INVESTIGATING", "TAKEN_OVER", "FAILED"},
    "RECOVERED": {"RESOLVED", "TAKEN_OVER", "FAILED"},
    "RESOLVED": set(),
    "TAKEN_OVER": set(),
    "FAILED": set(),
}

_RULE_TITLES = {
    "high_error_rate": "High error rate",
    "high_latency_p95": "High latency",
    "dependency_down": "Dependency down",
}


def can_transition(current: str, new: str) -> bool:
    return new in STATE_TRANSITIONS.get(current, set())


def _title(alert: dict[str, Any]) -> str:
    rule = str(alert.get("rule", "alert"))
    service = str(alert.get("service", "unknown"))
    return f"{_RULE_TITLES.get(rule, rule)} on {service}"


def create_incident(session: Session, alert: dict[str, Any]) -> Incident:
    incident = Incident(
        service=str(alert.get("service", "unknown")),
        status="OPEN",
        severity=str(alert.get("severity", "warning")),
        title=_title(alert),
        alert=alert,
        alert_events=[],
    )
    session.add(incident)
    session.flush()  # assign id
    return incident


def find_open_for_service(session: Session, service: str) -> Incident | None:
    stmt = (
        select(Incident)
        .where(Incident.service == service, Incident.status.notin_(TERMINAL_STATUSES))
        .limit(1)
    )
    return session.scalars(stmt).first()


def append_alert_event(session: Session, incident: Incident, alert: dict[str, Any]) -> None:
    incident.alert_events = [*(incident.alert_events or []), alert]
    session.add(incident)


def transition(session: Session, incident: Incident, new_status: str, **fields: Any) -> Incident:
    if not can_transition(incident.status, new_status):
        raise PolicyError(f"illegal incident transition {incident.status} -> {new_status}")
    incident.status = new_status
    for key, value in fields.items():
        setattr(incident, key, value)
    if new_status == "RESOLVED" and incident.resolved_at is None:
        incident.resolved_at = datetime.now(UTC)
        if incident.created_at is not None:
            delta = incident.resolved_at - incident.created_at
            incident.mttr_seconds = int(delta.total_seconds())
    session.add(incident)
    return incident


def get_incident(session: Session, incident_id: str) -> Incident | None:
    return session.get(Incident, incident_id)


def list_incidents(
    session: Session, *, status: str | None = None, limit: int = 50
) -> list[Incident]:
    stmt = select(Incident).order_by(Incident.created_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(Incident.status == status)
    return list(session.scalars(stmt).all())
