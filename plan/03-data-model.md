# 03 — Data Model, File Formats, Configs, API

> Single source of truth. Milestones cite this doc; nothing redefines these shapes.
> All timestamps are timezone-aware UTC ISO-8601. All ids are `uuid4` strings unless noted.

## 1. Platform database (Postgres `argus`, SQLAlchemy 2 + Alembic)

### incidents
| Column | Type | Notes |
|---|---|---|
| id | uuid pk | also the LangGraph `thread_id` |
| trace_id | text nullable | OTel trace id, written when the root span opens at intake |
| created_at / updated_at | timestamptz | |
| status | text enum | see state machine below |
| severity | text | `critical` \| `warning` (from alert) |
| title | text | e.g. "High 5xx error rate on shopapi" |
| alert | jsonb | full alert payload (§3) |
| alert_events | jsonb[] | deduped repeat alerts appended here |
| root_cause | text nullable | final hypothesis root cause |
| confidence | float nullable | final hypothesis confidence 0–1 |
| remediation | jsonb nullable | executed RemediationAction + result |
| escalation_level | text nullable | highest level reached |
| memory_used | bool default false | recall returned ≥1 memory |
| fast_path | bool default false | similarity fast-path hint fired |
| resolved_at | timestamptz nullable | |
| mttr_seconds | int nullable | resolved_at − created_at |
| llm_calls / tool_calls_count | int default 0 | denormalized counters |
| tokens_in / tokens_out | int default 0 | |
| cost_usd | numeric(10,6) default 0 | list-price cost |
| eval_case_id | uuid nullable | set when run by the eval harness |

**Status state machine** (only these transitions):
`OPEN → INVESTIGATING → (WAITING_APPROVAL ⇄ INVESTIGATING) → REMEDIATING →
RECOVERED → RESOLVED`, plus `→ TAKEN_OVER` (from any active state) and `→ FAILED`
(unhandled error). `RESOLVED`, `TAKEN_OVER`, `FAILED` are terminal.
`RECOVERED` = remediation verified; `RESOLVED` = postmortem written.

### approvals
| Column | Type | Notes |
|---|---|---|
| id | uuid pk | |
| incident_id | uuid fk | |
| created_at / decided_at | timestamptz | |
| level | text | NOTIFY \| APPROVE_ACTION \| APPROVE_PLAN \| TAKE_OVER |
| status | text | PENDING \| APPROVED \| REJECTED \| MODIFIED \| AUTO \| ACK |
| proposed_action | jsonb | RemediationAction (04 §schemas) |
| context | jsonb | {hypothesis, evidence_excerpts[], memory_refs[], plan_summary} |
| decided_by | text | `human` \| `policy_sim` (eval mode) |
| decision_comment | text nullable | |
| modified_action | jsonb nullable | when status=MODIFIED |

NOTIFY rows are created as status `AUTO` (informational feed) and can be `ACK`ed from
the UI. TAKE_OVER rows stay PENDING until the human posts a takeover resolution.

### spans
| Column | Type | Notes |
|---|---|---|
| span_id | text pk | OTel hex span id |
| trace_id | text index | OTel hex trace id |
| incident_id | uuid fk index | denormalized for fast lookup |
| parent_span_id | text nullable | |
| name | text | e.g. `node.plan`, `llm.supervisor`, `tool.search_logs` |
| kind | text | node \| llm \| tool \| policy \| human \| world |
| status | text | OK \| ERROR |
| started_at / ended_at | timestamptz | |
| duration_ms | int | |
| attrs | jsonb | agent, model, tokens, cost_usd, confidence, verdict, etc. |

### llm_calls
| Column | Type | Notes |
|---|---|---|
| id | uuid pk; span_id text; incident_id uuid nullable | eval judge calls have no incident |
| role | text | supervisor \| log_analyst \| metrics_analyst \| change_analyst \| reviewer \| memory_writer \| judge |
| provider / model | text | |
| messages | jsonb | full prompt messages |
| response | jsonb | raw text + parsed structured output |
| tokens_in / tokens_out | int | from provider usage metadata |
| cost_usd | numeric(10,6) | list price via config/prices.yaml |
| latency_ms | int; validation_retries int default 0 | |
| mode | text | live \| record \| replay |
| cache_key | text index | sha256(role + model + canonical messages) |
| created_at | timestamptz | |

### tool_calls
id uuid pk · span_id · incident_id · agent text · tool text · args jsonb ·
result jsonb (truncated to 8KB) · status OK|ERROR · error text nullable ·
latency_ms int · created_at.

### memories
| Column | Type | Notes |
|---|---|---|
| id | uuid pk | |
| kind | text | incident_pattern \| lesson \| env_fact |
| title | text | |
| content | text | the lesson/summary injected into prompts |
| fingerprint | jsonb | {alert_rule, services[], error_templates[]} |
| embedding | vector(384) | HNSW index, cosine |
| importance | float default 1.0 | decays on consolidation |
| use_count | int default 0; last_used_at timestamptz nullable | |
| source_incident_id | uuid nullable | |
| created_at | timestamptz; superseded_by uuid nullable | set by consolidation |

### eval_runs / eval_cases
`eval_runs`: id · started_at · finished_at · suite text · config jsonb
(memory_enabled, model overrides, llm_mode) · git_sha · notes.
`eval_cases`: id · run_id fk · scenario_id text (e.g. `S3-v2`) · incident_id ·
rca_correct bool · rca_judge_reason text · remediation_correct bool ·
recovered bool · escalation_expected text · escalation_actual text ·
escalation_correct bool · llm_calls int · tokens int · cost_usd · mttr_seconds ·
outcome text PASS|PARTIAL|FAIL · created_at.
(PASS = all four booleans true; PARTIAL = rca_correct but something else failed.)

LangGraph's Postgres checkpointer additionally creates its own tables via `.setup()`
— leave them untouched.

**Indexes:** incidents(status), incidents(created_at desc), spans(incident_id),
spans(trace_id), llm_calls(cache_key), llm_calls(incident_id),
memories embedding hnsw (vector_cosine_ops), approvals(status).

## 2. Worldstate volume layout & file formats

```
worldstate/
├── logs/{shopapi,paymentsvc}.jsonl      appended by services
├── metrics/metrics.jsonl                appended by poller
├── deploys/history.jsonl                appended by actuator
├── deploys/snapshots/<svc>/<deploy_id>.json
├── deploys/actions.jsonl                actuator audit (restarts, chaos)
├── config/{shopapi,paymentsvc}.json     live config, hot-reloaded by services
└── alerts/sent.jsonl                    every alert alertwatch fired (test oracle)
```

**Log line** (fields beyond the first four are optional):
```json
{"ts":"2026-07-05T10:31:02.113Z","service":"shopapi","level":"ERROR","msg":"payment call failed",
 "path":"/checkout","status":502,"latency_ms":31,"err_type":"ConnectError","request_id":"r-9f2c"}
```

**Metric line** — poller hits each service's `/internal/stats` every 5s and writes one
line per metric:
```json
{"ts":"...","service":"shopapi","name":"err_rate_60s","value":0.42,"labels":{}}
```
Metric names (fixed set): `req_count_60s`, `err_rate_60s` (0–1, 5xx/total),
`latency_p95_ms_60s`, `dep_up` (labels: `{"dep":"redis"|"payment"|"db"}`, value 0/1),
`db_pool_in_use`, `db_pool_size`.

**`/internal/stats` response** (each demo service maintains a rolling 60s window
in-process): `{req_count_60s, err_count_60s, err_rate_60s, latency_p95_ms_60s,
deps:{redis:"up"|"down", payment:"up"|"down", db:"up"|"down"},
db_pool:{in_use,size}, config_version}`.

**Deploy history entry:**
```json
{"deploy_id":"d-0042","ts":"...","service":"shopapi","author":"injector|agent|human",
 "message":"Point checkout at new payment endpoint",
 "changes":{"payment_url":{"old":"http://paymentsvc:8002","new":"http://paymentsvc:9999"}},
 "snapshot_before":"snapshots/shopapi/d-0041.json","snapshot_after":"snapshots/shopapi/d-0042.json"}
```
`deploy_id` is a monotonically increasing `d-XXXX` per world reset.

**Service config file** (`config/shopapi.json` — canonical keys):
`{version:"d-0042", payment_url, db_pool_size:10, cache_enabled:true,
feature_flags:{recs_v2:false}, request_timeout_ms:2000}`.
`config/paymentsvc.json`: `{version, base_latency_ms:40}`. Chaos latency (S2) is
**in-memory only** — set via the service's `POST /admin/chaos` (proxied by the
actuator), never via config/deploys. That preserves S2's "no deploy" signature and
makes a service restart genuinely clear it.

**Alert payload** (webhook body AND the line in alerts/sent.jsonl):
```json
{"alert_id":"a-7f3e","rule":"high_error_rate","service":"shopapi","severity":"critical",
 "ts":"...","window_seconds":60,"observed":{"metric":"err_rate_60s","value":0.42,"threshold":0.2},
 "summary":"shopapi err_rate_60s=0.42 breached threshold 0.2 for 2 consecutive checks"}
```

## 3. Config files (`config/`)

**models.yaml**
```yaml
providers:
  gemini: {env_key: GOOGLE_API_KEY, rpm: 9}    # keep 1 below the published free limit
  groq:   {env_key: GROQ_API_KEY,   rpm: 25}
roles:   # every role used by the platform must appear here
  supervisor:      {provider: gemini, model: gemini-2.5-flash}
  reviewer:        {provider: gemini, model: gemini-2.5-flash}
  log_analyst:     {provider: groq,   model: llama-3.3-70b-versatile}
  metrics_analyst: {provider: groq,   model: llama-3.3-70b-versatile}
  change_analyst:  {provider: groq,   model: llama-3.3-70b-versatile}
  memory_writer:   {provider: groq,   model: llama-3.3-70b-versatile}
  judge:           {provider: gemini, model: gemini-2.5-flash}
```
Model ids are *defaults*; M03 verifies current free-tier ids live and records the
final choice in PROGRESS. Env overrides: `ARGUS_MODEL__<ROLE>` (e.g.
`ARGUS_MODEL__SUPERVISOR=groq:llama-3.3-70b-versatile`).

**policy.yaml**
```yaml
target_classes: {shopredis: cache, shopdb: database, shopapi: service, paymentsvc: service}
actions:
  restart_service: {cache: NOTIFY, service: APPROVE_ACTION, database: APPROVE_PLAN}
  rollback_deploy: {default: APPROVE_ACTION}
confidence_overrides:      # applied after action level; the stricter wins
  - {below: 0.60, at_least: APPROVE_ACTION}
  - {below: 0.35, level: TAKE_OVER}
limits: {max_remediation_attempts: 2, max_review_loops: 2,
         max_llm_calls_per_incident: 40, max_wall_seconds_per_incident: 420}
```
Level strictness order: AUTO < NOTIFY < APPROVE_ACTION < APPROVE_PLAN < TAKE_OVER.

**alert_rules.yaml**
```yaml
rules:
  - {name: high_error_rate, metric: err_rate_60s,    op: ">", threshold: 0.20, for_checks: 2, severity: critical}
  - {name: high_latency_p95, metric: latency_p95_ms_60s, op: ">", threshold: 1500, for_checks: 2, severity: warning}
  - {name: dependency_down, metric: dep_up,          op: "==", threshold: 0,   for_checks: 2, severity: critical}
evaluation_interval_seconds: 10
refire_cooldown_seconds: 600   # per (rule, service)
```

**prices.yaml** — `{provider:{model:{in_per_mtok: float, out_per_mtok: float}}}`;
unknown model ⇒ cost 0 with a WARN log.

**Scenario yaml** (`evals/scenarios/S3-v1.yaml`):
```yaml
id: S3-v1
scenario: bad_deploy_env        # injector scenario key
params: {decoy_deploys: 1, warmup_seconds: 30}
expected:
  root_cause_label: "A deploy changed shopapi's payment_url to an unreachable endpoint, causing checkout 502s"
  root_cause_keywords: [payment_url, deploy, shopapi]   # judge fallback
  remediation: {tool: rollback_deploy, target_service: shopapi}
  escalation_level: APPROVE_ACTION
budgets: {max_llm_calls: 40, max_wall_seconds: 420}
```

## 4. REST API (platform, all under `/api`)

| Method & path | Purpose / body → response |
|---|---|
| POST `/alerts/webhook` | alert payload → 201 `{incident_id}` (new) or 200 `{incident_id, deduped:true}`. Dedupe is **service-level**: while a non-terminal incident exists for the alert's service, new alerts (any rule) append to its `alert_events` — one fault often breaches several rules |
| GET `/incidents?status=&limit=50` | list, newest first (summary fields) |
| GET `/incidents/{id}` | full record + approvals + counters + timeline (status changes) |
| GET `/incidents/{id}/spans` | flat span list ordered by started_at (UI builds the tree via parent_span_id) |
| GET `/llm_calls/{id}` | full prompt/response drill-down |
| GET `/approvals?status=PENDING` | queue for the UI |
| POST `/approvals/{id}/decision` | `{decision: approve\|reject\|modify\|ack, comment?, modified_action?}` → 200; enqueues resume; `modify` revalidates args against the tool schema and re-runs the risk gate |
| POST `/incidents/{id}/takeover_resolution` | `{root_cause, action_taken}` → closes TAKEN_OVER incident, still writes a memory |
| GET `/memories?query=&kind=` | list; `query` does vector search, else recency |
| DELETE `/memories/{id}` | user-data delete story |
| POST `/memories/consolidate` | runs consolidation, returns `{merged, decayed}` |
| GET `/dashboard/summary` | totals: incidents by status, resolution rate, escalation rate, avg MTTR, cost, tokens-by-role, per-incident cost list |
| GET `/evals/runs`, GET `/evals/runs/{id}` | run list / run detail with cases |
| GET `/health` | `{status, db, redis, worldstate_mounted, config:{llm_mode, auto_approve, memory_enabled, supervisor_model}}` — the config echo lets the eval runner verify active settings |

Conventions: FastAPI + Pydantic response models everywhere; errors are
`{"detail": str}` with correct 4xx/5xx; no auth (non-goal).

## 5. Actuator API (demo world, port 8010, header `X-Actuator-Token`)

| Endpoint | Behavior |
|---|---|
| POST `/restart` `{service}` | docker restart by compose service name; audit line |
| POST `/deploy` `{service, changes, message, author}` | write new config + snapshot + history entry |
| POST `/rollback` `{deploy_id, author}` | restore `snapshot_before`; writes a *new* history entry `author:"rollback"` |
| GET `/deploys?service=&limit=` | history entries, newest first |
| GET `/actions?limit=` | audit log (restarts, chaos) |
| POST `/chaos` `{service, extra_latency_ms}` | S2 only (injector uses it; agents don't get a chaos tool) |
| GET `/tail?file=alerts/sent.jsonl&last=50` | read-only debug tail of a **whitelisted** worldstate file (tests & demos read the named volume through this) |
| GET `/health` | 200 |

## 6. Ports & env vars

Ports: api 8080 · ui 8081 · platform postgres 5433 · platform redis 6380 ·
shopapi 8001 · paymentsvc 8002 · actuator 8010 · shopdb 5434 · jaeger 16686.

`.env.example` (checked in; `.env` gitignored):
```
GOOGLE_API_KEY=            # https://aistudio.google.com (free, no card)
GROQ_API_KEY=              # https://console.groq.com (free, no card)
ACTUATOR_TOKEN=dev-actuator-token
LLM_MODE=live              # live | record | replay | fake (scripted; deterministic tests)
AUTO_APPROVE=off           # off | policy_sim   (policy_sim only for eval runs)
MEMORY_ENABLED=true
DATABASE_URL=postgresql+psycopg://argus:argus@localhost:5433/argus   # host-side tools
PLATFORM_API_URL=http://localhost:8080
OTEL_EXPORT_JAEGER=false
```
In-container URLs use compose service names (`postgres`, `redis`, `actuator`); settings.py
(pydantic-settings) is the only place env vars are read.
