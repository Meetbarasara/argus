# M11 — Evaluation Harness & Ablations

**Objective:** implement 07 in full: the 15-case suite, the host-side runner, grading
(deterministic + judge), persistence, the EVALUATION.md report generator, and the two
ablations (memory lift, model comparison). Ends with real numbers from real runs
committed to the repo. This milestone produces the project's headline claims — run it
honestly (07 §6).

**Read first:** 07 (entire — it is the spec), 03 §1 (eval tables), 03 §3 (scenario
yaml), 08 #23, #26–#27.
**Prerequisites:** M10 green; API keys; a free-tier-quota-friendly day (2 full suites
≈ 800–1000 calls).

## Deliverables

| Path | Responsibility |
|---|---|
| `evals/scenarios/S{1..5}-v{1..3}.yaml` | 15 cases per 07 §1 + 03 §3 schema; v2/v3 params (decoys, warmup, benign restart) interpreted by inject.py (extend it if a param is missing — that's a demoworld change, keep it tiny) |
| `src/argus/evals/run.py` | CLI per 07 §2: sequential case loop (reset → memory hygiene → inject → await alert → await terminal → grade → persist); flags `--suite --memory --supervisor-model --llm-mode --repeat-for-memory`; sets platform env (AUTO_APPROVE=policy_sim, MEMORY_ENABLED, model override) by restarting api+worker with env overrides (compose `--env-file` overlay or `-e` recreate) and verifying via /api/health echo of active config; per-case progress output; resumable (`--resume run_id` skips graded cases) |
| `src/argus/evals/grade.py` | deterministic checks (remediation/recovery/escalation — recovery re-derived from metrics.jsonl independently, 07 §3) + judge call (JudgeVerdict) with keyword fallback; outcome PASS/PARTIAL/FAIL |
| `src/argus/evals/report.py` | regenerate EVALUATION.md per 07 §5 from eval_runs/eval_cases; also `--compare runA runB` ablation tables |
| `api/routers/evals.py` | replace 501s: GET runs / run detail (03 §4) — UI eval panel comes alive |
| tests | unit: grading matrix (synthetic incidents × expectations → outcome), keyword fallback, report rendering from fixture rows; integration: runner smoke on `--suite S1 --llm-mode replay` against recorded fixtures (no quota) proving the loop mechanics |

## Steps

1. Scenario yamls + injector param support; dry-run each variant once manually
   (evidence sanity — decoys visible, S2-v2 still deploy-free for the *fault*).
2. grade.py + unit matrix; report.py + fixture test.
3. run.py mechanics with replay smoke (no live quota burned on plumbing bugs).
4. **Run A: full live suite, memory OFF** (baseline; ~60–90 min, 08 #26).
5. **Run B: `--repeat-for-memory` memory ON vs OFF** (07 §4 protocol).
6. Optional if quota allows today, else next day: **Run C: `--supervisor-model
   groq:llama-3.3-70b-versatile`** for the model table.
7. `report` → commit EVALUATION.md; analyze failures in its §Failures honestly.
8. Evals API + UI panel check.

## Acceptance criteria

- [ ] Runner is deterministic in mechanics: replay smoke passes twice with identical
      grading; live variance comes only from LLMs.
- [ ] Grading never trusts the graph's self-assessment (recovery from raw metrics;
      escalation from approvals rows; remediation from actuator history).
- [ ] EVALUATION.md committed with ≥2 runs incl. memory ablation; method note +
      AUTO_APPROVE disclosure present; failures analyzed, not hidden.
- [ ] eval_cases link to their incidents; every case's trace openable in the UI.
- [ ] Judge calls logged (llm_calls role=judge) — auditable grading.

## Verification gate

```
$ uv run poe verify && uv run pytest tests/unit/test_grading.py -q     → green
$ uv run python -m argus.evals.run --suite S1 --llm-mode replay        → completes, writes eval_run
$ uv run python -m argus.evals.run --suite all --memory off            → 15/15 cases graded (live)
$ uv run python -m argus.evals.run --repeat-for-memory                 → lift table printed
$ uv run python -m argus.evals.report                                  → EVALUATION.md regenerated
$ curl -s localhost:8080/api/evals/runs | jq 'length'                  → ≥2 ; UI dashboard eval panel populated
$ uv run poe verify-all                                                 → green (regression checkpoint)
```

**Gotchas:** 08 #23 (memory hygiene between conditions), #26 (wall clock), #27 (quota
discipline — if daily caps block Run C, log it and finish next day rather than degrading pacing).
**Out of scope:** new scenarios beyond the 15; UI-triggered runs.
