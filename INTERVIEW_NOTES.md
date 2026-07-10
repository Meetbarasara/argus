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
