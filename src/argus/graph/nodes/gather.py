"""gather (deterministic join): the single fan-in point where the specialist Send-branches
converge (08 #20 — interrupts stay strictly *after* this join, never inside the fan-out).

It runs the two checks the plan/synthesize single nodes can't do mid-fan-out:
  * budget breach re-check *after* the wave (llm_calls now include the specialists' calls via
    ``total_llm_calls``) → mark breached so the join routes to take_over;
  * degradation gate — if this cycle's investigation mostly failed (> 50% confidence-0
    findings) skip synthesizing a hypothesis on empty evidence and escalate to a human.

When neither trips and a dependent wave is still pending, ``build.route_after_gather``
dispatches it; otherwise the run proceeds to synthesize. This node only *writes* the routing
signals (breached budget / status_reason); the pure routing decision lives in build.py."""

from __future__ import annotations

from typing import Any

from argus.graph import fanout
from argus.graph.support import budget_breach_reason, mark_breached

DEGRADED_REASON = "investigation degraded: majority of steps produced no usable evidence"


def gather(state: dict[str, Any], deps: Any) -> dict[str, Any]:
    reason = budget_breach_reason(state, deps.policy)
    if reason is not None:
        return {"budget": mark_breached(state), "status_reason": reason}
    if not fanout.remaining_steps(state) and fanout.investigation_degraded(state):
        return {"status_reason": DEGRADED_REASON}
    return {}
