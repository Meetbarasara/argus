# 07 — Evaluation Plan

The evaluation harness is the project's interview centerpiece: it turns "I built a
multi-agent system" into "here is how well it works, measured, with ablations."
This doc defines metrics, methodology, and the report format. M11 implements it.

## What we claim, and how each claim is measured

| Claim | Metric | Definition |
|---|---|---|
| Argus finds the right root cause | **RCA accuracy** | fraction of cases where the final hypothesis matches the scenario's expected root cause (judge, §3) |
| Argus proposes the right fix | **Remediation correctness** | proposed action tool + target_service (and for rollbacks, the faulty deploy) exactly match expectation |
| The fix actually works | **Recovery rate** | breached alert rule returns below threshold ≤120s after remediation (deterministic, from metrics) |
| Argus escalates when it should — and only then | **Escalation precision / recall** | expected vs actual highest escalation level per case; precision = escalations that were warranted, recall = warranted escalations that happened |
| Argus is efficient | **MTTR, LLM calls, tokens, cost/incident** | from incidents counters |
| Memory makes it smarter | **Memory lift** | Δ in LLM calls + MTTR + RCA on repeat-fault cases, memory ON vs OFF (§4) |
| Architecture is model-agnostic | **Model comparison** | same suite, supervisor model swapped, all metrics side-by-side |

Case outcome: **PASS** = RCA ✓ ∧ remediation ✓ ∧ recovered ✓ ∧ escalation ✓;
**PARTIAL** = RCA ✓ but something downstream failed; **FAIL** otherwise.

## 1. Suite composition (15 cases)

Each scenario S1–S5 × 3 variants (defined in `evals/scenarios/*.yaml`, schema in 03 §3):

- **v1** clean: fault injected on a quiet, warmed-up world.
- **v2** decoys: 1–2 benign deploys to *other* config keys/services shortly before the
  fault (tests change-correlation precision, esp. S3–S5; for S2 the decoys make "blame
  the deploy" tempting and wrong).
- **v3** noise: shortened warmup + a benign restart in the audit log + tighter fault
  timing (tests robustness to messy evidence).

Variant parameters live in the yaml (`params:`), interpreted by the injector.
The suite is versioned with the repo — same commit, same cases.

## 2. Runner protocol (`python -m argus.evals.run`, host-side CLI)

```
--suite all | S3 | S3-v2      which cases
--memory on|off               sets MEMORY_ENABLED for the platform during the run
--supervisor-model <id>       overrides ARGUS_MODEL__SUPERVISOR
--llm-mode live|replay        replay only for infra debugging, never for reported numbers
--repeat-for-memory           §4 memory-lift protocol
```

Per case: (1) reset world — clear worldstate (via actuator admin op), restart world
profile, wait for health + warmup; (2) memory hygiene — §4; (3) inject scenario;
(4) wait for alert → incident (timeout 120s); (5) wait for terminal status (timeout =
case budget; `AUTO_APPROVE=policy_sim` is set so approvals resolve as policy dictates,
recorded with `decided_by=policy_sim`); (6) grade (§3); (7) write `eval_cases` row.
Cases run **sequentially** — free-tier RPM makes parallel cases pointless and flaky.

Budget estimate: ~20–30 LLM calls/case ⇒ ~400 calls/suite ⇒ fits daily free quotas
(Gemini ≈1.5k RPD + Groq ≈1k RPD) with RPM pacing handled by the router. A full suite
takes roughly 60–90 min wall clock. Plan eval days accordingly; never trim pacing to
rush a run.

## 3. Grading

Deterministic first (no judge needed):
- remediation: compare executed/proposed action vs `expected.remediation`.
- recovery: from metrics.jsonl re-evaluation (the runner checks independently of the
  graph's own verify_recovery — no self-grading).
- escalation: compare incident.escalation_level vs `expected.escalation_level`.

**RCA judge** (role `judge`, structured `JudgeVerdict`): the judge sees the expected
label and the hypothesis and answers "same root cause?" — semantic match, not string
match. Fallback: if the judge call fails, keyword heuristic (`expected.
root_cause_keywords` all present, case-insensitive) with `rca_judge_reason =
"keyword-fallback"`. Judge prompt pins the rubric:

```text
You grade an incident diagnosis. Expected root cause: {label}. The system's
diagnosis: {hypothesis.root_cause} (affected: {services}).
match=true only if the diagnosis identifies the same causal mechanism and the same
service — a correct symptom description with the wrong cause is false; extra correct
detail is fine. Return JSON {match, reason}.
```

Judge calls are logged to `llm_calls` (incident_id null, role judge) — the grading
itself is auditable.

## 4. Ablations (the two headline numbers)

**Memory lift** (`--repeat-for-memory`): for each scenario, run v1 to seed the memory,
then run v2 and measure. Condition A: memory ON. Condition B: memory OFF
(`MEMORY_ENABLED=false`, recall returns empty). Before each condition the platform's
`memories` table is wiped (runner truncates it) so conditions are independent.
Report per-scenario and aggregate: Δ LLM calls, Δ MTTR, Δ RCA on the measured (second)
runs. Target: **≥20% fewer LLM calls** on repeats with memory ON.

**Model comparison**: full suite with default supervisor (Gemini Flash) vs
`--supervisor-model groq:llama-3.3-70b-versatile` (and optionally a third). Same
seeds, memory OFF for both (isolates the model variable). Report all §Claims metrics
side by side.

## 5. Reporting

`python -m argus.evals.report [run_id...]` regenerates **EVALUATION.md** (repo root):

```markdown
# Argus Evaluation Report
run <id> · <date> · commit <sha> · supervisor=<model> · memory=<on/off> · N=15
## Headline
RCA accuracy: 13/15 (87%) · Remediation: 13/15 · Recovery: 12/13 attempted ·
Escalation precision 100% / recall 92% · Median MTTR 143s · Median cost $0.011 (list)
## Per-scenario table   (S# × v# grid: outcome, rca, remediation, recovered, escalation, calls, mttr)
## Failures             (per failed case: what the graph concluded, judge reason, trace link)
## Ablation: memory lift    (table A vs B + delta)
## Ablation: supervisor model    (side-by-side metric table)
## Method note              (suite definition, judge rubric, AUTO_APPROVE=policy_sim disclosure)
```

The same numbers power the UI Dashboard eval panel (03 §4 endpoints).

## 6. Targets (aspirational, not gates — report honestly whatever they are)

RCA ≥ 80% · remediation ≥ 80% · recovery ≥ 90% of correctly-remediated cases ·
escalation precision ≥ 90% · memory lift ≥ 20% fewer LLM calls on repeats.
A miss is a *finding*, not a failure: analyze it in EVALUATION.md §Failures (that
analysis is itself interview material). Numbers are never inflated by re-running
until lucky; report the run you planned to report.

## 7. Interview talking points this doc buys

- "I evaluated on 15 seeded-fault cases with deterministic ground truth, so grading is
  mostly non-LLM; the only judged part is root-cause phrasing, with an auditable rubric."
- "The runner grades recovery from raw metrics independently — the system never grades
  its own homework."
- "Memory is worth X% fewer LLM calls and Y s MTTR on repeat incidents, measured by
  ablation, not vibes."
- "Swapping the supervisor model is one flag; here's the quality/cost table."
- "Escalation has precision *and* recall — I measure both over-asking and under-asking."
