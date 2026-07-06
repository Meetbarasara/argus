"""intake (deterministic): open the incident's trace, move OPEN -> INVESTIGATING, build
the service catalog from policy, and start the wall-clock budget."""

from __future__ import annotations

from typing import Any

from argus.db.session import session_scope
from argus.graph.support import now_iso, read_trace_id
from argus.obs.spans import span
from argus.repo import incidents as incident_repo

CLASS_DESCRIPTIONS = {
    "cache": "in-memory cache",
    "database": "relational database",
    "service": "application service",
}


def build_service_catalog(policy: dict[str, Any]) -> dict[str, Any]:
    return {
        service: {"class": cls, "description": CLASS_DESCRIPTIONS.get(cls, cls)}
        for service, cls in policy.get("target_classes", {}).items()
    }


def intake(state: dict[str, Any], deps: Any) -> dict[str, Any]:
    incident_id = state["incident_id"]
    # reuse the worker-opened trace (root span) if present; generate one for direct graph runs
    trace_id = read_trace_id(incident_id)
    catalog = build_service_catalog(deps.policy)

    with (
        span("node.intake", "node", incident_id=incident_id, trace_id=trace_id) as sp,
        session_scope() as session,
    ):
        incident = incident_repo.get_incident(session, incident_id)
        if incident is not None:
            if incident.status == "OPEN":
                incident_repo.transition(session, incident, "INVESTIGATING", trace_id=trace_id)
            else:  # already advanced (defensive) — still stamp the trace id
                incident.trace_id = trace_id
                session.add(incident)
        sp.set(services=len(catalog))

    budget = {
        "llm_calls_used": int((state.get("budget") or {}).get("llm_calls_used", 0)),
        "started_at_iso": now_iso(),
    }
    return {"service_catalog": catalog, "budget": budget}
