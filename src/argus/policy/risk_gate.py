"""The deterministic risk gate (03 §3, ADR-04).

``evaluate_risk`` is a pure function of (action, target service, confidence, policy) →
(escalation level, human-readable rule trace). No LLM, no I/O — so the gate is fully
unit-testable and the LLM can never talk its way past it. The graph node wraps this,
emits a ``policy`` span carrying the trace, and routes on the returned level.

Level strictness order (03 §3): AUTO < NOTIFY < APPROVE_ACTION < APPROVE_PLAN < TAKE_OVER.
Confidence overrides are applied after the action's base level and the stricter wins.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

# Strictness order — index = strictness. Used to pick "the stricter wins".
LEVEL_ORDER = ["AUTO", "NOTIFY", "APPROVE_ACTION", "APPROVE_PLAN", "TAKE_OVER"]


def stricter(a: str, b: str) -> str:
    """Return whichever of the two levels is stricter (higher in LEVEL_ORDER)."""
    return a if LEVEL_ORDER.index(a) >= LEVEL_ORDER.index(b) else b


@dataclass(frozen=True)
class RiskDecision:
    level: str
    rule_trace: list[str]


@lru_cache
def load_policy(path: str = "config/policy.yaml") -> dict[str, Any]:
    return dict(yaml.safe_load(Path(path).read_text(encoding="utf-8")))


def evaluate_risk(
    *,
    tool: str,
    target_service: str,
    confidence: float,
    policy: dict[str, Any],
) -> RiskDecision:
    """Map a proposed remediation to an escalation level with a full rule trace."""
    trace: list[str] = []
    actions = policy["actions"]

    if tool == "restart_service":
        cls = policy.get("target_classes", {}).get(target_service)
        if cls is None:
            trace.append(f"unknown target service '{target_service}' -> TAKE_OVER")
            return RiskDecision("TAKE_OVER", trace)
        level = actions.get("restart_service", {}).get(cls)
        if level is None:
            trace.append(f"no restart_service rule for class '{cls}' -> TAKE_OVER")
            return RiskDecision("TAKE_OVER", trace)
        trace.append(f"restart_service on {target_service} (class={cls}) -> {level}")
    elif tool == "rollback_deploy":
        level = actions.get("rollback_deploy", {}).get("default", "TAKE_OVER")
        trace.append(f"rollback_deploy -> {level} (default)")
    else:
        trace.append(f"unknown action '{tool}' -> TAKE_OVER")
        return RiskDecision("TAKE_OVER", trace)

    for override in policy.get("confidence_overrides", []):
        below = override["below"]
        if confidence < below:
            candidate = override.get("level") or override["at_least"]
            new_level = stricter(level, candidate)
            key = "level" if "level" in override else "at_least"
            trace.append(
                f"confidence {confidence} < {below} -> {key} {candidate}; stricter = {new_level}"
            )
            level = new_level

    return RiskDecision(level, trace)
