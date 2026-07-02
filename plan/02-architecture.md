# 02 — Architecture

## System diagram

```mermaid
flowchart LR
  subgraph WORLD["Demo world (profile: world)"]
    LG[loadgen] --> SA[shopapi :8001]
    SA --> PS[paymentsvc :8002]
    SA --> SDB[(shopdb)]
    SA --> SR[(shopredis)]
    SA -. writes logs .-> WS[(worldstate volume)]
    PS -. writes logs .-> WS
    TP[telemetry-poller] -. metrics.jsonl .-> WS
    AW[alertwatch] -. reads .-> WS
    ACT[actuator :8010] -. deploys/config/audit .-> WS
    ACT -- docker socket --> DOCKER[(Docker engine)]
  end

  subgraph PLATFORM["Argus platform (profile: platform)"]
    API[api :8080]
    WK[worker celery]
    PG[(postgres+pgvector :5433)]
    RD[(redis :6380)]
    UI[ui nginx :8081]
  end

  AW -- alert webhook --> API
  API -- enqueue --> RD --> WK
  WK -- LangGraph run --> PG
  WK -- read-only --> WS
  WK -- remediation calls --> ACT
  WK -- LLM APIs --> EXT[Gemini / Groq free tiers]
  UI -- polls REST --> API
  WK -. OTLP (optional profile) .-> JG[jaeger :16686]
```

## Data flows (the four that matter)

1. **Alert → incident.** alertwatch evaluates rules over worldstate every 10s → POST
   `/api/alerts/webhook` → API dedupes (non-terminal incident for the same *service* ⇒
   append event, don't create — one fault often breaches several rules) → inserts
   `incidents` row (OPEN) → enqueues Celery task
   `run_incident(incident_id)` → worker runs the LangGraph graph synchronously with
   `thread_id = incident_id` and the Postgres checkpointer.
2. **Approval pause/resume.** Graph hits `human_approval` → `interrupt()` →
   checkpoint persisted, Celery task returns, incident status WAITING_APPROVAL,
   `approvals` row PENDING. Human decides via `POST /api/approvals/{id}/decision` →
   API validates + stores decision → enqueues `resume_incident(incident_id)` → worker
   re-invokes the graph with `Command(resume=<decision>)` on the same thread_id →
   execution continues from the exact paused node. Resume is idempotent: the task
   re-checks approval status before resuming.
3. **Memory loop.** `postmortem` node distills the incident into a memory (title,
   lesson, fingerprint) → embed locally (fastembed) → insert into `memories`
   (pgvector). Next incident's `recall_memory` node embeds the alert context, pulls
   top-5 scored memories, injects them into the planning prompt, and bumps
   `use_count`.
4. **Evaluation.** Host-side CLI (`python -m argus.evals.run`) resets the world,
   injects a scenario, waits for the incident to reach a terminal state via the API,
   grades it (deterministic checks + LLM judge), writes `eval_runs`/`eval_cases`,
   regenerates `EVALUATION.md`.

## Containers, ports, volumes, profiles

| Service | Profile | Image / build | Host port | Notes |
|---|---|---|---|---|
| api | platform | `docker/platform.Dockerfile` | 8080 | FastAPI (uvicorn), serves REST |
| worker | platform | same image, celery cmd | – | mounts `worldstate` **read-only** |
| postgres | platform | `pgvector/pgvector:pg16` | 5433 | platform DB `argus` |
| redis | platform | `redis:7-alpine` | 6380 | Celery broker + rate-limit buckets |
| ui | platform | `docker/ui.Dockerfile` (nginx) | 8081 | serves React build, proxies `/api` → api |
| jaeger | observability | `jaegertracing/all-in-one` | 16686 | optional |
| shopapi | world | `docker/demoworld.Dockerfile` | 8001 | |
| paymentsvc | world | same image | 8002 | |
| shopdb | world | `postgres:16-alpine` | 5434 | debug access only |
| shopredis | world | `redis:7-alpine` | – | internal; stopped by S1 |
| loadgen | world | same demoworld image | – | continuous traffic |
| poller | world | same demoworld image | – | writes metrics.jsonl |
| alertwatch | world | same demoworld image | – | posts webhooks; logs all alerts to worldstate |
| actuator | world | same demoworld image | 8010 | mounts docker socket + `worldstate` rw; token auth |

- **Volumes:** `worldstate` (named volume; logs/, metrics/, deploys/, config/, alerts/),
  `pgdata_platform`, `pgdata_shop`.
- **Network:** one compose network; platform reaches `actuator:8010` by service name.
- All services define healthchecks; compose `depends_on: condition: service_healthy`.

## Repository layout

```
argus/  (repo root — recommend renaming folder from "Agentic project"; see M00)
├── CLAUDE.md, README.md, EVALUATION.md (generated), INTERVIEW_NOTES.md (M12)
├── pyproject.toml, uv.lock, .gitattributes, .gitignore, .env.example
├── docker-compose.yml
├── docker/            platform.Dockerfile, demoworld.Dockerfile, ui.Dockerfile
├── config/            models.yaml, policy.yaml, alert_rules.yaml, prices.yaml
├── plan/              this plan (immutable except PROGRESS.md)
├── src/
│   ├── argus/         platform package
│   │   ├── settings.py            pydantic-settings, all env in one place
│   │   ├── api/                   FastAPI app + routers (alerts, incidents, approvals, memories, dashboard, evals, health)
│   │   ├── worker/                celery app + tasks (run_incident, resume_incident)
│   │   ├── graph/                 state.py, nodes/, build.py (compiled graph), checkpointer.py
│   │   ├── agents/                prompts.py, supervisor.py, specialists.py, reviewer.py, memory_writer.py, judge.py
│   │   ├── llm/                   router.py, ratelimit.py, recorder.py, costs.py, schemas helpers
│   │   ├── tools/                 registry.py, telemetry_tools.py, change_tools.py, remediation_tools.py
│   │   ├── memory/                vectorstore.py (interface), pgvector_store.py, embedder.py, recall.py, fingerprint.py, consolidate.py
│   │   ├── policy/                risk_gate.py (deterministic), policy_loader.py
│   │   ├── obs/                   otel.py (setup), pg_exporter.py, spans.py (helpers)
│   │   ├── db/                    models.py (SQLAlchemy), session.py, migrations/ (alembic)
│   │   ├── repo/                  incidents.py — status-machine-enforcing repository (only writer of incident status)
│   │   └── evals/                 run.py (CLI), grade.py, report.py
│   └── demoworld/
│       ├── common/                jsonlog.py, hotconfig.py, stats.py (rolling window)
│       ├── shopapi/app.py, paymentsvc/app.py
│       ├── loadgen.py, poller.py, alertwatch.py
│       ├── actuator/app.py, actuator/docker_ops.py, actuator/deploys.py
│       └── inject.py              fault injector CLI (drives actuator + docker)
├── ui/                            Vite + React + TS + Tailwind (see 05 for conventions)
├── evals/scenarios/               S1-v1.yaml … S5-v3.yaml
└── tests/                         unit/, integration/, graph/, e2e/  (markers in 05)
```

## Architecture Decision Records

**ADR-01 — pgvector, not a dedicated vector DB.** Memory is <100k vectors; Postgres is
already present. One less service/account, offline demo, and honest engineering
judgment to defend in interviews. A thin `VectorStore` interface (`memory/vectorstore.py`)
keeps Pinecone a one-file adapter if ever wanted.

**ADR-02 — Deploys are hot-reloaded config files, not container restarts.** Demo-world
services re-read `worldstate/config/<svc>.json` every 5s. A "deploy" = actuator writes
a new config + history entry; rollback = restore previous snapshot. Deterministic,
instant, no orchestration complexity, and it gives the change_analyst a clean audit
trail. Container restarts remain a separate remediation (S1/S2).

**ADR-03 — Actuator is the single privileged choke point.** Only the actuator holds the
docker socket and write access to config/deploys. Platform tools call its
token-authenticated HTTP API. Every action is written to an audit log the agents can
read. Talking point: agents get *capabilities*, not *credentials*.

**ADR-04 — The risk gate is deterministic code, not an LLM.** `policy.yaml` maps
(action × target class × confidence band) → escalation level. The LLM proposes; policy
disposes. An LLM must never authorize its own risky action.

**ADR-05 — Record/replay is built into the LLM layer from day one.** Every call is
cache-keyed (role+model+messages). `record` fills the cache from live calls; `replay`
serves tests/demos deterministically with zero quota. This makes graph tests
deterministic, protects the live demo, and stretches free tiers.

**ADR-06 — The graph runs synchronously inside Celery.** No asyncio-in-Celery. Sync
LangGraph + sync checkpointer + prefork workers (in Linux containers) is the boring,
reliable choice. Parallel specialists come from LangGraph's Send API, not asyncio.

**ADR-07 — One instrumentation, two span sinks.** Code emits OpenTelemetry spans once;
a custom PostgresSpanExporter writes them to the `spans` table (powers our UI and
dashboards, joins to `llm_calls`/`tool_calls`), and an optional OTLP exporter feeds
Jaeger for the industry-standard view.

**ADR-08 — UI polls; no websockets.** TanStack Query with 2–3s refetch on active pages.
Incidents last minutes; polling is indistinguishable in the demo and removes a whole
failure class.

**ADR-09 — World telemetry is files (JSONL), not Prometheus/Loki.** The monitored
world writes structured JSONL to a shared volume; tools read files. Deterministic,
seedable, testable, zero extra infra. The *platform's* own telemetry is the
full-featured part (OTel) — effort goes where the resume value is.

**ADR-10 — Local embeddings via fastembed.** bge-small-en-v1.5 (384-dim, ONNX, no
torch): small image, no API, no rate limits. Model files are baked into the worker
image at build time so runtime is offline.

## Security posture (worth one interview minute)

- Mutating tools (`restart_service`, `rollback_deploy`) are executable **only** by the
  `remediate` node after the risk gate — enforced in the tool executor (checks
  execution context), not merely by prompts.
- Actuator requires `X-Actuator-Token`; the token never appears in logs or LLM prompts.
- The worker mounts worldstate read-only; only the actuator writes to it.
- Secrets live in `.env` (gitignored); prompts/log records are scrubbed of env values.
- The demo world is fully containerized and isolated — fault injection can't touch the host.
