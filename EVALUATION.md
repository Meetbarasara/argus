# Argus Evaluation Report

run `01349136` · 2026-07-19 · commit `b5592c2` · supervisor=cerebras:gpt-oss-120b · memory=off · N=15

> **Read this first — run conditions.** These are single-run, live numbers on **free-tier LLMs**
> (supervisor `cerebras:gpt-oss-120b`, specialists groq `llama-3.3-70b`, **change-analyst + reviewer
> `cerebras:zai-glm-4.7`**, judge gemini with a `cerebras → groq` fallback chain). Unlike the earlier
> 7/15 baseline, this run completed on a **stable environment with no rate-limit exhaustion**, so
> **every one of the 15 cases is a real investigation — zero `0`-call artifacts.** The number is an
> honest floor for this configuration, not a rate-limited one. How the run was assembled is documented
> in *Run conditions & caveats*.

## Headline
- **RCA accuracy:** 10/15 (67%)
- **Remediation correct:** 8/15 (53%)
- **Recovery:** 8/8 of correctly-remediated (100%)
- **Escalation:** precision 92% / recall 100%
- **Efficiency:** median MTTR 293.0s · median 16 LLM calls · median cost $0.0222 (run total $0.32)
- **Outcome:** 8/15 PASS · 2 PARTIAL · 5 FAIL

## What the run shows
- **Change-correlation gap closed on S3 (2/3, was 0/3).** In the 7/15 baseline all three S3 variants
  (a deploy repoints `shopapi`'s `payment_url` at a dead endpoint) misread the checkout-502s as a
  `paymentsvc` dependency outage and failed. Putting a stronger reasoner (`zai-glm-4.7`) on the
  **change-analyst** — the specialist responsible for correlating deploys to incidents — flips S3-v2
  and S3-v3 to full PASS (correct rollback, recovered). S3-v1 still misattributes to a transient
  network fault. This is the single biggest driver of the RCA lift (47% → **67%**).
- **It fails closed — hard.** Recovery is **8/8 (100%)**: every autonomous remediation actually healed
  the world, and escalation **recall is 100%** — it never once resolved autonomously a case that
  needed a human. On anything it can't diagnose with confidence it escalates rather than acting.
- **The new bottleneck is over-escalation, not diagnosis.** Seven cases escalate to **TAKE_OVER**
  (S1-v3, S2-v1/v2/v3, S3-v1, S4-v1/v2). Two of them — **S2-v1 and S2-v3 — diagnose the root cause
  correctly** (paymentsvc latency) but hand off to a human instead of proposing the restart, so they
  score PARTIAL rather than PASS. Improving change-correlation surfaced this second-order effect: the
  reviewer/risk-gate is conservative, and correct diagnoses don't always convert to a proposed action.
  That gap between **RCA 10/15** and **PASS 8/15** is the most useful thing this run measures.
- **Strong on cache / latency-diagnosis / feature-flag faults.** S5 sweeps **3/3** (broken feature-flag
  deploy → rollback, end-to-end), S1 passes 2/3, and S4-v3 rolls back a bad pool-size deploy cleanly.

## Per-case
| case | outcome | rca | remediation | recovered | escalation (exp→act) | calls | mttr |
|---|---|---|---|---|---|---|---|
| S1-v1 | PASS | ✅ | ✅ | ✅ | NOTIFY→NOTIFY ✅ | 9 | 73s |
| S1-v2 | PASS | ✅ | ✅ | ✅ | NOTIFY→NOTIFY ✅ | 12 | 41s |
| S1-v3 | FAIL | ❌ | ❌ | ❌ | NOTIFY→TAKE_OVER ❌ | 22 | — |
| S2-v1 | PARTIAL | ✅ | ❌ | ❌ | APPROVE_ACTION→TAKE_OVER ❌ | 12 | — |
| S2-v2 | FAIL | ❌ | ❌ | ❌ | APPROVE_ACTION→TAKE_OVER ❌ | 12 | — |
| S2-v3 | PARTIAL | ✅ | ❌ | ❌ | APPROVE_ACTION→TAKE_OVER ❌ | 17 | — |
| S3-v1 | FAIL | ❌ | ❌ | ❌ | APPROVE_ACTION→TAKE_OVER ❌ | 16 | — |
| S3-v2 | PASS | ✅ | ✅ | ✅ | APPROVE_ACTION→APPROVE_ACTION ✅ | 14 | 387s |
| S3-v3 | PASS | ✅ | ✅ | ✅ | APPROVE_ACTION→APPROVE_ACTION ✅ | 18 | 326s |
| S4-v1 | FAIL | ❌ | ❌ | ❌ | APPROVE_ACTION→TAKE_OVER ❌ | 16 | — |
| S4-v2 | FAIL | ❌ | ❌ | ❌ | APPROVE_ACTION→TAKE_OVER ❌ | 15 | — |
| S4-v3 | PASS | ✅ | ✅ | ✅ | APPROVE_ACTION→APPROVE_ACTION ✅ | 20 | 363s |
| S5-v1 | PASS | ✅ | ✅ | ✅ | APPROVE_ACTION→APPROVE_ACTION ✅ | 17 | 260s |
| S5-v2 | PASS | ✅ | ✅ | ✅ | APPROVE_ACTION→APPROVE_ACTION ✅ | 16 | 208s |
| S5-v3 | PASS | ✅ | ✅ | ✅ | APPROVE_ACTION→APPROVE_ACTION ✅ | 20 | 441s |

## Failures
Grouped by cause: **S2-v1/S2-v3 (PARTIAL)** are the *correct-diagnosis, over-escalated* cases — RCA ✅
(paymentsvc latency) but handed to a human instead of proposing the restart. **S1-v3, S2-v2, S4-v1,
S4-v2** formed no confident hypothesis before taking over (a real reasoning miss, but it fails closed).
**S3-v1** is the one surviving change-correlation miss (read the dead `payment_url` as a transient
network fault). All are full 12–22-call investigations — no artifacts. Per-case judge reasoning:

- **S1-v3** (FAIL): diagnosis “Redis dependency is unavailable for shopapi due to DNS resolution failures ("no address as” · judge: correctly identifies shopapi + Redis, but attributes unavailability to DNS resolution rather than the expected “shopredis is down” — distinct causal mechanisms. · incident `6854202f`
- **S2-v1** (PARTIAL): diagnosis “A chaos experiment injected 3000ms latency into paymentsvc, causing the shopapi dependency” · judge: correctly identifies the causal mechanism (paymentsvc latency) and affected service — RCA accepted; remediation/escalation is where it falls short. · incident `7accae8f`
- **S2-v2** (FAIL): diagnosis “no confident hypothesis formed before take-over” · judge: failed to identify the causal mechanism (paymentsvc latency spike); correct service, no cause. · incident `6911470a`
- **S2-v3** (PARTIAL): diagnosis “An operator-initiated chaos action on paymentsvc injected 3000 ms of extra latency at 16:0” · judge: correctly identifies latency in paymentsvc + affected shopapi, with correct extra detail — RCA accepted. · incident `5c91f228`
- **S3-v1** (FAIL): diagnosis “Shopapi is unable to establish TCP connections to the Paymentsvc service, resulting in con” · judge: attributes to a transient networking/socket problem, not the deploy-induced `payment_url` misconfiguration — mechanism doesn’t match. · incident `b21313be`
- **S4-v1** (FAIL): diagnosis “no confident hypothesis formed before take-over” · judge: correct service (shopapi), no causal mechanism vs the expected “deploy shrank db pool, exhausting connections”. · incident `b05544af`
- **S4-v2** (FAIL): diagnosis “no confident hypothesis formed before take-over” · judge: correct service, no identification of the db-pool exhaustion cause. · incident `028b5d0e`

## Method note
- Suite: 15 seeded-fault cases (S1–S5 × v1 clean / v2 decoys / v3 noise), versioned in `evals/scenarios/`.
- Grading is mostly deterministic: recovery re-derived from raw `metrics.jsonl` (never the graph's self-report), escalation from the incident row, remediation from the executed/proposed action. Only root-cause phrasing is judged (role=judge, auditable in `llm_calls`), with a keyword fallback.
- `AUTO_APPROVE=policy_sim` during runs (approvals auto-resolve as policy dictates, recorded `decided_by=policy_sim`). memory=off.

## Ablation: memory lift

Repeat-fault (v2) cases, memory ON vs OFF — each condition wipes `memories` then re-seeds via the v1 run (07 §4). Δ = ON−OFF, so a negative Δ means memory cut calls. (Measured separately from the headline run, on the same supervisor.)

| case | calls ON | calls OFF | Δ calls | MTTR ON | MTTR OFF | RCA ON | RCA OFF |
|---|---|---|---|---|---|---|---|
| S1-v2 | 15 | 12 | +3 | 370s | 175s | ✅ | ✅ |

**Aggregate:** 15 vs 12 LLM calls across 1 repeat case — no lift on this pairing.

**Interpretation (the sign is negative, and that's expected here).** The repeat used *more* calls with
memory on (15 vs 12), not the ≥20% target. Both conditions resolved correctly (RCA ✅/✅) and the repeat
**did recall and inject the memory** (`memory_used=True`), so the recall path works — but the *fast-path
shortcut* (skip investigation when recall similarity > 0.92 and the source incident RESOLVED) did **not**
engage. The reason is structural: the ablation seeds on **v1 (clean redis-down)** and measures on **v2
(redis-down + 2 decoy deploys)**, whose fingerprint falls under the 0.92 threshold — so memory acted as
prompt *context*, not a shortcut, and one stochastic case swung +3. The controlled **same-fault** lift is
established at M07 (identical S1 repeat: **13 → 6 LLM calls, ~54% fewer**, fast-path firing). Net: memory
recall is wired and working; the fast-path payoff appears on near-identical repeats, not the decoy-shifted
v2 probe, and one case is too small to claim a number either way.

## Ablation: supervisor model

The architecture is model-agnostic — swapping the supervisor is a single flag (`--supervisor-model`,
echoed to `ARGUS_MODEL__SUPERVISOR`), and this run used `cerebras:gpt-oss-120b`. A side-by-side
**cerebras vs gemini** table is deliberately *omitted*: the only gemini `--suite all` runs on hand are
quota-degraded (median **0–6** LLM calls — Gemini's daily cap was exhausted before the graph could
investigate). Publishing that as a "model comparison" would measure Gemini's free-tier quota, not the
model. A fair comparison needs a supervisor with sustained capacity (paid tier or fresh daily allowance)
over the full 15-case suite; the harness emits the table automatically
(`report.py::model_comparison_table`) once such a run exists in the DB.

## Run conditions & caveats

- **Clean environment — no rate-limit exhaustion.** This run executed on a freshly-restarted Docker
  engine with all world services healthy, so per-case fault injection and investigation ran without the
  container-churn / daily-cap effects that produced `0`-call artifacts in the 7/15 baseline. **All 15
  cases are real investigations (12–22 LLM calls each).**
- **How the run was assembled (honest note).** Two concurrent launches earlier collided on one world;
  this headline is a `--resume` of run `01349136` in which **4 cases (S1-v1/v2/v3, S2-v1) were retained
  because two independent runs graded them identically** (a built-in reproducibility check) and the
  **other 11 were re-run fresh** on the clean engine, with the 2 initial stragglers (S3-v1, S4-v2)
  re-run individually until they produced real, non-artifact grades. No grade in the table has 0 calls.
- **Routing (2026-07-19):** supervisor `cerebras:gpt-oss-120b`; change-analyst + reviewer
  `cerebras:zai-glm-4.7`; log/metrics/memory specialists groq `llama-3.3-70b`; judge
  `gemini-2.5-flash`; `LLM_FALLBACK=cerebras:gpt-oss-120b,groq:llama-3.3-70b-versatile`.
- **Grading is deterministic except RCA phrasing** (judge role, auditable in `llm_calls`, keyword
  fallback). Recovery is re-derived independently from raw `metrics.jsonl` via the actuator `/tail` —
  the graph never grades its own recovery — which is why recovery reads a clean 8/8.
- **Reproduce:** `docker compose --profile platform --profile world up -d` →
  `uv run python -m argus.evals.run --suite all --memory off --supervisor-model cerebras:gpt-oss-120b`
  → `uv run python -m argus.evals.report`. Cases are versioned in `evals/scenarios/*.yaml`.
