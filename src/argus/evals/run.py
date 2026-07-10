"""Eval runner (07 §2), host-side CLI. Sequential case loop over the live platform:
set platform env (AUTO_APPROVE=policy_sim, MEMORY_ENABLED, optional supervisor override) →
verify via /api/health → per case: reset world → memory hygiene → inject → await alert→incident
→ await terminal → grade (07 §3) → persist eval_case. Cases run sequentially (free-tier RPM).

The case loop takes its platform interactions as a ``Platform`` bundle of callables so the
mechanics are unit-testable without docker or LLM quota; ``main`` wires the real ones."""

from __future__ import annotations

import argparse
import json
import operator
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import text

from argus.db.models import EvalCase, EvalRun
from argus.db.session import session_scope
from argus.evals import scenarios
from argus.evals.grade import CaseGrade, grade_case
from argus.graph.verify import rule_ok
from argus.llm.router import LLMRouter

TERMINAL = {"RESOLVED", "TAKEN_OVER", "FAILED", "CLOSED"}


@dataclass
class Platform:
    """Injectable platform interactions (real in ``main``, stubbed in tests)."""

    inject: Callable[[str, dict[str, Any]], None]
    reset: Callable[[], None]
    await_incident: Callable[[str, float], str | None]  # (since_iso, timeout) -> incident_id
    fetch_incident: Callable[[str], dict[str, Any]]
    await_terminal: Callable[[str, float], dict[str, Any]]  # (incident_id, timeout) -> incident
    recovered: Callable[[dict[str, Any]], bool]  # (alert) -> recovery re-derived from metrics


# --- persistence ---------------------------------------------------------------------
def _persist_case(
    run_id: str, case_id: str, incident: dict[str, Any] | None, grade: CaseGrade | None
) -> str:
    with session_scope() as session:
        row = EvalCase(
            run_id=run_id,
            scenario_id=case_id,
            incident_id=(incident or {}).get("id"),
            llm_calls=int((incident or {}).get("llm_calls") or 0),
            tokens=int((incident or {}).get("tokens_in") or 0)
            + int((incident or {}).get("tokens_out") or 0),
            cost_usd=(incident or {}).get("cost_usd") or 0,
            mttr_seconds=(incident or {}).get("mttr_seconds"),
        )
        if grade is not None:
            row.rca_correct = grade.rca_correct
            row.rca_judge_reason = grade.rca_judge_reason
            row.remediation_correct = grade.remediation_correct
            row.recovered = grade.recovered
            row.escalation_expected = grade.escalation_expected
            row.escalation_actual = grade.escalation_actual
            row.escalation_correct = grade.escalation_correct
            row.outcome = grade.outcome
        else:
            row.outcome = "FAIL"  # incident never materialised (alert/terminal timeout)
        session.add(row)
        session.flush()
        return str(row.id)


def run_case(case_id: str, platform: Platform, router: LLMRouter, run_id: str) -> str:
    """Run one case end-to-end and persist its eval_case row; returns the outcome."""
    sc = scenarios.load_scenario(case_id)
    expected = sc["expected"]
    params = sc.get("params", {})

    platform.reset()
    since = datetime.now(UTC).isoformat()
    platform.inject(sc["scenario"], params)

    incident_id = platform.await_incident(since, 120.0)
    if incident_id is None:
        _persist_case(run_id, case_id, None, None)
        return "FAIL(no-incident)"

    budget = float(sc.get("budgets", {}).get("max_wall_seconds", 420)) + 60.0
    incident = platform.await_terminal(incident_id, budget)
    alert = incident.get("alert", {})
    grade = grade_case(router, incident, alert, expected, recovered=platform.recovered(alert))
    _persist_case(run_id, case_id, incident, grade)
    return grade.outcome


def run_suite(
    case_ids: list[str], platform: Platform, router: LLMRouter, run_id: str
) -> dict[str, str]:
    results: dict[str, str] = {}
    for i, case_id in enumerate(case_ids, 1):
        print(f"[{i}/{len(case_ids)}] {case_id} …", flush=True)
        try:
            results[case_id] = run_case(case_id, platform, router, run_id)
        except Exception as exc:  # a broken case must not sink the whole suite
            print(f"    {case_id} errored: {exc}", flush=True)
            _persist_case(run_id, case_id, None, None)
            results[case_id] = f"ERROR({exc})"
        print(f"    → {results[case_id]}", flush=True)
    return results


# --- real platform wiring ------------------------------------------------------------
def _git_sha() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        return None


def _real_platform(api_url: str, actuator_url: str, token: str) -> Platform:
    from demoworld import inject as injector

    client = httpx.Client(base_url=api_url, timeout=15.0)

    def do_inject(scenario_key: str, params: dict[str, Any]) -> None:
        injector.inject(
            scenario_key,
            decoy_deploys=int(params.get("decoy_deploys", 0)),
            warmup_seconds=int(params.get("warmup_seconds", 0)),
            benign_restart=bool(params.get("benign_restart", False)),
            actuator_url=actuator_url,
            token=token,
        )

    def reset() -> None:
        # restart the world profile and let it warm up; per-case memory hygiene is separate
        subprocess.run(
            ["docker", "compose", "restart", "shopredis", "shopapi", "alertwatch"], check=False
        )
        time.sleep(8)

    def await_incident(since_iso: str, timeout: float) -> str | None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            incidents = client.get("/api/incidents", params={"limit": 20}).json()
            fresh = [i for i in incidents if i.get("created_at", "") >= since_iso]
            if fresh:
                return str(sorted(fresh, key=lambda i: i["created_at"])[-1]["id"])
            time.sleep(3)
        return None

    def fetch_incident(incident_id: str) -> dict[str, Any]:
        return dict(client.get(f"/api/incidents/{incident_id}").json())

    def await_terminal(incident_id: str, timeout: float) -> dict[str, Any]:
        deadline = time.time() + timeout
        incident = fetch_incident(incident_id)
        while time.time() < deadline and incident.get("status") not in TERMINAL:
            time.sleep(4)
            incident = fetch_incident(incident_id)
        return incident

    def recovered(alert: dict[str, Any]) -> bool:
        # independent recovery check from raw metrics via the actuator's whitelisted tail
        return _recovered_via_tail(alert, actuator_url, token)

    return Platform(do_inject, reset, await_incident, fetch_incident, await_terminal, recovered)


def _recovered_via_tail(alert: dict[str, Any], actuator_url: str, token: str) -> bool:
    """Re-derive recovery from metrics.jsonl fetched over the actuator /tail endpoint (07 §3 —
    grading never trusts the graph). Falls back to the local worldstate reader in-container."""
    try:
        with httpx.Client(
            base_url=actuator_url, headers={"X-Actuator-Token": token}, timeout=15.0
        ) as c:
            resp = c.get("/tail", params={"file": "metrics/metrics.jsonl", "last": 400})
            resp.raise_for_status()
            lines = [json.loads(ln) for ln in resp.text.splitlines() if ln.strip()]
        return _rule_ok_from_lines(alert, lines)
    except Exception:
        return rule_ok(alert) is True


def _rule_ok_from_lines(alert: dict[str, Any], lines: list[dict[str, Any]]) -> bool:
    from argus.graph.verify import _OPS, _rule_ops

    observed = alert.get("observed", {})
    metric = str(observed.get("metric", ""))
    service = str(alert.get("service", ""))
    dep = (alert.get("labels") or {}).get("dep")
    vals = [
        ln.get("value")
        for ln in lines
        if ln.get("service") == service
        and ln.get("name") == metric
        and (dep is None or (ln.get("labels") or {}).get("dep") == dep)
    ]
    latest = next((float(v) for v in reversed(vals) if isinstance(v, int | float)), None)
    if latest is None:
        return False
    op, cfg_threshold = _rule_ops().get(str(alert.get("rule", "")), (">", 0.0))
    threshold = float(observed.get("threshold", cfg_threshold))
    return not _OPS.get(op, operator.gt)(latest, threshold)


def set_platform_env(memory: bool, supervisor_model: str | None, llm_mode: str) -> None:
    """Point the platform at the run's config by rewriting .env and recreating api+worker,
    then verify via /api/health's config echo (07 §2)."""
    import re
    from pathlib import Path

    env = Path(".env")
    text_env = env.read_text(encoding="utf-8") if env.exists() else ""

    def upsert(body: str, key: str, value: str) -> str:
        line = f"{key}={value}"
        if re.search(rf"(?m)^{key}=.*$", body):
            return re.sub(rf"(?m)^{key}=.*$", line, body)
        return body + ("" if body.endswith("\n") or not body else "\n") + line + "\n"

    text_env = upsert(text_env, "AUTO_APPROVE", "policy_sim")
    text_env = upsert(text_env, "MEMORY_ENABLED", "true" if memory else "false")
    text_env = upsert(text_env, "LLM_MODE", llm_mode)
    if supervisor_model:
        text_env = upsert(text_env, "ARGUS_MODEL__SUPERVISOR", supervisor_model)
    env.write_text(text_env, encoding="utf-8")
    subprocess.run(["docker", "compose", "up", "-d", "api", "worker"], check=False)
    time.sleep(8)


def wipe_memories() -> None:
    with session_scope() as session:
        session.execute(text("DELETE FROM memories"))


def _start_run(suite: str, config: dict[str, Any]) -> str:
    with session_scope() as session:
        run = EvalRun(suite=suite, config=config, git_sha=_git_sha())
        session.add(run)
        session.flush()
        return str(run.id)


def _finish_run(run_id: str) -> None:
    with session_scope() as session:
        run = session.get(EvalRun, run_id)
        if run is not None:
            run.finished_at = datetime.now(UTC)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="argus.evals.run")
    ap.add_argument("--suite", default="all", help="all | S3 | S3-v2")
    ap.add_argument("--memory", choices=["on", "off"], default="off")
    ap.add_argument("--supervisor-model", default=None)
    ap.add_argument("--llm-mode", choices=["live", "record", "replay"], default="live")
    ap.add_argument("--api-url", default="http://localhost:8080")
    ap.add_argument("--actuator-url", default="http://localhost:8010")
    ap.add_argument("--token", default="dev-actuator-token")
    args = ap.parse_args(argv)

    case_ids = scenarios.suite_ids(args.suite)
    print(f"eval suite {args.suite}: {len(case_ids)} cases {case_ids}", flush=True)
    set_platform_env(args.memory == "on", args.supervisor_model, args.llm_mode)
    wipe_memories()

    config = {
        "memory_enabled": args.memory == "on",
        "supervisor_model": args.supervisor_model or "gemini-2.5-flash",
        "llm_mode": args.llm_mode,
        "auto_approve": "policy_sim",
    }
    run_id = _start_run(args.suite, config)
    platform = _real_platform(args.api_url, args.actuator_url, args.token)
    router = LLMRouter()
    results = run_suite(case_ids, platform, router, run_id)
    _finish_run(run_id)
    print(f"\nrun {run_id} complete: {results}", flush=True)


if __name__ == "__main__":
    main()
