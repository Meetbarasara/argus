"""postmortem (no-op until M07): the memory-writer node will summarize the incident into
a persistent memory here. In M05 it only emits its span; the incident is flagged
memory_used=false and the status machine allows RECOVERED -> RESOLVED with no memory."""

from __future__ import annotations

from typing import Any

from argus.graph.support import read_trace_id
from argus.obs.spans import span


def postmortem(state: dict[str, Any], deps: Any) -> dict[str, Any]:
    incident_id = state["incident_id"]
    trace_id = read_trace_id(incident_id)
    with span("node.postmortem", "node", incident_id=incident_id, trace_id=trace_id) as sp:
        sp.set(memory_used=False, note="postmortem memory write lands in M07")
    return {}
