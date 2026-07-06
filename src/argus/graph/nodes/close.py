"""close (deterministic, terminal): finalize a recovered incident. Moves RECOVERED ->
RESOLVED (which stamps resolved_at + mttr_seconds in the repo) and rolls up the final
counters. RESOLVED with an empty postmortem is allowed in M05 (memory lands in M07)."""

from __future__ import annotations

from typing import Any

from argus.db.session import session_scope
from argus.graph.support import counter_rollup, read_trace_id
from argus.obs.spans import span
from argus.repo import incidents as incident_repo


def close(state: dict[str, Any], deps: Any) -> dict[str, Any]:
    incident_id = state["incident_id"]
    trace_id = read_trace_id(incident_id)
    with (
        span("node.close", "node", incident_id=incident_id, trace_id=trace_id) as sp,
        session_scope() as session,
    ):
        incident = incident_repo.get_incident(session, incident_id)
        if incident is not None and incident.status == "RECOVERED":
            fields = counter_rollup(session, incident_id, state.get("budget", {}))
            incident_repo.transition(session, incident, "RESOLVED", **fields)
            sp.set(status="RESOLVED")
    return {}
