"""verify_recovery (04 §1, node table): re-evaluate the *breached* alert rule against
fresh metrics and declare recovery only after it reads OK on 2 consecutive checks
(10s apart) within 120s — the same two-consecutive discipline alertwatch uses to fire,
so a service's rolling window has time to settle after a restart (08 #7).

Deterministic: no LLM. Recovery polling cadence is injected via GraphDeps so graph tests
run it near-instantly instead of waiting real seconds."""

from __future__ import annotations

import operator
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from argus.db.session import session_scope
from argus.graph.support import now_iso, read_trace_id
from argus.obs.spans import span
from argus.repo import incidents as incident_repo
from argus.tools import worldstate

_OPS = {
    ">": operator.gt,
    "<": operator.lt,
    ">=": operator.ge,
    "<=": operator.le,
    "==": operator.eq,
}


@lru_cache
def _rule_ops(path: str = "config/alert_rules.yaml") -> dict[str, tuple[str, float]]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return {r["name"]: (r["op"], float(r["threshold"])) for r in data.get("rules", [])}


def _latest_value(service: str, metric: str, dep: str | None) -> float | None:
    lines = worldstate.read_metrics(service, metric, since_minutes=5)
    if dep:
        lines = [ln for ln in lines if (ln.get("labels") or {}).get("dep") == dep]
    for line in reversed(lines):
        value = line.get("value")
        if isinstance(value, int | float):
            return float(value)
    return None


def rule_ok(alert: dict[str, Any]) -> bool | None:
    """True if the breached rule now reads OK, False if still breaching, None if no data."""
    observed = alert.get("observed", {})
    metric = str(observed.get("metric", ""))
    service = str(alert.get("service", ""))
    dep = (alert.get("labels") or {}).get("dep")
    value = _latest_value(service, metric, dep)
    if value is None:
        return None
    op, cfg_threshold = _rule_ops().get(str(alert.get("rule", "")), (">", 0.0))
    threshold = float(observed.get("threshold", cfg_threshold))
    breached = _OPS.get(op, operator.gt)(value, threshold)
    return not breached


def verify_recovery(state: dict[str, Any], deps: Any) -> dict[str, Any]:
    alert = state["alert"]
    incident_id = state["incident_id"]
    trace_id = read_trace_id(incident_id)

    interval = deps.recovery_interval_s
    deadline = deps.recovery_deadline_s
    sleep = deps.recovery_sleep
    max_checks = 2 if interval <= 0 else max(2, int(deadline // interval) + 1)

    checks: list[dict[str, Any]] = []
    consecutive_ok = 0
    recovered = False
    with span("node.verify_recovery", "node", incident_id=incident_id, trace_id=trace_id) as sp:
        for i in range(max_checks):
            ok = rule_ok(alert)
            checks.append({"ts": now_iso(), "ok": bool(ok)})
            consecutive_ok = consecutive_ok + 1 if ok else 0
            if consecutive_ok >= 2:
                recovered = True
                break
            if i < max_checks - 1:
                sleep(interval)
        sp.set(recovered=recovered, checks=len(checks))

    attempts = len(state.get("remediation_attempts", []))
    max_attempts = int(deps.policy["limits"]["max_remediation_attempts"])
    with session_scope() as session:
        incident = incident_repo.get_incident(session, incident_id)
        if incident is not None:
            if recovered:
                incident_repo.transition(session, incident, "RECOVERED")
            elif attempts < max_attempts and incident.status == "REMEDIATING":
                # failed attempt becomes evidence; reset to INVESTIGATING and replan
                incident_repo.transition(session, incident, "INVESTIGATING")
            # else: attempts exhausted -> leave REMEDIATING; take_over sets TAKEN_OVER

    return {"recovery": {"recovered": recovered, "checks": checks}}
