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


# --- ablation renderers (pure; 07 §4/§5) ---------------------------------------------
def _measured(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The repeat (v2) cases — the ones the memory ablation actually measures (07 §4)."""
    return [c for c in cases if str(c.get("scenario_id", "")).endswith("-v2")]


def memory_lift_table(cases_on: list[dict[str, Any]], cases_off: list[dict[str, Any]]) -> str:
    """07 §4 memory lift: compare the repeat (v2) cases, memory ON vs OFF, on LLM calls / MTTR /
    RCA. Each condition wiped `memories` then re-seeded with its v1 run, so they are independent.
    Fewer LLM calls on the ON repeat = memory paying off. Pure → unit-tested from fixtures."""
    on = {str(c["scenario_id"]): c for c in _measured(cases_on)}
    off = {str(c["scenario_id"]): c for c in _measured(cases_off)}
    ids = sorted(set(on) & set(off))
    tick = lambda b: "✅" if b else "❌"  # noqa: E731
    out = [
        "## Ablation: memory lift",
        "",
        "Repeat-fault (v2) cases, memory ON vs OFF — each condition wipes `memories` then "
        "re-seeds via the v1 run (07 §4). Δ = ON−OFF, so a negative Δ means memory cut calls.",
        "",
        "| case | calls ON | calls OFF | Δ calls | MTTR ON | MTTR OFF | RCA ON | RCA OFF |",
        "|---|---|---|---|---|---|---|---|",
    ]
    tot_on = tot_off = 0
    for sid in ids:
        a, b = on[sid], off[sid]
        ca, cb = int(a.get("llm_calls") or 0), int(b.get("llm_calls") or 0)
        tot_on += ca
        tot_off += cb
        ma, mb = a.get("mttr_seconds"), b.get("mttr_seconds")
        out.append(
            f"| {sid} | {ca} | {cb} | {ca - cb:+d} | "
            f"{f'{ma}s' if ma is not None else '—'} | {f'{mb}s' if mb is not None else '—'} | "
            f"{tick(a.get('rca_correct'))} | {tick(b.get('rca_correct'))} |"
        )
    if not ids:
        out.append("| _no paired v2 cases_ |  |  |  |  |  |  |  |")
    out.append("")
    if tot_off:
        pct = round(100 * (tot_off - tot_on) / tot_off)
        out.append(
            f"**Aggregate:** {tot_on} vs {tot_off} LLM calls across {len(ids)} repeat case(s) — "
            f"**{pct}% fewer with memory ON** (target ≥20%)."
        )
    else:
        out.append("**Aggregate:** insufficient data (no OFF-condition calls recorded).")
    out.append("")
    return "\n".join(out)


def model_comparison_table(runs: list[tuple[str, dict[str, Any], list[dict[str, Any]]]]) -> str:
    """07 §5 supervisor-model comparison: same suite, memory OFF, supervisor swapped — headline
    metrics side by side. ``runs`` = [(supervisor_model, config, cases)]. Pure."""
    out = [
        "## Ablation: supervisor model",
        "",
        "Same suite, memory OFF, supervisor model swapped (one flag) — the architecture is "
        "model-agnostic. List-price cost.",
        "",
        "| supervisor | RCA | remediation | recovery | esc P/R | median calls | median MTTR | "
        "median cost |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for model, _cfg, cases in runs:
        s = summarize(cases)
        mttr = f"{s['median_mttr']}s" if s["median_mttr"] is not None else "—"
        out.append(
            f"| {model} | {s['rca']}/{s['n']} | {s['remediation']}/{s['n']} | "
            f"{s['recovered']}/{s['remediated']} | "
            f"{round(100 * s['esc_precision'])}%/{round(100 * s['esc_recall'])}% | "
            f"{s['median_calls']} | {mttr} | ${s['median_cost']:.4f} |"
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


def _all_runs(session: Any) -> list[EvalRun]:
    return list(session.scalars(select(EvalRun).order_by(EvalRun.started_at.desc())).all())


def _baseline_run(runs: list[EvalRun]) -> EvalRun | None:
    """The headline run: the latest full ``--suite all`` non-ablation run (the memory-off
    baseline); fall back to the latest non-ablation run, then to the latest run overall."""
    non_abl = [r for r in runs if not (r.config or {}).get("ablation")]
    full = [r for r in non_abl if r.suite == "all"]
    for candidate in (full, non_abl, runs):
        if candidate:
            return candidate[0]
    return None


def _ablation_pair(runs: list[EvalRun], name: str) -> tuple[EvalRun | None, EvalRun | None]:
    def pick(cond: str) -> EvalRun | None:
        return next(
            (
                r
                for r in runs
                if (r.config or {}).get("ablation") == name
                and (r.config or {}).get("condition") == cond
            ),
            None,
        )

    return pick("on"), pick("off")


def _model_runs(runs: list[EvalRun], baseline: EvalRun | None) -> list[EvalRun]:
    """Baseline + any other full memory-off run whose supervisor differs → model comparison."""
    if baseline is None:
        return []
    base_model = (baseline.config or {}).get("supervisor_model")
    picked = [baseline]
    for r in runs:
        cfg = r.config or {}
        if (
            cfg.get("ablation")
            or r.suite != "all"
            or cfg.get("memory_enabled")
            or r.id == baseline.id
        ):
            continue
        if cfg.get("supervisor_model") != base_model:
            picked.append(r)
    return picked if len(picked) > 1 else []


def write_report(run_id: str | None = None, path: str = REPORT_PATH) -> str | None:
    """Regenerate EVALUATION.md (07 §5): the baseline run's headline/per-case/failures/method,
    then auto-embed the memory-lift ablation (when the ON/OFF pair is in the DB) and the
    supervisor-model comparison (when a model-swap run is present)."""
    with session_scope() as session:
        runs = _all_runs(session)
        if not runs:
            return None
        base = session.get(EvalRun, run_id) if run_id is not None else _baseline_run(runs)
        if base is None:
            return None
        parts = [render_report(_run_dict(base), _case_dicts(session, base.id))]
        m_on, m_off = _ablation_pair(runs, "memory")
        if m_on is not None and m_off is not None:
            parts.append(
                memory_lift_table(_case_dicts(session, m_on.id), _case_dicts(session, m_off.id))
            )
        model_runs = _model_runs(runs, base)
        if model_runs:
            parts.append(
                model_comparison_table(
                    [
                        (
                            (r.config or {}).get("supervisor_model", "gemini-2.5-flash"),
                            r.config or {},
                            _case_dicts(session, r.id),
                        )
                        for r in model_runs
                    ]
                )
            )
        markdown = "\n".join(parts)
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
