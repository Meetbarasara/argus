"""Eval runner (07 §2), host-side CLI. Sequential case loop over the live platform:
set platform env (AUTO_APPROVE=policy_sim, MEMORY_ENABLED, optional supervisor override) →
verify via /api/health → per case: reset world → memory hygiene → inject → await alert→incident
→ await terminal → grade (07 §3) → persist eval_case. Cases run sequentially (free-tier RPM).

The case loop takes its platform interactions as a ``Platform`` bundle of callables so the
mechanics are unit-testable without docker or LLM quota; ``main`` wires the real ones."""

from __future__ import annotations

import argparse
import io
import operator
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select, text

from argus.db.models import EvalCase, EvalRun
from argus.db.session import session_scope
from argus.evals import scenarios
from argus.evals.grade import CaseGrade, grade_case
from argus.evals.report import memory_lift_table
from argus.graph.verify import rule_ok
from argus.llm.router import LLMRouter

TERMINAL = {"RESOLVED", "TAKEN_OVER", "FAILED", "CLOSED"}
PAYMENTSVC_URL = "http://localhost:8002"  # 03 §6 — S2 injects chaos here; must be healthy first


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
    case_ids: list[str],
    platform: Platform,
    router: LLMRouter,
    run_id: str,
    skip: set[str] | None = None,
) -> dict[str, str]:
    skip = skip or set()
    results: dict[str, str] = {}
    for i, case_id in enumerate(case_ids, 1):
        if case_id in skip:
            print(f"[{i}/{len(case_ids)}] {case_id} … already graded, skipping", flush=True)
            continue
        print(f"[{i}/{len(case_ids)}] {case_id} …", flush=True)
        try:
            results[case_id] = run_case(case_id, platform, router, run_id)
        except Exception as exc:  # a broken case must not sink the whole suite
            print(f"    {case_id} errored: {exc}", flush=True)
            _persist_case(run_id, case_id, None, None)
            results[case_id] = f"ERROR({exc})"
        print(f"    → {results[case_id]}", flush=True)
    return results


def _graded_case_ids(run_id: str) -> set[str]:
    """scenario_ids already persisted for a run — ``--resume`` skips them."""
    with session_scope() as session:
        rows = session.scalars(select(EvalCase.scenario_id).where(EvalCase.run_id == run_id)).all()
    return {str(r) for r in rows}


def _eval_case_dicts(run_id: str) -> list[dict[str, Any]]:
    """Minimal case rows for the memory-lift table (07 §4)."""
    with session_scope() as session:
        cases = session.scalars(select(EvalCase).where(EvalCase.run_id == run_id)).all()
        return [
            {
                "scenario_id": c.scenario_id,
                "llm_calls": c.llm_calls,
                "mttr_seconds": c.mttr_seconds,
                "rca_correct": c.rca_correct,
            }
            for c in cases
        ]


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

    def _clear_nonterminal_incidents() -> None:
        """Eval hygiene: the API dedupes a new alert into any NON-terminal incident for the same
        service (03 §4 service-level dedupe). An incident the previous case left mid-flight (its
        budget expired) would therefore swallow this case's alert and the runner would observe no
        new incident → a spurious FAIL(no-incident). Close them before injecting."""
        with session_scope() as session:
            rows = session.execute(
                text(
                    "UPDATE incidents SET status='FAILED', updated_at=now(), "
                    "status_reason='cleared by eval reset (03 §4 dedupe hygiene)' "
                    "WHERE status NOT IN ('RESOLVED','TAKEN_OVER','FAILED','CLOSED') RETURNING id"
                )
            ).fetchall()
        if rows:
            print(f"    cleared {len(rows)} lingering non-terminal incident(s)", flush=True)

    def _reset_worldstate() -> None:
        # actuator admin op: rewrite config/{shopapi,paymentsvc}.json to baseline, clear
        # paymentsvc's in-memory chaos, truncate deploy/metric/alert history (07 §2 clean slate)
        try:
            with httpx.Client(
                base_url=actuator_url, headers={"X-Actuator-Token": token}, timeout=15.0
            ) as c:
                c.post("/admin/reset_worldstate").raise_for_status()
        except Exception as exc:
            print(f"    reset_worldstate failed (continuing): {exc}", flush=True)

    def _health_ok(base: str, path: str) -> bool:
        try:
            with httpx.Client(base_url=base, timeout=5.0) as c:
                return c.get(path).status_code == 200
        except Exception:
            return False

    def _await_ready(timeout: float = 90.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if (
                _health_ok(api_url, "/api/health")
                and _health_ok(actuator_url, "/health")
                and _health_ok(PAYMENTSVC_URL, "/health")
            ):
                break
            time.sleep(2)
        time.sleep(10)  # warmup: let shopapi rebuild its pool + poller take a clean baseline

    def reset() -> None:
        # 07 §2 clean slate, in order: close any lingering non-terminal incident (else the API
        # dedupes this case's alert into it and no new incident appears); reset worldstate to
        # baseline so a prior case's bad deploy/chaos can't leak in; restart the mutable world
        # containers — shopredis (S1 stops it), shopapi (baseline config + fresh pool), paymentsvc
        # (drops in-memory chaos and heals a wedged S2 target — a 502 on /chaos fails the case),
        # alertwatch (clears the 600s refire cooldown) — then wait for API + actuator + paymentsvc
        # health before injecting.
        _clear_nonterminal_incidents()
        _reset_worldstate()
        subprocess.run(
            ["docker", "compose", "restart", "shopredis", "shopapi", "paymentsvc", "alertwatch"],
            check=False,
        )
        _await_ready()

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
        # 07 §1/§3: independent recovery check from raw metrics via the actuator /tail. Poll up to
        # 120s ("breached rule returns below threshold ≤120s after remediation") — a rolling-window
        # metric (err_rate_60s) or a dependency re-check lags the fix, so a single read right at the
        # terminal transition false-negatives a case that does recover moments later.
        deadline = time.time() + 120.0
        while True:
            if _recovered_via_tail(alert, actuator_url, token):
                return True
            if time.time() >= deadline:
                return False
            time.sleep(8)

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
            # /tail returns {"file":..., "lines":[{metric}, ...]} — the metric dicts, not raw JSONL
            lines = [ln for ln in resp.json().get("lines", []) if isinstance(ln, dict)]
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


def set_platform_env(
    memory: bool,
    supervisor_model: str | None,
    llm_mode: str,
    api_url: str = "http://localhost:8080",
) -> None:
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
    _await_config_echo(api_url, memory, llm_mode)


def _await_config_echo(api_url: str, memory: bool, llm_mode: str, timeout: float = 90.0) -> None:
    """Wait until /api/health echoes the run's active config (07 §2) — AUTO_APPROVE=policy_sim,
    the right memory flag and llm_mode — so a case never runs against stale env."""
    deadline = time.time() + timeout
    last: dict[str, Any] = {}
    while time.time() < deadline:
        try:
            last = dict(httpx.get(f"{api_url}/api/health", timeout=5.0).json().get("config", {}))
            if (
                last.get("auto_approve") == "policy_sim"
                and bool(last.get("memory_enabled")) == memory
                and last.get("llm_mode") == llm_mode
            ):
                print(f"    health echo confirms {last}", flush=True)
                return
        except Exception:
            pass
        time.sleep(2)
    print(f"    warning: health echo unconfirmed in {timeout:.0f}s (last={last})", flush=True)


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


def _config(
    memory: bool, supervisor_model: str | None, llm_mode: str, **extra: Any
) -> dict[str, Any]:
    cfg: dict[str, Any] = {
        "memory_enabled": memory,
        "supervisor_model": supervisor_model or "gemini-2.5-flash",
        "llm_mode": llm_mode,
        "auto_approve": "policy_sim",
    }
    cfg.update(extra)
    return cfg


def _memory_pairs(suite: str) -> list[tuple[str, str]]:
    """(v1 seed, v2 measure) pairs for each scenario present in ``suite`` (07 §4)."""
    all_ids = scenarios.suite_ids(suite)
    prefixes = sorted({cid.split("-", 1)[0] for cid in all_ids})
    return [
        (f"{p}-v1", f"{p}-v2") for p in prefixes if f"{p}-v1" in all_ids and f"{p}-v2" in all_ids
    ]


def run_memory_ablation(
    suite: str,
    llm_mode: str,
    supervisor_model: str | None,
    api_url: str,
    actuator_url: str,
    token: str,
    router: LLMRouter,
) -> tuple[str, str]:
    """07 §4 memory-lift protocol: per scenario, v1 seeds → v2 measures; run once with memory ON
    and once OFF, each condition wiping `memories` first so they are independent. Returns the two
    run ids (on, off)."""
    pairs = _memory_pairs(suite)
    run_ids: dict[str, str] = {}
    for condition, memory in (("on", True), ("off", False)):
        print(f"\n=== memory {condition.upper()} · {len(pairs)} scenario(s) ===", flush=True)
        set_platform_env(memory, supervisor_model, llm_mode, api_url)
        wipe_memories()
        cfg = _config(memory, supervisor_model, llm_mode, ablation="memory", condition=condition)
        run_id = _start_run(f"memory-{condition}", cfg)
        platform = _real_platform(api_url, actuator_url, token)
        for seed_id, measure_id in pairs:
            for cid in (seed_id, measure_id):
                print(f"[{condition}] {cid} …", flush=True)
                try:
                    print(f"    → {run_case(cid, platform, router, run_id)}", flush=True)
                except Exception as exc:  # a broken case must not sink the condition
                    print(f"    {cid} errored: {exc}", flush=True)
                    _persist_case(run_id, cid, None, None)
        _finish_run(run_id)
        run_ids[condition] = run_id
    return run_ids["on"], run_ids["off"]


def _resume_run(
    run_id: str, api_url: str, actuator_url: str, token: str, router: LLMRouter
) -> None:
    """Continue an interrupted run, skipping already-graded cases (deliverable). Re-points the
    platform at the run's original config; does NOT wipe memories (preserves seeded state)."""
    with session_scope() as session:
        run = session.get(EvalRun, run_id)
        if run is None:
            raise SystemExit(f"no eval_run {run_id}")
        cfg = dict(run.config or {})
        suite = run.suite
    sup = cfg.get("supervisor_model")
    set_platform_env(
        bool(cfg.get("memory_enabled")),
        None if sup in (None, "gemini-2.5-flash") else str(sup),
        str(cfg.get("llm_mode", "live")),
        api_url,
    )
    if cfg.get("ablation") == "memory":
        case_ids = [cid for pair in _memory_pairs("all") for cid in pair]
    else:
        case_ids = scenarios.suite_ids(suite)
    skip = _graded_case_ids(run_id)
    print(f"resume {run_id}: {len(skip)} done, {len(case_ids) - len(skip)} to go", flush=True)
    platform = _real_platform(api_url, actuator_url, token)
    results = run_suite(case_ids, platform, router, run_id, skip)
    _finish_run(run_id)
    print(f"\nresumed run {run_id}: {results}", flush=True)


def main(argv: list[str] | None = None) -> None:
    # Windows stdout defaults to cp1252, which can't encode the arrows/Δ/≥ we print (and the
    # memory-lift table) → UnicodeEncodeError mid-run. Force UTF-8 so a run never dies on output.
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="argus.evals.run")
    ap.add_argument("--suite", default="all", help="all | S3 | S3-v2")
    ap.add_argument("--memory", choices=["on", "off"], default="off")
    ap.add_argument("--supervisor-model", default=None)
    ap.add_argument("--llm-mode", choices=["live", "record", "replay"], default="live")
    ap.add_argument(
        "--repeat-for-memory",
        action="store_true",
        help="07 §4 memory-lift ablation: per scenario v1 seeds→v2 measures, memory ON vs OFF",
    )
    ap.add_argument(
        "--resume", default=None, metavar="RUN_ID", help="continue a run, skipping graded cases"
    )
    ap.add_argument("--api-url", default="http://localhost:8080")
    ap.add_argument("--actuator-url", default="http://localhost:8010")
    ap.add_argument("--token", default="dev-actuator-token")
    args = ap.parse_args(argv)
    router = LLMRouter()

    if args.repeat_for_memory:
        on_id, off_id = run_memory_ablation(
            args.suite,
            args.llm_mode,
            args.supervisor_model,
            args.api_url,
            args.actuator_url,
            args.token,
            router,
        )
        print(
            "\n" + memory_lift_table(_eval_case_dicts(on_id), _eval_case_dicts(off_id)), flush=True
        )
        print(f"memory ablation runs: ON={on_id} OFF={off_id}", flush=True)
        return

    if args.resume:
        _resume_run(args.resume, args.api_url, args.actuator_url, args.token, router)
        return

    case_ids = scenarios.suite_ids(args.suite)
    print(f"eval suite {args.suite}: {len(case_ids)} cases {case_ids}", flush=True)
    set_platform_env(args.memory == "on", args.supervisor_model, args.llm_mode, args.api_url)
    wipe_memories()
    config = _config(args.memory == "on", args.supervisor_model, args.llm_mode)
    run_id = _start_run(args.suite, config)
    platform = _real_platform(args.api_url, args.actuator_url, args.token)
    results = run_suite(case_ids, platform, router, run_id)
    _finish_run(run_id)
    print(f"\nrun {run_id} complete: {results}", flush=True)


if __name__ == "__main__":
    main()
