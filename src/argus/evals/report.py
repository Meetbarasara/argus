"""EVALUATION.md generator (07 §5). ``render_report``/``summarize`` are pure (test from
fixture rows); ``write_report`` pulls eval_runs/eval_cases from the DB and writes the file;
``--compare A B`` prints the ablation delta table (memory lift / model comparison)."""

from __future__ import annotations

import argparse
from statistics import median
from typing import Any

from sqlalchemy import select

from argus.db.models import EvalCase, EvalRun
from argus.db.session import session_scope

HUMAN_LEVELS = {"APPROVE_ACTION", "APPROVE_PLAN", "TAKE_OVER"}
REPORT_PATH = "EVALUATION.md"


def _pct(numer: int, denom: int) -> str:
    return f"{round(100 * numer / denom)}%" if denom else "—"


def summarize(cases: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(cases)
    rca = sum(1 for c in cases if c.get("rca_correct"))
    rem = sum(1 for c in cases if c.get("remediation_correct"))
    remediated = [c for c in cases if c.get("remediation_correct")]
    recovered = sum(1 for c in remediated if c.get("recovered"))
    act_esc = [c for c in cases if c.get("escalation_actual") in HUMAN_LEVELS]
    exp_esc = [c for c in cases if c.get("escalation_expected") in HUMAN_LEVELS]
    tp = sum(1 for c in act_esc if c.get("escalation_expected") in HUMAN_LEVELS)
    mttrs = [c["mttr_seconds"] for c in cases if c.get("mttr_seconds") is not None]
    costs = [float(c.get("cost_usd") or 0) for c in cases]
    calls = [int(c.get("llm_calls") or 0) for c in cases]
    return {
        "n": n,
        "passes": sum(1 for c in cases if c.get("outcome") == "PASS"),
        "rca": rca,
        "remediation": rem,
        "remediated": len(remediated),
        "recovered": recovered,
        "esc_precision": tp / len(act_esc) if act_esc else 1.0,
        "esc_recall": tp / len(exp_esc) if exp_esc else 1.0,
        "median_mttr": median(mttrs) if mttrs else None,
        "median_cost": median(costs) if costs else 0.0,
        "median_calls": median(calls) if calls else 0,
    }


def render_report(run: dict[str, Any], cases: list[dict[str, Any]]) -> str:
    s = summarize(cases)
    cfg = run.get("config") or {}
    memory = "on" if cfg.get("memory_enabled", True) else "off"
    sup = cfg.get("supervisor_model", "gemini-2.5-flash")
    out: list[str] = []
    out.append("# Argus Evaluation Report")
    out.append("")
    out.append(
        f"run `{str(run.get('id', ''))[:8]}` · {str(run.get('started_at', ''))[:10]} · "
        f"commit `{str(run.get('git_sha') or '')[:8]}` · "
        f"supervisor={sup} · memory={memory} · N={s['n']}"
    )
    out.append("")
    out.append("## Headline")
    out.append(f"- **RCA accuracy:** {s['rca']}/{s['n']} ({_pct(s['rca'], s['n'])})")
    out.append(
        f"- **Remediation correct:** {s['remediation']}/{s['n']} ({_pct(s['remediation'], s['n'])})"
    )
    out.append(
        f"- **Recovery:** {s['recovered']}/{s['remediated']} of correctly-remediated "
        f"({_pct(s['recovered'], s['remediated'])})"
    )
    out.append(
        f"- **Escalation:** precision {round(100 * s['esc_precision'])}% / "
        f"recall {round(100 * s['esc_recall'])}%"
    )
    mttr = f"{s['median_mttr']}s" if s["median_mttr"] is not None else "—"
    out.append(
        f"- **Efficiency:** median MTTR {mttr} · median {s['median_calls']} LLM calls · "
        f"median cost ${s['median_cost']:.4f}"
    )
    out.append(f"- **Outcome:** {s['passes']}/{s['n']} PASS")
    out.append("")
    out.append("## Per-case")
    out.append(
        "| case | outcome | rca | remediation | recovered | escalation (exp→act) | calls | mttr |"
    )
    out.append("|---|---|---|---|---|---|---|---|")
    tick = lambda b: "✅" if b else "❌"  # noqa: E731
    for c in sorted(cases, key=lambda c: str(c.get("scenario_id"))):
        esc = (
            f"{c.get('escalation_expected')}→{c.get('escalation_actual')} "
            f"{tick(c.get('escalation_correct'))}"
        )
        mt = f"{c.get('mttr_seconds')}s" if c.get("mttr_seconds") is not None else "—"
        out.append(
            f"| {c.get('scenario_id')} | {c.get('outcome')} | {tick(c.get('rca_correct'))} | "
            f"{tick(c.get('remediation_correct'))} | {tick(c.get('recovered'))} | {esc} | "
            f"{c.get('llm_calls')} | {mt} |"
        )
    out.append("")
    failures = [c for c in cases if c.get("outcome") != "PASS"]
    out.append("## Failures")
    if not failures:
        out.append("_None — every case passed._")
    for c in failures:
        out.append(
            f"- **{c.get('scenario_id')}** ({c.get('outcome')}): diagnosis "
            f"“{str(c.get('root_cause') or '—')[:90]}” · "
            f"judge: {c.get('rca_judge_reason') or '—'} · "
            f"incident `{str(c.get('incident_id') or '')[:8]}`"
        )
    out.append("")
    out.append("## Method note")
    out.append(
        "- Suite: 15 seeded-fault cases (S1–S5 × v1 clean / v2 decoys / v3 noise), "
        "versioned in `evals/scenarios/`."
    )
    out.append(
        "- Grading is mostly deterministic: recovery re-derived from raw `metrics.jsonl` "
        "(never the graph's self-report), escalation from the incident row, remediation from "
        "the executed/proposed action. Only root-cause phrasing is judged (role=judge, "
        "auditable in `llm_calls`), with a keyword fallback."
    )
    out.append(
        "- `AUTO_APPROVE=policy_sim` during runs (approvals auto-resolve as policy dictates, "
        f"recorded `decided_by=policy_sim`). memory={memory}."
    )
    out.append("")
    return "\n".join(out)


# --- DB-backed entry points ----------------------------------------------------------
def _run_dict(run: EvalRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "started_at": run.started_at.isoformat() if run.started_at else "",
        "git_sha": run.git_sha,
        "config": run.config or {},
        "suite": run.suite,
    }


def _case_dicts(session: Any, run_id: str) -> list[dict[str, Any]]:
    cases = session.scalars(select(EvalCase).where(EvalCase.run_id == run_id)).all()
    from argus.repo import incidents as incident_repo

    rows: list[dict[str, Any]] = []
    for c in cases:
        inc = incident_repo.get_incident(session, c.incident_id) if c.incident_id else None
        rows.append(
            {
                "scenario_id": c.scenario_id,
                "incident_id": c.incident_id,
                "rca_correct": c.rca_correct,
                "rca_judge_reason": c.rca_judge_reason,
                "remediation_correct": c.remediation_correct,
                "recovered": c.recovered,
                "escalation_expected": c.escalation_expected,
                "escalation_actual": c.escalation_actual,
                "escalation_correct": c.escalation_correct,
                "llm_calls": c.llm_calls,
                "cost_usd": c.cost_usd,
                "mttr_seconds": c.mttr_seconds,
                "outcome": c.outcome,
                "root_cause": inc.root_cause if inc is not None else None,
            }
        )
    return rows


def latest_run_id(session: Any) -> str | None:
    run = session.scalars(select(EvalRun).order_by(EvalRun.started_at.desc())).first()
    return run.id if run is not None else None


def write_report(run_id: str | None = None, path: str = REPORT_PATH) -> str | None:
    with session_scope() as session:
        rid = run_id or latest_run_id(session)
        if rid is None:
            return None
        run = session.get(EvalRun, rid)
        if run is None:
            return None
        markdown = render_report(_run_dict(run), _case_dicts(session, rid))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(markdown)
    return path


def compare(run_a: str, run_b: str) -> str:
    """Ablation delta: A vs B aggregate metrics (memory on/off or model swap)."""
    with session_scope() as session:
        rows = []
        for label, rid in (("A", run_a), ("B", run_b)):
            run = session.get(EvalRun, rid)
            if run is None:
                continue
            s = summarize(_case_dicts(session, rid))
            cfg = run.config or {}
            rows.append((label, rid[:8], cfg, s))
    lines = [
        "## Ablation comparison",
        "",
        "| run | supervisor | memory | RCA | median calls | median MTTR |",
        "|---|---|---|---|---|---|",
    ]
    for label, rid, cfg, s in rows:
        mem = "on" if cfg.get("memory_enabled", True) else "off"
        mttr = f"{s['median_mttr']}s" if s["median_mttr"] is not None else "—"
        lines.append(
            f"| {label} `{rid}` | {cfg.get('supervisor_model', 'gemini-2.5-flash')} | {mem} | "
            f"{s['rca']}/{s['n']} | {s['median_calls']} | {mttr} |"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="argus.evals.report")
    ap.add_argument("run_id", nargs="?", default=None)
    ap.add_argument("--compare", nargs=2, metavar=("RUN_A", "RUN_B"))
    args = ap.parse_args(argv)
    if args.compare:
        print(compare(args.compare[0], args.compare[1]))
        return
    path = write_report(args.run_id)
    print(f"wrote {path}" if path else "no eval runs to report")


if __name__ == "__main__":
    main()
