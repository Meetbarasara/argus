# M06 — Human-in-the-Loop (interrupt, approve, modify, take over)

**Objective:** replace M05's WAITING_APPROVAL hold with real LangGraph interrupts:
the graph pauses mid-execution, a human decides via the API (approve / modify /
reject / take over), and the graph resumes from its checkpoint exactly where it
stopped. All five escalation levels behave per 04's edge table.

**Read first:** 04 §1 (human_approval + take_over edges), 03 §1 (approvals),
03 §4 (decision endpoint), 08 #18–#20.
**Prerequisites:** M05 green.

## Deliverables

| Path | Responsibility |
|---|---|
| `graph/nodes/human_approval.py` | creates approvals row (context payload per 03 §1: hypothesis, evidence excerpts, memory refs, plan summary) then `interrupt(payload)`; on resume receives the decision dict and routes per edge table |
| `graph/nodes/take_over.py` | same interrupt pattern; context = full investigation package; resume payload = human's takeover_resolution |
| `worker/tasks.py` | run_incident v2: detect `__interrupt__` in result → ensure approvals row + WAITING_APPROVAL/TAKEN_OVER status → return. `resume_incident(incident_id, approval_id)`: idempotency check (08 #19) → `graph.invoke(Command(resume=payload), thread_id)` → same outcome handling |
| `api/routers/approvals.py` | GET queue; POST decision: atomic PENDING→decided flip (08 #19), `modify` ⇒ validate modified_action against tool arg schema + re-run risk_gate (rejecting modifications that *raise* the risk level beyond what was approved-for), enqueue resume; `ack` for NOTIFY rows |
| `api/routers/incidents.py` | + POST takeover_resolution (03 §4): closes TAKEN_OVER incident, records human resolution (postmortem picks it up in M07) |
| NOTIFY path | risk_gate NOTIFY continues without pause but inserts the informational approvals row (status AUTO) — already partially in M05; finish + test ack |
| tests | integration (`tests/integration/test_hitl.py`; the live worker runs with `LLM_MODE=fake` + checked-in scripts so the suite is deterministic — see 05/M03): S3-shaped run → PENDING approval → (i) approve ⇒ resumes ⇒ remediates ⇒ RESOLVED; (ii) reject with comment ⇒ replan (comment visible in next plan prompt) and remediation_attempts incremented; (iii) modify (change target param) ⇒ modified action executed verbatim + audit shows modified_by; (iv) double-decision ⇒ second gets 409; (v) duplicate resume task ⇒ no-op; (vi) take_over ⇒ takeover_resolution closes incident. Unit: modify re-gate logic. |

## Steps

1. Interrupt round-trip in isolation: a 3-node toy graph test proving
   invoke → interrupt → checkpoint → `Command(resume)` continues (de-risks 08 #18
   before touching the real graph).
2. human_approval + take_over nodes; wire edges per 04.
3. Task v2 (interrupt detection + resume task).
4. Approvals API with atomic flip + modify re-gating.
5. Integration suite (i)–(vi).
6. Live: S3 end-to-end — approve via curl and watch rollback + recovery; then S3
   again with reject → observe replan.

## Acceptance criteria

- [ ] Pause survives worker restart: pause, `docker compose restart worker`, approve —
      resume still works (checkpoint durability proven; add to integration suite).
- [ ] Decision endpoint is race-safe (409 on double decide) and resume idempotent.
- [ ] Modify path can never lower scrutiny: re-gated level must be ≤ the approved
      level or the modification is rejected 422.
- [ ] Every human interaction emits a `human` span with decision + latency
      (human_review_time visible in trace).
- [ ] All escalation levels reachable and correct per 04's edge table.

## Verification gate

```
$ uv run poe verify && docker compose run --rm tester pytest tests/integration/test_hitl.py -q   → green
$ python -m demoworld.inject --scenario S3          → incident WAITING_APPROVAL
$ docker compose restart worker                     → (durability check)
$ curl -s localhost:8080/api/approvals?status=PENDING | jq '.[0] | {level, proposed_action}'
        → APPROVE_ACTION + rollback_deploy of the injected deploy
$ curl -s -X POST localhost:8080/api/approvals/<id>/decision \
       -d '{"decision":"approve","comment":"lgtm"}'  → 200
$ # poll incident → REMEDIATING → RECOVERED → RESOLVED; world error rate recovered
$ curl -s localhost:8080/api/incidents/<id>/spans | jq '[.[] | select(.kind=="human")] | length'  → ≥1
```

**Gotchas:** 08 #18–#20. **Out of scope:** UI (M10) — curl/HTTPie is the interface here.
