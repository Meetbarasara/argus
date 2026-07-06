"""recall_memory (deterministic): a no-op until M07 wires pgvector recall. It always
writes an empty memory_hits list (the graph downstream reads it unconditionally) and
leaves incidents.memory_used at its default (false)."""

from __future__ import annotations

from typing import Any

from argus.graph.support import read_trace_id
from argus.obs.spans import span


def recall_memory(state: dict[str, Any], deps: Any) -> dict[str, Any]:
    incident_id = state["incident_id"]
    trace_id = read_trace_id(incident_id)
    with span("node.recall_memory", "node", incident_id=incident_id, trace_id=trace_id) as sp:
        sp.set(hits=0, note="memory recall lands in M07")
    return {"memory_hits": []}
