# Argus Evaluation Report

run `ef2bebc0` · 2026-07-17 · commit `26fc545` · supervisor=cerebras:gpt-oss-120b · memory=off · N=15

## Headline
- **RCA accuracy:** 2/15 (13%)
- **Remediation correct:** 3/15 (20%)
- **Recovery:** 2/3 of correctly-remediated (67%)
- **Escalation:** precision 89% / recall 73%
- **Efficiency:** median MTTR 228.5s · median 9 LLM calls · median cost $0.0057
- **Outcome:** 2/15 PASS

## Per-case
| case | outcome | rca | remediation | recovered | escalation (exp→act) | calls | mttr |
|---|---|---|---|---|---|---|---|
| S1-v1 | PASS | ✅ | ✅ | ✅ | NOTIFY→NOTIFY ✅ | 16 | 37s |
| S1-v2 | FAIL | ❌ | ❌ | ❌ | NOTIFY→TAKE_OVER ❌ | 26 | — |
| S1-v3 | FAIL | ❌ | ❌ | ❌ | None→None ❌ | 0 | — |
| S2-v1 | FAIL | ❌ | ❌ | ✅ | APPROVE_ACTION→None ❌ | 0 | — |
| S2-v2 | FAIL | ❌ | ❌ | ❌ | APPROVE_ACTION→TAKE_OVER ❌ | 8 | — |
| S2-v3 | FAIL | ❌ | ❌ | ❌ | None→None ❌ | 0 | — |
| S3-v1 | FAIL | ❌ | ❌ | ❌ | APPROVE_ACTION→TAKE_OVER ❌ | 13 | — |
| S3-v2 | FAIL | ❌ | ❌ | ❌ | APPROVE_ACTION→TAKE_OVER ❌ | 21 | — |
| S3-v3 | PASS | ✅ | ✅ | ✅ | APPROVE_ACTION→APPROVE_ACTION ✅ | 21 | 420s |
| S4-v1 | FAIL | ❌ | ❌ | ❌ | APPROVE_ACTION→None ❌ | 0 | — |
| S4-v2 | FAIL | ❌ | ❌ | ❌ | APPROVE_ACTION→None ❌ | 0 | — |
| S4-v3 | FAIL | ❌ | ❌ | ❌ | APPROVE_ACTION→TAKE_OVER ❌ | 16 | — |
| S5-v1 | FAIL | ❌ | ✅ | ❌ | APPROVE_ACTION→TAKE_OVER ❌ | 18 | — |
| S5-v2 | FAIL | ❌ | ❌ | ❌ | APPROVE_ACTION→TAKE_OVER ❌ | 5 | — |
| S5-v3 | FAIL | ❌ | ❌ | ❌ | APPROVE_ACTION→TAKE_OVER ❌ | 9 | — |

## Failures
- **S1-v2** (FAIL): diagnosis “auto-resolved in eval mode (policy_sim take-over)” · judge: The system diagnosis describes an auto-resolution process ('policy_sim take-over') rather than identifying the actual root cause, which was 'shopredis' being down and breaking 'shopapi's redis cache dependency. The causal mechanism is completely different. · incident `b631abe5`
- **S1-v3** (FAIL): diagnosis “—” · judge: — · incident ``
- **S2-v1** (FAIL): diagnosis “ShopAPI is unable to reach its dependencies due to a transient network/connectivity issue,” · judge: The system diagnosis provided no causal mechanism. The expected root cause identified 'paymentsvc latency spiked' as the causal mechanism and 'paymentsvc' as the primary causal service, neither of which were present in the diagnosis. · incident `8c99090e`
- **S2-v2** (FAIL): diagnosis “auto-resolved in eval mode (policy_sim take-over)” · judge: The system diagnosis describes the resolution method ('auto-resolved in eval mode') rather than the actual technical root cause of the incident (paymentsvc latency spike). While it correctly identifies 'shopapi' as an affected service, it misses the causal mechanism and the upstream service ('paymentsvc') entirely. · incident `0d796857`
- **S2-v3** (FAIL): diagnosis “—” · judge: — · incident ``
- **S3-v1** (FAIL): diagnosis “auto-resolved in eval mode (policy_sim take-over)” · judge: The diagnosis correctly identifies the affected service (shopapi) but fails to identify the causal mechanism. The system diagnosis describes how the issue was resolved ('auto-resolved in eval mode'), not the root cause of the problem (a deploy changing a URL to an unreachable endpoint). · incident `07dd742f`
- **S3-v2** (FAIL): diagnosis “auto-resolved in eval mode (policy_sim take-over)” · judge: The diagnosis correctly identifies the affected service (shopapi) but fails to identify the causal mechanism. The system diagnosis describes how the issue was resolved ('auto-resolved in eval mode'), not the root cause of the problem (a deploy changing a URL to an unreachable endpoint). · incident `3709709c`
- **S4-v1** (FAIL): diagnosis “—” · judge: keyword-fallback · incident `fa751db4`
- **S4-v2** (FAIL): diagnosis “—” · judge: The system provided no diagnosis for the root cause, only identifying the affected service. The expected root cause details a specific causal mechanism (deploy shrinking db pool, exhausting connections). · incident `c20e2132`
- **S4-v3** (FAIL): diagnosis “auto-resolved in eval mode (policy_sim take-over)” · judge: The system diagnosis correctly identifies the affected service (shopapi) but fails to identify the causal mechanism. The expected root cause points to a deploy shrinking the db pool leading to connection exhaustion, whereas the diagnosis describes how the issue was resolved ('auto-resolved in eval mode (policy_sim take-over)') rather than the underlying problem itself. · incident `d359fc77`
- **S5-v1** (FAIL): diagnosis “auto-resolved in eval mode (policy_sim take-over)” · judge: The system diagnosis correctly identified the affected service (shopapi) but failed to identify the causal mechanism. The expected cause was a deploy enabling a broken feature flag, whereas the system diagnosis described how the issue was handled (auto-resolved in eval mode) rather than its root cause. · incident `cdf22901`
- **S5-v2** (FAIL): diagnosis “auto-resolved in eval mode (policy_sim take-over)” · judge: The diagnosis correctly identifies the affected service (shopapi) but completely misses the causal mechanism. The expected cause is a broken feature flag enabled by a deploy, whereas the diagnosis describes an auto-resolution process ('auto-resolved in eval mode (policy_sim take-over)') rather than the root cause of the incident itself. · incident `cdefbec0`
- **S5-v3** (FAIL): diagnosis “auto-resolved in eval mode (policy_sim take-over)” · judge: The diagnosis correctly identifies the affected service (shopapi) but completely misses the causal mechanism. The expected cause is a broken feature flag enabled by a deploy, whereas the diagnosis describes an auto-resolution process ('auto-resolved in eval mode (policy_sim take-over)') rather than the root cause of the incident itself. · incident `39fb504c`

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

## Ablation: supervisor model

Same suite, memory OFF, supervisor model swapped (one flag) — the architecture is model-agnostic. List-price cost.

| supervisor | RCA | remediation | recovery | esc P/R | median calls | median MTTR | median cost |
|---|---|---|---|---|---|---|---|
| cerebras:gpt-oss-120b | 2/15 | 3/15 | 2/3 | 89%/73% | 9 | 228.5s | $0.0057 |
| gemini-2.5-flash | 1/4 | 1/4 | 1/1 | 0%/0% | 6.0 | 113s | $0.0043 |
| gemini-2.5-flash | 3/15 | 3/15 | 2/3 | 80%/36% | 0 | 133s | $0.0000 |
