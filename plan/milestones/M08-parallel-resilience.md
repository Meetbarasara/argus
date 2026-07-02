# M08 — Parallel Specialists & Resilience

**Objective:** the graph gets production manners: independent plan steps fan out to
specialists in parallel (LangGraph Send API), failures degrade gracefully instead of
crashing runs, and budgets are enforced everywhere. Behavior contract (04 edge table)
does not change — only execution shape and robustness.

**Read first:** 04 §1–§2 (Send fan-out, findings reducer, edge budgets), 08 #20–#21.
**Prerequisites:** M07 green.

## Deliverables

| Change | Detail |
|---|---|
| `graph/build.py` | plan → conditional Send fan-out: steps with no unmet depends_on dispatch in one wave; dependent steps run in a second wave with their dependencies' findings injected (2 waves max — plan schema caps at 5 steps); all join at synthesize (08 #20: interrupts stay strictly post-join) |
| `agents/specialists.py` | tool-call budget 4→6; on tool structured-error: one corrective retry (error text in context) — already M05; NEW: on LLM/provider failure (post-router-retries): specialist emits Finding{confidence:0, summary:"specialist failed: …"} instead of raising |
| synthesize | already tolerates low-confidence findings; NEW: if >50% of findings have confidence 0 → skip hypothesis, route to take_over with reason "investigation degraded" |
| budget guard | pre-node check (llm_calls_used, wall clock) → take_over on breach; counted in state.budget by the router callback; unit-test the boundary (39th ok, 40th trips) |
| worker | Celery task-level: acks_late already (M02); NEW: task soft_time_limit = max_wall+60s → mark FAILED with status_reason on hard expiry |
| chaos tests | `tests/graph/test_resilience.py` (FakeLLM + monkeypatched tools): (a) one tool erroring twice → failed-step finding → synthesize plans around it → still resolves; (b) provider 429-storm on one specialist (router gives up) → degraded finding; (c) >50% degraded → TAKEN_OVER; (d) budget trip → TAKEN_OVER; (e) parallel wave: 3 independent steps → all findings present (reducer append, no loss) |
| parallelism proof | integration/live: spans of the three specialists overlap in time |

## Steps

1. Fan-out/join rewrite behind a flag (`PARALLEL_SPECIALISTS=true` default) — the
   sequential path stays testable for A/B latency demo.
2. Failure-path changes in specialists + synthesize.
3. Budget guard extraction (one wrapper, all LLM nodes).
4. Chaos tests (a)–(e); fix whatever they find.
5. Live S3 run; verify overlap + latency vs an M05-era sequential run (record both
   wall-clocks in PROGRESS — nice demo stat).

## Acceptance criteria

- [ ] All M05/M06/M07 graph + integration tests still green **unchanged** (behavior
      contract preserved) — this is the milestone's real gate.
- [ ] Chaos tests (a)–(e) green.
- [ ] Live incident shows ≥2 specialist spans with overlapping [start,end] windows.
- [ ] Wall-clock improvement vs sequential recorded (expect ~30–50% on 3-step plans).
- [ ] No path can crash a run without a terminal status + status_reason (grep for
      naked raises in nodes; the task wrapper catch-all is the only FAILED writer).

## Verification gate

```
$ uv run poe verify && uv run poe test-graph              → green (old + new)
$ python -m demoworld.inject --scenario S3                → WAITING_APPROVAL, approve, RESOLVED
$ curl -s localhost:8080/api/incidents/<id>/spans | jq \
  '[.[] | select(.kind=="node" and (.name|startswith("node.log_analyst","node.metrics_analyst","node.change_analyst")))] | map({name, started_at, ended_at})'
        → time windows overlap
$ uv run poe verify-all                                    → green (regression checkpoint)
```

**Gotchas:** 08 #20 (never interrupt inside fan-out), #21 (state bloat: findings only).
**Out of scope:** UI, evals.
