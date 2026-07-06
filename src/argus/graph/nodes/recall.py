"""recall_memory (M07): embed the alert, recall scored memories, and offer a fast-path
hint for a near-identical resolved incident. Honors MEMORY_ENABLED (off ⇒ empty hits, and
the plan prompt's memory block is the ablation-clean "No similar past incidents." line).
Recall itself is injected via deps so host graph tests never load the embedder."""

from __future__ import annotations

from typing import Any

from argus.db.session import session_scope
from argus.graph.support import read_trace_id
from argus.obs.spans import span
from argus.repo import incidents as incident_repo
from argus.settings import get_settings


def recall_memory(state: dict[str, Any], deps: Any) -> dict[str, Any]:
    incident_id = state["incident_id"]
    trace_id = read_trace_id(incident_id)

    with span("node.recall_memory", "node", incident_id=incident_id, trace_id=trace_id) as sp:
        if not get_settings().memory_enabled:
            sp.set(memory_enabled=False, hits=0)
            return {"memory_hits": []}
        hits, fast_path = deps.recall(state["alert"])
        sp.set(memory_enabled=True, hits=len(hits), fast_path=bool(fast_path))

    if hits or fast_path:
        with session_scope() as session:
            incident = incident_repo.get_incident(session, incident_id)
            if incident is not None:
                incident.memory_used = bool(hits)
                incident.fast_path = bool(fast_path)
                session.add(incident)

    updates: dict[str, Any] = {"memory_hits": hits}
    if fast_path:
        updates["fast_path_hint"] = fast_path
    return updates
