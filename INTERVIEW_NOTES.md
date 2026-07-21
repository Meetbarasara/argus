# Argus — interview notes

Talking points, file pointers, and the recording checklist. Numbers are sourced from
[EVALUATION.md](EVALUATION.md) and [plan/PROGRESS.md](plan/PROGRESS.md) — no hand-typed
drift; where the committed full-suite run is quota-degraded, that is stated plainly.

## 30-second pitch

"Argus is an AI on-call engineer. An alert fires on a running microservice stack; a
supervisor agent plans an investigation, specialist agents gather evidence with tools, a
reviewer independently validates the root-cause hypothesis, and a **deterministic** risk
gate decides whether Argus remediates autonomously or pauses for a human. It's a LangGraph
state machine, not a prompt chain — with human-in-the-loop, persistent memory that provably
cuts repeat-incident cost, full OpenTelemetry tracing, and a 15-case evaluation harness with
ablations. It runs on free-tier LLMs."

## Architecture walkthrough order (how to demo the code)

1. **The world is real** — [`demoworld/`](src/demoworld): shopapi/paymentsvc emit JSONL
   logs + metrics to a shared volume; `inject.py` breaks it 5 ways; alertwatch fires
   webhooks. This is why the evidence is genuine, not mocked.
2. **Alert → incident → graph** — [`api/routers/alerts.py`](src/argus/api/routers/alerts.py)
   (service-level dedupe) → Celery → [`worker/tasks.py`](src/argus/worker/tasks.py) → the
   compiled graph in [`graph/build.py`](src/argus/graph/build.py).
3. **The agents** — [`agents/`](src/argus/agents): supervisor plan/synthesize, three
   specialists on a tool loop, reviewer. Prompts are isolated in `prompts.py`.
4. **The safety spine** (below).
5. **Memory** — [`memory/recall.py`](src/argus/memory/recall.py) scoring +
   fast-path; postmortems become pgvector rows.
6. **Proof** — [`evals/`](src/argus/evals) + [EVALUATION.md](EVALUATION.md).

## The three safety layers (the interview centerpiece)

The LLM is never trusted to authorize its own risky action. Three independent gates:

1. **Independent review** — a separate reviewer agent must accept the hypothesis before it
   can reach remediation; `revise` loops back to the supervisor (≤2×), then escalates.
   → [`agents/reviewer.py`](src/argus/agents), the `review` node in [`graph/`](src/argus/graph).
2. **Deterministic risk gate** — `policy.yaml` maps (action × target class × confidence
   band) → escalation level, in plain code. The LLM proposes; policy disposes.
   → [`policy/risk_gate.py`](src/argus/policy/risk_gate.py) (ADR-04), [`config/policy.yaml`](config/policy.yaml).
3. **Human-in-the-loop** — anything above NOTIFY is a real LangGraph `interrupt()`; the
   incident parks as WAITING_APPROVAL with a durable checkpoint and survives a worker
   restart; approve/modify/reject/take-over resume from the exact paused node.
   → [`api/routers/approvals.py`](src/argus/api/routers/approvals.py) (proven by `test_hitl` 7/7).

Bonus layer — **capability isolation**: mutating tools run *only* inside the `remediate`
node, enforced by the tool executor (not prompts); the actuator holds the only docker
socket and requires a token that never enters logs or prompts (ADR-03).

## Memory lift & model comparison

- **Method:** `--repeat-for-memory` runs each scenario's v1 (seed) then v2 (measure) with
  memory ON vs OFF, wiping `memories` between conditions; the delta in LLM calls / MTTR /
  RCA on the v2 runs is the lift (07 §4). Model comparison swaps `--supervisor-model` with
  memory off for both.
- **Measured:** M07 proved a **54 % reduction in LLM calls** on a repeat S1 (13 → 6 calls),
  well past the ≥20 % target (see PROGRESS M07). The M11 harness reproduces this as a table;
  the committed full-suite ablation is quota-degraded (clean re-run queued for fresh quota).
- **Honest framing:** "memory is worth ~half the LLM calls on a recurring incident, measured
  by ablation, not vibes."

## What failed and why (from EVALUATION.md §Failures)

- **Change-correlation under decoys (S1-v2, PARTIAL):** RCA correct (redis down), but two
  benign decoy deploys led the change-analyst to propose a rollback and over-escalate
  instead of restarting the cache — a genuine precision finding, quota-independent. It's
  exactly what the v2 "decoy" variants are designed to expose.
- **Weak-supervisor escalation:** with the Groq fallback as supervisor (Gemini exhausted),
  payment-latency (S2) draws low-confidence hypotheses that the risk gate correctly routes
  to TAKE_OVER — model quality, not a graph bug (the gate did its job).
- **The quota ceiling:** a full unattended 15-case suite exceeds the free-tier budget in one
  sitting (Gemini's ~20/day cap + Groq's per-minute TPM under the doubled fallback load).
  Documented, not hidden — and the reason the headline re-run is deferred to fresh quota.

## The free-LLM story, framed as robustness engineering

Building on free tiers *forced* the reliability features that make the system production-shaped:
validation-retry on malformed structured output, an independent reviewer that catches weak
hypotheses, a deterministic gate + HITL so a bad call never auto-executes, record/replay for
deterministic tests + demos (ADR-05), and a transparent provider fallback
(`LLM_FALLBACK=groq:…`) so a rate-limited call retries on another model. "The constraint
became the feature."

## Reliability Q&A — the multi-agent questions you WILL get

**"How do you make sure an agent's response is correct?"**
Four checks, in order, and only the last one is an LLM-free ground truth:
1. **Schema validation on every call** — responses must parse into Pydantic models; a
   malformed reply is retried with the validation error fed back (`validation_retries` is
   recorded per call and visible in the trace UI). → [`agents/schemas.py`](src/argus/agents/schemas.py)
2. **Evidence grounding** — a hypothesis carries excerpts from real tool output (logs,
   metrics, deploy diffs); the approval card shows them so a human can audit the claim.
3. **Independent review** — a *different* model (role-routed) must accept the hypothesis;
   `revise` loops back, twice max, then it escalates instead of pushing through.
4. **Reality check** — after remediation, `verify_recovery` re-reads the world's metrics;
   "fixed" means the error rate actually fell, not that a model said so.
And offline: the 15-case eval suite grades RCA against labeled scenarios (deterministic
keyword/label match + LLM judge) — correctness is a measured number (RCA 10/15), not a claim.

**"How do you make sure agents don't drift / hallucinate actions?"**
- **The LLM never authorizes itself.** Escalation level comes from `policy.yaml` via plain
  code; an unknown tool or unknown target service hard-routes to TAKE_OVER.
  → [`policy/risk_gate.py`](src/argus/policy/risk_gate.py)
- **Hallucinated calls can't execute.** Tools live in a fixed registry with JSON-schema arg
  validation; a made-up tool or bad params fail before any side effect. Even a *human's*
  modified action is re-validated server-side and may only lower risk (422 otherwise).
- **Budgets** cap LLM calls and wall time per incident — breach = escalate, never loop.
- **Low confidence escalates.** A live 30 %-confidence diagnosis routed to TAKE_OVER —
  the safe failure direction (documented as over-escalation in EVALUATION.md).
- **Drift across versions** is caught by re-running the eval suite after any prompt/model
  change (record/replay makes reruns deterministic and free) and comparing pass rates —
  the `/api/evals/runs` panel keeps the history side by side.
- **Memory can't quietly steer** — fast-path needs ≥0.92 similarity; consolidation merges
  duplicates and decays stale entries, so old incidents don't hijack new ones.

**"Why multiple agents instead of one big prompt?"**
Separation of concerns you can point at: the supervisor only plans (1–5 typed steps),
specialists only gather evidence on a tool loop (parallel, cheaper models), the reviewer
only critiques, and none of them holds remediation authority. It's a typed LangGraph state
machine — every hop is a checkpointed state transition, not chat history.

**"What if an agent dies mid-incident?"**
Postgres checkpointer: the graph resumes from the exact parked node after a worker restart
(proven by `test_hitl`). The approval decision flip is a single atomic
`UPDATE … WHERE status='PENDING'` — a double-approve is a 409, and a duplicate resume no-ops.

**"How do you control cost?"**
Per-call token/cost accounting rolled up per incident and per role (dashboard chart), model
routing per role (big model only where it pays), memory fast-path (measured 54 % call
reduction on repeats), budgets as the hard stop. Whole 15-case eval: ~$0.32.

**Honest gaps (say them before they ask):** the judge is itself an LLM (paired with
deterministic label checks); eval reruns are manual, not a CI canary; the demo world's logs
are trusted input — real infra would need prompt-injection hardening on ingested text.

## Scaling answers (what changes for real infra)

- **Telemetry:** the tools read an interface, not files — swap the JSONL readers in
  [`tools/`](src/argus/tools) for Loki/Prometheus adapters; the graph is unchanged (ADR-09).
- **Actuation:** the actuator becomes a Kubernetes operator / cloud API behind the same
  token-authed HTTP contract; agents still get capabilities, not credentials (ADR-03).
- **Memory:** `VectorStore` is a one-file interface — pgvector → Pinecone/pgvector-at-scale
  without touching recall logic (ADR-01).
- **Multi-tenancy / authz:** add auth at the API edge + per-tenant incident/memory
  partitioning; the graph and policy are tenant-agnostic today.
- **Throughput:** Celery already scales horizontally (prefork workers); the checkpointer is
  Postgres, so a restart or a second worker resumes any parked incident.

## Resume bullets (measured, defensible)

Pick 3–4; every number traces to EVALUATION.md / PROGRESS.md:

- Built **Argus**, an AI on-call engineer: a LangGraph multi-agent system (supervisor,
  3 parallel specialists, independent reviewer) that investigates live alerts on a
  13-container demo microservice stack, remediates via a token-authed actuator, and
  escalates to a human through durable graph interrupts (FastAPI + Celery + Postgres/pgvector + React).
- Enforced safety with a **deterministic risk gate** (policy-as-code over action × target ×
  confidence) and full human-in-the-loop approve/modify/reject/take-over — **100 % escalation
  recall** on the eval suite (zero unauthorized autonomous actions).
- Shipped a **15-scenario evaluation harness** with LLM-judge + deterministic grading and
  memory ablations: **67 % root-cause accuracy, 8/15 end-to-end PASS, ~$0.02/incident**,
  run headlines regenerated from the DB (no hand-typed numbers).
- Implemented **pgvector incident memory** with recall-informed planning and a similarity-gated
  fast path — **54 % fewer LLM calls** on an identical repeat incident (13 → 6, M07 controlled
  measurement). Say "same-fault repeat", not "ablation": the harness's memory ON/OFF ablation
  probes a *decoy-shifted* variant that falls under the 0.92 fast-path threshold and showed no
  lift (15 vs 12) — that negative result is printed in EVALUATION.md, so claiming "the ablation
  proved 20 %+" contradicts your own repo.
- Full observability: every LLM/tool call traced with prompt, tokens, cost, and latency;
  span-tree drill-down UI; record/replay LLM modes for deterministic tests on free-tier models.

## Recording checklist (<5-min video)

**Pre-flight:** `LLM_MODE=record` dry run to fill the cache, then record against
`LLM_MODE=replay` for a deterministic, zero-quota take (ADR-05). Quiet the dashboard first.

Beats: quiet dashboard → `inject --scenario S3` → incident appears INVESTIGATING, live trace
tree grows (plan → parallel specialists → synthesize) → reviewer accepts → WAITING_APPROVAL,
approval card shows evidence + proposed rollback + confidence → **Approve** → rollback
executes, error rate falls, RESOLVED, postmortem memory appears → inject S3 again → memory
fast-path, visibly fewer steps → close on the eval dashboard (scores + memory-lift ablation).

Screenshots to capture into `docs/img/`: incidents list, trace drill-down (llm span →
prompt/tokens/cost), approval card, dashboard, Jaeger trace.
