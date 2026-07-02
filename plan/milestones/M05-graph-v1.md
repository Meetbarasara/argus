# M05 — Graph v1 (happy path, autonomous resolution)

**Objective:** the full LangGraph pipeline running real incidents end to end with
**sequential** specialists: intake → plan → investigate → synthesize → review →
risk_gate → (AUTO/NOTIFY only) remediate → verify_recovery → close. S1 resolves
autonomously. Approval-requiring paths stop at a clean TAKE_OVER-style hold (M06
replaces the hold with real interrupts). Memory nodes exist as no-ops (M07 fills them).

**Read first:** 04 (entire doc — topology, state, schemas, prompts, budgets),
03 §1 (status machine), 08 #17, #21.
**Prerequisites:** M04 green; world + platform running; keys for live gate.

## Deliverables

| Path | Responsibility |
|---|---|
| `src/argus/agents/schemas.py` | 04 §3 verbatim |
| `src/argus/agents/prompts.py` | all prompt builders (04 §4 skeletons, filled) |
| `src/argus/agents/supervisor.py` | plan() + synthesize() via router.structured |
| `src/argus/agents/specialists.py` | tool-loop runner: bound tools (M04 bridge), ≤4 calls, 1 error retry, emits Finding (failed step ⇒ confidence 0.0 finding) |
| `src/argus/agents/reviewer.py` | review() → ReviewVerdict |
| `src/argus/graph/state.py` | IncidentState (04 §2) |
| `src/argus/graph/nodes/*.py` | one module per node; deterministic nodes have no LLM import |
| `src/argus/policy/risk_gate.py` | pure function (policy.yaml → level + rule_trace); exhaustive unit tests incl. confidence overrides & strictness ordering |
| `src/argus/graph/build.py` | compile graph with PostgresSaver (08 #17); sequential specialist chain for now; budget guard wrapper on every LLM node (04 edge table) |
| `src/argus/worker/tasks.py` | run_incident v1: invoke graph, map outcomes → status; if gate says APPROVE_*/TAKE_OVER: status WAITING_APPROVAL/TAKEN_OVER + status_reason "HITL lands in M06", graph run ends cleanly (no interrupt yet) |
| `src/argus/graph/verify.py` | verify_recovery: re-evaluate breached rule from metrics, 2×OK/10s within 120s |
| tests | `tests/graph/` (host tier: FakeLLM in-process, `world_fixture` tmp worldstate, `fake_actuator` mock, platform postgres on localhost — see 05): scripted full runs — (a) S1 happy path: correct statuses, spans, NOTIFY approvals row, remediation executed, RESOLVED*; (b) reviewer revise loop: bad hypothesis once → feedback → approve on 2nd; (c) reviewer reject ×2 → TAKEN_OVER; (d) budget breach → TAKEN_OVER; (e) risk_gate unit table for all 5 scenarios' expected levels. (*RESOLVED here = recovery verified + close; postmortem no-op until M07 — the status machine allows RECOVERED→RESOLVED with an empty postmortem, flagged `memory_used=false`.) |

## Steps

1. schemas + risk_gate (pure units, test-first).
2. prompts + agent wrappers against FakeLLM.
3. nodes + build.py; graph tests (a)–(e) all on FakeLLM — deterministic, no network.
4. Celery integration: task drives the compiled graph with thread_id=incident_id;
   checkpointer `.setup()` at worker boot.
5. Live run: inject S1 → watch it resolve autonomously (LLM_MODE=record so the run
   doubles as a demo fixture).
6. Live-ish run: inject S3 → reaches WAITING_APPROVAL hold with correct proposed
   rollback recorded.

## Acceptance criteria

- [ ] Graph tests (a)–(e) green with FakeLLM (no live calls; `pytest -m graph`).
- [ ] Live S1: alert → RESOLVED with remediation `restart_service(shopredis)`,
      escalation NOTIFY, world actually recovered (metrics), spans tree complete
      (node+llm+tool+policy kinds), counters/cost populated on the incident row.
- [ ] Live S3: reaches WAITING_APPROVAL with proposed rollback_deploy of the right deploy.
- [ ] No node writes incident status except via incident_repo (grep-able).
- [ ] Prompt text lives only in prompts.py.

## Verification gate

```
$ uv run poe verify && uv run poe test-graph          → green
$ python -m demoworld.inject --scenario S1
$ # poll: curl -s localhost:8080/api/incidents?limit=1 | jq '.[0] | {status, escalation_level}'
        → {"status":"RESOLVED","escalation_level":"NOTIFY"} within ~4 min
$ curl -s localhost:8080/api/incidents/<id>/spans | jq 'length'   → > 15 spans, kinds include node/llm/tool/policy
$ python -m demoworld.inject --scenario S3
        → incident reaches WAITING_APPROVAL; .remediation? null; approvals row PENDING with rollback_deploy proposal
$ uv run poe verify-all                                → green (regression checkpoint)
```

**Gotchas:** 08 #12–#13 (structured output in anger), #17, #21.
**Out of scope:** interrupts/resume (M06), memory (M07), parallelism (M08).
