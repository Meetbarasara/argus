# Argus Build Plan — Index & Execution Order

Argus is an **AI on-call engineer**: alerts fire from a running demo microservice stack;
a supervisor agent plans an investigation; specialist agents gather evidence with tools;
a reviewer agent validates the root-cause hypothesis; a deterministic risk gate decides
whether remediation runs automatically or pauses for human approval; every decision is
traced end-to-end; postmortems become persistent memories that make future incidents
faster. An evaluation harness proves all of it with numbers.

This directory is the **single source of truth** for the build. It was designed up front
so the builder never has to make architectural decisions mid-build.

## Document index

| Doc | Purpose |
|---|---|
| [00-README.md](00-README.md) | This file: index, milestone order, builder protocol, doc map |
| [01-product-spec.md](01-product-spec.md) | What we're building, user stories, demo storyline, non-goals |
| [02-architecture.md](02-architecture.md) | Containers, data flow, repo layout, ports, ADRs (locked decisions) |
| [03-data-model.md](03-data-model.md) | DB schema, worldstate file formats, config schemas, REST API, env vars |
| [04-agents-graph.md](04-agents-graph.md) | Graph topology, state, Pydantic schemas, agents, prompts, tool registry |
| [05-conventions.md](05-conventions.md) | Code style, testing tiers, logging, commits, definition of done |
| [06-verification-protocol.md](06-verification-protocol.md) | The before/after gate procedure and failure playbook |
| [07-evaluation-plan.md](07-evaluation-plan.md) | Metrics, judge rubric, ablations, report template, target numbers |
| [08-risks-gotchas.md](08-risks-gotchas.md) | Known pitfalls (Windows, rate limits, LangGraph/Celery) + mitigations |
| [PROGRESS.md](PROGRESS.md) | Living tracker: milestone status, gate evidence, deviations, open questions |
| `milestones/M00…M12` | One file per milestone: steps, acceptance criteria, verification gate |

## Milestone execution order

Strictly sequential. Each milestone leaves the repo in a verified-green state.

| # | Milestone | Delivers | Est. | Key gate |
|---|---|---|---|---|
| M00 | [Scaffold & tooling](milestones/M00-scaffold.md) | repo, uv, poe, ruff/mypy/pytest, compose skeleton | 0.5d | `poe verify` green; `docker compose config` valid |
| M01 | [Demo world](milestones/M01-demo-world.md) | shop services, telemetry, fault injector, alertwatch, actuator | 1.5d | every scenario produces its expected evidence + alert |
| M02 | [Platform core](milestones/M02-platform-core.md) | API, DB migrations, Celery, alert→incident intake | 1d | posted alert becomes an incident row; Celery round-trip |
| M03 | [LLM layer](milestones/M03-llm-layer.md) | router, rate limits, structured-output retry, record/replay, cost log | 1d | validation-retry + replay unit tests; live smoke per provider |
| M04 | [Tool layer](milestones/M04-tools.md) | tool registry + 9 tools, tool_calls logging | 1d | tools find S3 evidence against live world; rollback works |
| M05 | [Graph v1](milestones/M05-graph-v1.md) | full happy path, sequential specialists, auto-remediation | 1.5d | S1 resolved end-to-end autonomously; fake-LLM graph tests |
| M06 | [Human-in-the-loop](milestones/M06-hitl.md) | interrupt/resume, 5 approval levels, modify, take-over | 1.5d | S3 pauses for approval; approve via API resumes to RESOLVED |
| M07 | [Memory](milestones/M07-memory.md) | pgvector store, postmortem write, recall, fast-path | 1d | same fault twice → second run measurably cheaper |
| M08 | [Parallelism & resilience](milestones/M08-parallel-resilience.md) | parallel specialists, retries, budgets | 1d | specialist spans overlap; injected tool failure recovered |
| M09 | [Observability](milestones/M09-observability.md) | OTel exporters, Jaeger profile, dashboard endpoints | 0.5d | full span tree via API; Jaeger shows the trace |
| M10 | [React UI](milestones/M10-ui.md) | 5-page SPA: incidents, trace tree, approvals, memory, dashboard | 2d | approve an incident end-to-end from the browser |
| M11 | [Evaluation harness](milestones/M11-evals.md) | scenario suite, runner, grading, ablations, EVALUATION.md | 1.5d | 15-case suite runs; memory-lift ablation produces numbers |
| M12 | [Demo & docs](milestones/M12-demo-docs.md) | one-command demo, README, INTERVIEW_NOTES.md | 0.5d | fresh-clone quickstart works; demo script runs the storyline |

Total ≈ 14–15 focused days.

## Builder protocol (the loop for every milestone)

1. **Orient** — read `PROGRESS.md`; read this file's doc map row for the milestone; read
   the milestone file and the cited docs. Nothing else is required context.
2. **Baseline (verify BEFORE)** — `git status` clean; `uv run poe verify` green
   (and `poe verify-all` where the milestone says so). Red baseline = fix first, it's a
   regression from a previous milestone.
3. **Mark in progress** — set the milestone row in `PROGRESS.md` to `in_progress`.
4. **Implement** — follow the milestone's ordered steps. Write tests alongside code
   (test-first for pure logic). Keep commits small if you like, but at least one
   `M0X:`-prefixed commit at the end.
5. **Verify AFTER** — `uv run poe verify` green, then run every command in the
   milestone's **Verification gate** verbatim and compare with the expected output.
6. **Record** — update `PROGRESS.md`: status `done`, one-line gate evidence
   (what you ran, what you observed), any deviations with reasons.
7. **Commit** — `git add -A && git commit -m "M0X: <title>"`.

**Regression checkpoints:** at the end of M05, M08, M11, and M12 additionally run
`uv run poe verify-all` (unit + integration) to catch cross-milestone breakage.

## Doc map — what to read per milestone

| Milestone | Required reading (beyond the milestone file itself) |
|---|---|
| M00 | 02 (repo layout, compose topology), 05 (tooling config) |
| M01 | 01 (scenario behavior), 02 (world containers), 03 (worldstate formats, actuator API) |
| M02 | 02 (platform containers), 03 (DB schema: incidents; REST: alerts/incidents; env vars) |
| M03 | 03 (llm_calls schema, models.yaml), 04 (structured schemas), 08 (provider quirks, rate limits) |
| M04 | 03 (tool_calls schema, worldstate formats), 04 (tool registry table) |
| M05 | 04 (entire doc), 03 (incident statuses, spans) |
| M06 | 04 (risk gate, approval flow), 03 (approvals schema, policy.yaml), 08 (interrupt/resume) |
| M07 | 03 (memories schema), 04 (recall + postmortem nodes), 07 (memory-lift metric) |
| M08 | 04 (parallel topology, budgets), 08 (Send API notes) |
| M09 | 02 (dual span sinks ADR), 03 (spans schema, dashboard API) |
| M10 | 03 (REST API), 01 (demo storyline — what the UI must show), 05 (UI conventions) |
| M11 | 07 (entire doc), 03 (eval tables, scenario yaml schema) |
| M12 | 01 (demo storyline), 07 (report template) |

## Hard rules (repeated because they matter)

- Schemas/APIs/configs are defined once, in 03 and 04. Milestones **cite** them.
  If a milestone file ever seems to contradict 03/04, **03/04 win** — log the
  discrepancy in PROGRESS.
- Never weaken a test or gate to pass it.
- All runtime code targets Linux containers. Host = uv + docker + node only.
- Deviations (version bumps, renamed model ids, workarounds) always get a
  PROGRESS entry: what, why, impact.

## Resuming in a fresh session

Open the repo and say: *"Continue building Argus. Read CLAUDE.md and plan/PROGRESS.md,
then proceed with the current milestone."* Everything needed to continue is on disk.
