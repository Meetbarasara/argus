# Argus Evaluation Report

run `a6313997` · 2026-07-10 · commit `5deb2ef` · supervisor=gemini-2.5-flash · memory=off · N=15

> ⚠️ **This run is quota-degraded — it measures the free-tier LLM quota, not Argus.** Both
> free-tier providers were exhausted mid-run: Gemini's daily request cap (~20/day) was spent
> by the pre-run health smoke + harness validations, and Groq — bearing the doubled load once
> every Gemini-role call fell back to it — hit its per-minute token limit (429). So **10 of 15
> cases failed on the *first* LLM call** (0–1 `calls` below), before any investigation ran.
>
> **The harness itself is validated end-to-end.** The same **S3-v1** case graded **PASS**
> (RCA ✓ · remediation ✓ · recovery ✓ · escalation ✓) in isolation ~30 min earlier, while
> Gemini still had quota; M05–M07 proved live autonomous S1 resolution, the HITL approve→resolve
> flow, and a **54 % memory-lift** on repeats. A clean full-suite headline + memory ablation will
> be re-run on fresh Gemini quota (per plan/08 #27) and will regenerate this report.
>
> The one quota-independent signal here is **S1-v2 (PARTIAL)**: RCA correct (redis down) but the
> two decoy deploys led the change-analyst to propose a rollback and over-escalate instead of
> restarting the cache — a genuine change-correlation-precision finding.

## Headline
- **RCA accuracy:** 3/15 (20%)
- **Remediation correct:** 3/15 (20%)
- **Recovery:** 2/3 of correctly-remediated (67%)
- **Escalation:** precision 80% / recall 36%
- **Efficiency:** median MTTR 133s · median 0 LLM calls · median cost $0.0000
- **Outcome:** 2/15 PASS

## Per-case
| case | outcome | rca | remediation | recovered | escalation (exp→act) | calls | mttr |
|---|---|---|---|---|---|---|---|
| S1-v1 | PASS | ✅ | ✅ | ✅ | NOTIFY→NOTIFY ✅ | 13 | 78s |
| S1-v2 | PARTIAL | ✅ | ❌ | ✅ | NOTIFY→APPROVE_ACTION ❌ | 14 | 133s |
| S1-v3 | PASS | ✅ | ✅ | ✅ | NOTIFY→NOTIFY ✅ | 10 | 133s |
| S2-v1 | FAIL | ❌ | ✅ | ❌ | APPROVE_ACTION→TAKE_OVER ❌ | 17 | — |
| S2-v2 | FAIL | ❌ | ❌ | ❌ | APPROVE_ACTION→None ❌ | 0 | — |
| S2-v3 | FAIL | ❌ | ❌ | ❌ | None→None ❌ | 0 | — |
| S3-v1 | FAIL | ❌ | ❌ | ❌ | APPROVE_ACTION→TAKE_OVER ❌ | 1 | — |
| S3-v2 | FAIL | ❌ | ❌ | ❌ | APPROVE_ACTION→None ❌ | 0 | — |
| S3-v3 | FAIL | ❌ | ❌ | ❌ | APPROVE_ACTION→None ❌ | 0 | — |
| S4-v1 | FAIL | ❌ | ❌ | ❌ | APPROVE_ACTION→None ❌ | 0 | — |
| S4-v2 | FAIL | ❌ | ❌ | ❌ | APPROVE_ACTION→None ❌ | 0 | — |
| S4-v3 | FAIL | ❌ | ❌ | ❌ | APPROVE_ACTION→TAKE_OVER ❌ | 1 | — |
| S5-v1 | FAIL | ❌ | ❌ | ❌ | APPROVE_ACTION→None ❌ | 0 | — |
| S5-v2 | FAIL | ❌ | ❌ | ❌ | APPROVE_ACTION→None ❌ | 0 | — |
| S5-v3 | FAIL | ❌ | ❌ | ❌ | APPROVE_ACTION→TAKE_OVER ❌ | 1 | — |

## Failures
- **S1-v2** (PARTIAL): diagnosis “Redis dependency being down for shopapi service” · judge: The system diagnosis correctly identifies the causal mechanism (Redis dependency being down) and the same service (shopapi) as the expected root cause. · incident `15023c01`
- **S2-v1** (FAIL): diagnosis “auto-resolved in eval mode (policy_sim take-over)” · judge: The system diagnosis does not identify the causal mechanism (paymentsvc latency) and only mentions the affected service (shopapi) without explaining the root cause of the issue. · incident `6e285f8c`
- **S2-v2** (FAIL): diagnosis “—” · judge: keyword-fallback · incident `f4db703f`
- **S2-v3** (FAIL): diagnosis “—” · judge: — · incident ``
- **S3-v1** (FAIL): diagnosis “auto-resolved in eval mode (policy_sim take-over)” · judge: The system diagnosis does not identify the causal mechanism of the deploy changing the payment_url to an unreachable endpoint, only the affected service is correct. · incident `03747209`
- **S3-v2** (FAIL): diagnosis “—” · judge: System diagnosis is empty and does not identify the causal mechanism or the incorrect payment_url endpoint. · incident `2d441d83`
- **S3-v3** (FAIL): diagnosis “—” · judge: System diagnosis is empty and does not identify the causal mechanism or the incorrect payment_url endpoint. · incident `425aa2f5`
- **S4-v1** (FAIL): diagnosis “—” · judge: System diagnosis did not identify the causal mechanism of the deploy shrinking shopapi's db pool, exhausting connections under load. · incident `afb3f4c9`
- **S4-v2** (FAIL): diagnosis “—” · judge: The system diagnosis did not identify a causal mechanism for the incident. · incident `2da3430f`
- **S4-v3** (FAIL): diagnosis “auto-resolved in eval mode (policy_sim take-over)” · judge: keyword-fallback · incident `d5e938e9`
- **S5-v1** (FAIL): diagnosis “—” · judge: The system diagnosis does not identify a causal mechanism, only the affected service. · incident `d0f378ac`
- **S5-v2** (FAIL): diagnosis “—” · judge: The system diagnosis did not identify a causal mechanism or mention the broken feature flag (recs_v2) as the root cause of the 500s on shopapi. · incident `5f68250a`
- **S5-v3** (FAIL): diagnosis “auto-resolved in eval mode (policy_sim take-over)” · judge: keyword-fallback · incident `320bfd77`

## Method note
- Suite: 15 seeded-fault cases (S1–S5 × v1 clean / v2 decoys / v3 noise), versioned in `evals/scenarios/`.
- Grading is mostly deterministic: recovery re-derived from raw `metrics.jsonl` (never the graph's self-report), escalation from the incident row, remediation from the executed/proposed action. Only root-cause phrasing is judged (role=judge, auditable in `llm_calls`), with a keyword fallback.
- `AUTO_APPROVE=policy_sim` during runs (approvals auto-resolve as policy dictates, recorded `decided_by=policy_sim`). memory=off.

## Ablation: memory lift

Repeat-fault (v2) cases, memory ON vs OFF — each condition wipes `memories` then re-seeds via the v1 run (07 §4). Δ = ON−OFF, so a negative Δ means memory cut calls.

| case | calls ON | calls OFF | Δ calls | MTTR ON | MTTR OFF | RCA ON | RCA OFF |
|---|---|---|---|---|---|---|---|
| S1-v2 | 0 | 0 | +0 | — | — | ❌ | ❌ |

**Aggregate:** insufficient data (no OFF-condition calls recorded).
