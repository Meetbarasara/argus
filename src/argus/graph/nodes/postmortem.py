"""postmortem (M07): write a reusable memory from the resolved/taken-over incident via the
injected writer (memory_writer LLM for auto-resolutions, a deterministic lesson for human
take-overs). Honors MEMORY_ENABLED. The memory-writer call is post-resolution bookkeeping,
so it is not billed to the investigation budget."""

from __future__ import annotations

from typing import Any

from argus.graph.support import read_trace_id
from argus.obs.spans import span
from argus.settings import get_settings


def postmortem(state: dict[str, Any], deps: Any) -> dict[str, Any]:
    incident_id = state["incident_id"]
    trace_id = read_trace_id(incident_id)
    with span("node.postmortem", "node", incident_id=incident_id, trace_id=trace_id) as sp:
        if not get_settings().memory_enabled:
            sp.set(memory_used=False, note="MEMORY_ENABLED=false")
            return {}
        memory_id = deps.write_postmortem(
            state,
            deps.router,
            incident_id=incident_id,
            trace_id=trace_id,
            parent_span_id=sp.span_id,
        )
        sp.set(memory_id=memory_id, memory_used=bool(memory_id))
    return {}
