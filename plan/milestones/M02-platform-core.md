# M02 — Platform Core (API, DB, Celery, intake)

**Objective:** the platform skeleton that everything plugs into: FastAPI app, full
database schema via Alembic, Celery wiring, and the alert-webhook → incident → queued
task pipeline. After this milestone an alert from the world creates a real incident
row and a worker picks it up (and, for now, just marks it INVESTIGATING → FAILED with
"graph not implemented" — proving the pipe end to end).

**Read first:** 02 (platform containers, flow 1), 03 §1 (all tables), 03 §4 (REST),
03 §6 (env), 08 #8–#10.
**Prerequisites:** M00–M01 green; platform postgres/redis healthy.

## Deliverables

| Path | Responsibility |
|---|---|
| `src/argus/db/models.py` | SQLAlchemy models for **every** table in 03 §1 (all now — later milestones only use them, so schema churn stays here) |
| `src/argus/db/session.py` | engine/session factory from settings |
| `src/argus/db/migrations/` | Alembic env + migration 0001: `CREATE EXTENSION vector`, all tables, all indexes incl. HNSW (08 #8) |
| `src/argus/api/app.py` | FastAPI factory: routers, CORS-when-dev (08 #25), exception handlers per 05; container entrypoint runs `alembic upgrade head` before uvicorn (idempotent) |
| `src/argus/api/routers/alerts.py` | POST webhook: validate payload (03 §2 alert shape), dedupe via partial unique index (08 #10), create incident OPEN, enqueue `run_incident` |
| `src/argus/api/routers/incidents.py` | GET list/detail (03 §4 shapes); spans + llm_calls detail endpoints return empty lists until M03+ populate them |
| `src/argus/api/routers/health.py` | db, redis, worldstate-mount checks |
| `src/argus/worker/app.py` | Celery app (redis broker/backend, task_acks_late, prefetch 1) |
| `src/argus/worker/tasks.py` | `run_incident(incident_id)` v0: set INVESTIGATING, log, set FAILED with status_reason "graph not implemented (M05)"; `resume_incident` stub raising NotImplementedError |
| `src/argus/repo/incidents.py` | incident_repo: status transitions **enforcing the 03 state machine** (invalid transition ⇒ PolicyError), counter increments |
| tests | unit: state-machine transitions (exhaustive legal/illegal table), alert payload validation, dedupe logic; integration: webhook→row→celery→status flip; alembic upgrade+downgrade+upgrade |

Compose: api + worker services now start (depends_on postgres healthy; worker also
mounts worldstate ro — verified by health endpoint).

## Steps

1. Models + migration 0001 (everything in 03 §1) → `alembic upgrade head` against
   platform postgres; test upgrade → downgrade → upgrade.
2. incident_repo with the state machine + exhaustive unit test.
3. API app + alerts/incidents/health routers + unit tests (TestClient, db fixture).
4. Celery app + v0 tasks; api enqueues by name (no import of worker in api).
5. Wire compose; end-to-end integration test: POST sample S1 alert payload → 201 →
   poll GET /incidents/{id} until status FAILED with the v0 reason (proves broker,
   worker, DB, status pipeline).
6. Dedupe test: with the worker paused (`docker compose stop worker`, so the first
   incident stays non-terminal), POST a second alert for the same service (different
   rule) → 200 deduped, `alert_events` grew, still one open row. Restart the worker after.

## Acceptance criteria

- [ ] Migration is the complete 03 §1 schema (column-for-column) incl. pgvector + HNSW.
- [ ] Illegal status transitions raise; legal ones persist (unit-tested exhaustively).
- [ ] Webhook → incident → worker round trip observable via the API.
- [ ] Dedupe: no second open incident for the same service (any rule).
- [ ] `/api/health` reports db+redis+worldstate ok from inside containers.

## Verification gate

```
$ docker compose --profile platform up -d --build && docker compose ps   → api, worker, postgres, redis healthy
$ uv run alembic upgrade head             → no-op (already applied in container start) / exit 0
$ curl -s localhost:8080/api/health       → {"status":"ok","db":true,"redis":true,"worldstate_mounted":true}
$ curl -s -X POST localhost:8080/api/alerts/webhook -H 'content-type: application/json' \
       -d @tests/fixtures/alert_s1.json   → 201 {"incident_id": "..."}
$ curl -s localhost:8080/api/incidents/<id> | jq .status   → "FAILED" (v0 reason) within 15s
$ uv run poe verify && uv run poe test-integration          → green
```

**Gotchas:** 08 #8–#10. **Out of scope:** any LLM/graph/tool code; approvals endpoints
return 501 stubs (M06); dashboard/memories/evals endpoints return 501 stubs (M07/M09/M11).
Stubs are declared now so the API surface is complete and the UI (M10) has stable paths.
