# 01 — Product Spec

## Elevator pitch

**Argus is an AI on-call engineer.** When an alert fires on a running system, Argus
investigates it the way a human SRE would — reads logs, checks metrics, reviews recent
deploys — forms a root-cause hypothesis, has that hypothesis independently reviewed,
and then either fixes the problem itself or pauses and asks a human for approval,
depending on risk and confidence. Every step is traced. Every resolved incident becomes
a memory that makes the next similar incident faster and cheaper.

It is not a chatbot demo. It is production-shaped infrastructure for autonomous AI
workflows: task decomposition, tool use, independent review, deterministic safety
gating, human-in-the-loop, persistent memory, full observability, and a measurable
evaluation harness.

## Why it exists (resume framing)

Most AI portfolio projects are single-agent wrappers around one prompt. Argus
demonstrates the skills AI-engineering roles actually screen for:

1. **Multi-agent orchestration** — a supervisor that plans, specialists that execute,
   a reviewer that validates, wired as a state machine (LangGraph), not a prompt chain.
2. **Safety architecture** — the LLM never authorizes its own risky actions; a
   deterministic policy gate does, and humans approve what policy says they must.
3. **Memory that provably helps** — not "we added a vector DB" but "memory reduced
   median LLM calls per repeat incident by X%, measured".
4. **Evaluation discipline** — a seeded-fault eval suite with root-cause accuracy,
   remediation correctness, recovery rate, escalation precision, cost — plus ablations
   (memory on/off, model A/B).
5. **Observability** — OpenTelemetry-instrumented trace trees down to individual
   prompts, tokens, and dollars.

## The two systems

- **Demo world** (`demoworld`): a small e-commerce microservice stack (shop API,
  payment service, Postgres, Redis, load generator) that produces real logs, metrics,
  and deploy history — plus a **fault injector** that breaks it in 5 reproducible ways
  and an **alertwatch** process that fires alerts. This is the patient.
- **Platform** (`argus`): the agent system that receives alerts and runs the
  investigate → review → gate → remediate → learn loop. This is the doctor.

Both ship in one docker-compose file; the whole demo runs offline except for LLM API
calls (free tiers).

## Fault scenarios (product behavior contract)

These 5 scenarios define what "working" means. Each has a deterministic evidence trail
and one correct remediation. They double as the evaluation suite (see 07).

| ID | Name | What breaks | What the operator sees | Correct fix | Expected escalation |
|---|---|---|---|---|---|
| S1 | `redis_down` | cache container stopped | 5xx spike + redis connection errors in shopapi logs | restart `shopredis` | NOTIFY (auto-fix, inform human) |
| S2 | `payment_latency` | in-memory chaos adds ~3s to paymentsvc (**no deploy in history**) | checkout p95 latency alert, timeout logs, no recent change | restart `paymentsvc` | APPROVE_ACTION |
| S3 | `bad_deploy_env` | deploy points shopapi at wrong payment URL | 502s on /checkout starting right after a visible deploy | rollback that deploy | APPROVE_ACTION |
| S4 | `db_pool_exhaustion` | deploy shrinks shopapi DB pool to 2 | mixed pool-timeout 500s + latency under load; subtle config deploy | rollback that deploy | APPROVE_ACTION |
| S5 | `feature_flag_500` | deploy enables broken `recs_v2` flag | 5xx on /products only; deploy visible | rollback that deploy | APPROVE_ACTION |

Design intent: S1 proves autonomous remediation; S2 proves agents don't blindly blame
deploys (there is none); S3–S5 prove change-correlation with three different symptom
shapes; all of S2–S5 exercise human approval.

## Core user stories

1. **Autonomous resolution (S1).** An alert arrives → Argus investigates, reviewer
   approves the hypothesis, policy says NOTIFY → Argus restarts the cache itself,
   verifies metrics recovered, writes a postmortem memory, and informs the human.
2. **Approval flow (S3).** Alert arrives → hypothesis blames deploy `d-0042` → policy
   says APPROVE_ACTION → execution pauses; the human sees the full context (evidence,
   reasoning, proposed rollback, similar past incidents) in the review UI and clicks
   Approve / Modify / Reject. Approve resumes the paused graph exactly where it stopped.
3. **Reviewer catch.** A specialist's evidence doesn't support the supervisor's
   hypothesis → the reviewer returns `revise` with feedback → the supervisor
   re-synthesizes (max 2 loops) before anything reaches the human.
4. **Take-over.** Confidence stays too low / remediation fails twice / budget exceeded
   → Argus stands down, packages everything it learned, and hands the incident to the
   human, who records the actual resolution (which still becomes a memory).
5. **Memory learning.** The same fault class recurs → recall surfaces the past
   incident and its fix into planning → the second investigation is measurably shorter.
6. **Debugging via traces.** Any past incident can be opened as a span tree — every
   agent decision, prompt, tool call, cost, and human action — down to raw
   prompt/response payloads.
7. **Evaluation run.** One command runs the 15-case suite and produces a scored
   report; ablation flags re-run it with memory off or a different supervisor model.

## The 5-minute demo storyline (M12 builds exactly this)

1. `docker compose up` — both worlds healthy; UI dashboard shows a quiet system.
2. Inject **S3** (`bad_deploy_env`). Load generator starts failing checkouts.
3. Alert fires → incident appears in UI as INVESTIGATING; the live trace tree grows:
   plan → three specialists (parallel) → synthesis.
4. Reviewer approves the hypothesis; risk gate says APPROVE_ACTION → status
   WAITING_APPROVAL; approval card shows evidence excerpts, the proposed rollback, and
   the agent's reasoning. Human clicks **Approve**.
5. Rollback executes via the actuator; verify-recovery watches error rate fall;
   incident → RESOLVED; postmortem memory appears in the Memory page.
6. Inject **S3 again** (variant). This time the recall node surfaces the previous
   incident; the plan is visibly shorter; resolution takes fewer steps and less cost —
   shown side-by-side on the dashboard.
7. Close on the eval dashboard: suite scores, memory-lift ablation, model comparison.

## Non-goals (explicitly out of scope — do not build)

- No authentication/multi-tenancy (single local operator).
- No Kubernetes; docker-compose only. Single node.
- No real cloud/pager integrations (PagerDuty, Slack) — the webhook + UI feed stand in.
- No token-by-token streaming to the UI; polling is fine.
- No fine-tuning; no training pipelines.
- No Windows-native execution of services (containers only).
- Demo world stays at 2 app services + 2 datastores — resist making it "realistic-big".

## Glossary

| Term | Meaning |
|---|---|
| Incident | One alert-triggered execution of the graph, end to end |
| Finding | A specialist's structured evidence report for one plan step |
| Hypothesis | Supervisor's synthesized root cause + proposed remediation |
| Escalation level | AUTO / NOTIFY / APPROVE_ACTION / APPROVE_PLAN / TAKE_OVER |
| Fast path | Planning shortcut when memory similarity to a resolved incident is very high |
| Worldstate | The shared volume of demo-world logs/metrics/deploys/config |
| Gate | A milestone's verification commands + expected outputs |
