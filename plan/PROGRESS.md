# Argus Build Progress

> Maintained by the builder. Update at the start and end of every milestone.
> Never mark a milestone `done` with a red gate.

## Milestone status

| # | Milestone | Status | Verify before | Gate after | Commit | Notes |
|---|---|---|---|---|---|---|
| M00 | Scaffold & tooling | done | ✅ 2026-07-03 (empty repo) | ✅ 2026-07-05 poe verify + all 4 docker gates | 827ea31 | Complete — Docker installed, full gate green |
| M01 | Demo world | done | ✅ 2026-07-05 | ✅ 2026-07-05 poe verify (45) + world gate 5/5 passed (554s) | 141696a + gate | Complete — all 5 scenarios produce evidence + recover |
| M02 | Platform core | todo | – | – | – | |
| M03 | LLM layer | todo | – | – | – | |
| M04 | Tool layer | todo | – | – | – | |
| M05 | Graph v1 | todo | – | – | – | |
| M06 | Human-in-the-loop | todo | – | – | – | |
| M07 | Memory | todo | – | – | – | |
| M08 | Parallelism & resilience | todo | – | – | – | |
| M09 | Observability | todo | – | – | – | |
| M10 | React UI | todo | – | – | – | |
| M11 | Evaluation harness | todo | – | – | – | |
| M12 | Demo & docs | todo | – | – | – | |

Status values: `todo` → `in_progress` → `done` (or `blocked` with an Open question).
"Verify before" / "Gate after": ✅ + date, or ❌ + link to note.

## Gate evidence log

> One short entry per completed milestone: the exact commands run and the observed
> result (paste key output lines, not walls of text).

<!-- Example:
### M01 — 2026-07-05
- `docker compose --profile world up -d` → 8/8 healthy
- `python -m demoworld.inject --scenario S1` → alert `high_error_rate/shopapi` in
  worldstate/alerts/sent.jsonl after 41s; shopapi log shows 37 ConnectError lines
- `pytest -m world` → 12 passed
-->

### M00 — 2026-07-03 (partial: docker items pending)
- Ran: `uv run poe fmt` then `uv run poe verify` → ruff format ✅, ruff check ✅,
  `mypy src` ✅ (3 files), `pytest -m unit` ✅ (2 passed).
- Delivered: git repo (commit 1 = .gitattributes/.gitignore), pyproject + uv.lock
  (all runtime + dev deps), settings.py + unit tests, all 4 config/ yamls,
  .env.example + .env, docker-compose.yml (all services, profiles, healthchecks,
  `name: argus`), 3 Dockerfiles (platform has `dev` target for tester), .dockerignore.
- **2026-07-05 — Docker gate completed** (Docker Desktop + WSL2 installed on host):
  - `docker compose config --quiet` → CONFIG_OK
  - `docker compose --profile platform up -d postgres redis` → `argus-postgres-1`,
    `argus-redis-1` both **healthy** (project name pinned to `argus`)
  - `docker compose build api shopapi` → `argus-api:latest` + `argus-shopapi:latest`
    built, exit 0 (uv sync --frozen works in-container; Dockerfiles + lock validated)
  - **M00 now fully done.**

### M01 — 2026-07-03 (partial: common/ trio only; services Docker-blocked)
- Built the M01 step-1 foundation: `demoworld/common/` — `jsonlog.py` (03 §2 records +
  rotation + torn-line-safe `read_jsonl`), `hotconfig.py` (ADR-02 hot reload, keeps
  last-known on missing/malformed), `stats.py` (rolling-60s window, nearest-rank p95,
  injectable clock), `settings.py` (worldstate/env accessors).
- Ran: `uv run poe verify` → ruff ✅, `mypy src` ✅ (8 files), `pytest -m unit` ✅
  (**17 passed**: 2 settings + 7 jsonlog + 4 hotconfig + 4 stats). All host-side, no Docker.
- **Pending (Docker Desktop still not installed):** all demo-world services
  (shopapi, paymentsvc, actuator, loadgen, poller, alertwatch), `inject.py`, and the
  entire M01 verification gate (`--profile world up`, `pytest -m world`, scenario
  evidence+recovery). Resume here once Docker is installed.

### M01 — 2026-07-05 (paymentsvc service, Docker now available)
- Built `seed/defaults.py` (baseline configs + 20-product seed + `ensure_config`
  self-bootstrap) and `paymentsvc` (factory-mode FastAPI: /health, /pay, /internal/stats,
  /admin/chaos). Compose command switched to `--factory` for testability.
- Host: `uv run poe verify` green — 22 unit tests (5 new paymentsvc via TestClient).
- Live smoke (built image + `up -d paymentsvc`): /health ok; /pay baseline 40ms;
  /internal/stats correct 03 §2 shape (config_version d-0000); **S2 mechanism verified** —
  chaos 3000ms → /pay took 3.05s (latency_ms 3040) → reset to 0. Fixed a robustness bug
  found in smoke (/pay 422'd without JSON content-type → dropped the unused body param).
- Next: `shopapi` (DB pool + cache + checkout→paymentsvc; needs psycopg-pool dep), then
  poller/loadgen, actuator, alertwatch, inject, and the 5-scenario world gate.

### M01 — 2026-07-05 (shopapi service)
- Added psycopg-pool dep; settings `shopdb_url()`/`shopredis_url()`; `shopapi` (factory,
  sync handlers in threadpool): /health, /products (live inventory DB check + cache-first
  catalog), /checkout (→paymentsvc with request_timeout_ms), /internal/stats (deps +
  db_pool + config_version). Startup seeds the products table (20 rows, idempotent retry).
  Pool sized from `db_pool_size`, rebuilt on config change (S4 lever = DB_WORK_SECONDS 0.15
  hold + POOL_ACQUIRE_TIMEOUT 0.75; final tuning at world-gate time with loadgen).
- Host: `uv run poe verify` green (22 tests; mypy caught a redis Awaitable-union → cast fix).
- Live smoke (world up: shopdb+shopredis+shopapi+paymentsvc): /products returns 20 rows;
  /checkout 200 via paymentsvc; deps all up; pool size 10.
- **S1 verified live**: stop shopredis → /products 500 `ConnectionError`, dep redis=down,
  error line written to worldstate/logs/shopapi.jsonl (correct 03 §2 shape); restart → 200.
  S2/S3/S4/S5 mechanisms wired (config-driven), to be exercised via inject at the world gate.
- Next: poller + loadgen (metrics flowing), then actuator, alertwatch, inject, world gate.

### M01 — 2026-07-05 (poller + loadgen: telemetry flowing)
- `jsonlog.append_jsonl` shared helper; `settings.metrics_file()`; `poller` (samples every
  service's /internal/stats every 5s → 03 §2 metric lines; pure `parse_targets` +
  `stats_to_metrics` unit-tested) and `loadgen` (concurrent 70/30 products/checkout mix,
  env-tunable concurrency/think — the S4 load lever).
- Host: `uv run poe verify` green (25 tests; +3 poller).
- Live (world up + poller + loadgen): metrics.jsonl accumulating; after ~18s shopapi
  req_count_60s=176, err_rate 0, latency_p95 154ms, dep_up{redis,payment,db}=1, pool 1/10;
  paymentsvc req_count 54, latency_p95 40ms. All six 03 §2 metric names present.
- Next: actuator (restart/deploy/rollback/chaos/tail/reset), alertwatch, inject, world gate.

### M01 — 2026-07-05 (actuator: the privileged choke point)
- Added `docker` SDK dep. `actuator/deploys.py` (DeployManager: deploy/rollback/list with
  dotted-path changes, before/after snapshots, monotonic d-NNNN ids, atomic config writes)
  — 6 host unit tests. `actuator/docker_ops.py` (restart by compose label, 08 #4).
  `actuator/app.py` (factory, token-guarded: /restart /deploy /rollback /deploys /actions
  /chaos /tail /admin/reset_worldstate; /health open).
- Host: `uv run poe verify` green (31 tests; +6 deploys). mypy needed a type:ignore for
  docker.from_env (not in stubs).
- **Live smoke — all endpoints pass**, incl. the 08 #4 risk: **restart shopredis via the
  Docker socket works** (`restarted: [argus-shopredis-1]`, by-label). 401 without token;
  deploy d-0001 records old→new + snapshots; chaos proxied to paymentsvc; audit log
  captures restart+chaos; rollback d-0002 restores payment_url; tail whitelisted; reset
  clears to baseline (deploys=[]).
- Next: alertwatch (rule engine → alerts), inject.py, and the 5-scenario world gate.

### M01 — 2026-07-05 (alertwatch: alert pipeline live)
- `alertwatch`: loads alert_rules.yaml, evaluates every 10s, fires after `for_checks`
  consecutive breaches with per-(rule,service,dep) cooldown; appends alerts/sent.jsonl +
  best-effort webhook. Pure engine (evaluate_rule/latest_values/check_rules/tick) — 6 unit
  tests. Host: poe verify green (37 tests).
- **Debug win (found by live test, not guessed):** during S1, shopapi `/internal/stats`
  took ~4s (redis-py connection retries + DNS lookup of the stopped host), exceeding the
  poller's 3s timeout → no metrics during the outage → no alert. Fix: redis client
  `retry=Retry(NoBackoff(),0)` + 0.3s timeouts (fast-fail), and poller GET timeout 3→5s.
- **Live S1 end-to-end now fires**: err_rate 0.74, dep_up[redis]=0 → sent.jsonl gets
  dependency_down (critical), high_error_rate, high_latency_p95; recovers on redis restart.
- Note: ~3s residual is DNS resolution of the stopped container name (pre-connect, not
  bounded by socket timeouts); poller's 5s timeout covers it. Acceptable — valid evidence.
- Next: inject.py (fault CLI) + the 5-scenario world gate → finishes M01.

### M01 — 2026-07-05 (inject.py fault CLI)
- Actuator gains `/admin/stop_container` (docker_ops.stop_service) so injection is pure
  HTTP (works from host or tester container; agents never get it — only /restart).
- `inject.py`: `--scenario S1..S5 [--decoy-deploys N] [--warmup-seconds N]`, drives faults
  via the actuator; S1 stop redis, S2 chaos, S3 payment_url deploy, S4 db_pool_size deploy,
  S5 recs_v2 deploy; optional benign decoy deploys precede the fault. 8 host unit tests
  (httpx MockTransport asserts each scenario's endpoint+payload). poe verify green (45).
- Live via CLI from host: S3 → deploy d-0001 (payment_url old→new) in /deploys; S2 → chaos
  3000ms on paymentsvc in /actions; reset clean.
- **Only remaining M01 item: the automated 5-scenario world gate** (tester container:
  reset→inject→assert alert+evidence≤90s→remediate→assert recovery≤120s). Will need S4
  load tuning (pool=2 must exhaust under loadgen; pool=10 must not).

### M01 — 2026-07-05 (WORLD GATE GREEN — M01 DONE)
- `tests/integration/test_scenarios.py` (marker `world`, runs in tester container): per
  scenario reset→inject(apply_fault)→assert expected alert≤90s + evidence→remediate→assert
  recovery (2 consecutive healthy checks)≤130s. `_reset` restarts alertwatch (clears
  cooldown) + shopredis + reseeds baseline.
- **S4 load tuning (the known-hard part):** closed-loop loadgen self-limits, so a saturated
  pool queued but didn't time out. Fix: shopapi `DB_WORK_SECONDS 0.15→0.4`,
  `POOL_ACQUIRE_TIMEOUT 0.75→0.3`, loadgen `LOADGEN_CONCURRENCY=12`. Result: pool=2 crosses
  err_rate 0.2 at ~25s; pool=10 stays 0.0. Baseline /products latency now ~400ms (< 1500).
- **Gate result: `5 passed in 554.78s` (9:14).** S1 ConnectionError+dep down→restart;
  S2 checkout-502 + no-deploy→restart paymentsvc; S3 payment_url deploy→rollback;
  S4 PoolTimeout + db_pool_size deploy→rollback; S5 recs_v2 deploy + /products 500→rollback.
  All recovered. Host `poe verify` green (45).
- **M01 complete.** Next: M02 (platform core — API, DB migrations, Celery, alert intake).

## Deviations log

> Anything done differently from plan/ docs: version bumps, renamed LLM model ids,
> workarounds. Format: date, what, why, impact.

| Date | Deviation | Why | Impact |
|---|---|---|---|
| 2026-07-03 | Folder not renamed to `argus`; compose pinned with `name: argus` instead | Windows locks the CWD of the running session — rename impossible mid-session | None for docker; user may rename folder later when no session is open |
| 2026-07-03 | `readme` field omitted from pyproject | README.md is an M12 deliverable; hatchling build fails on missing file | M12 re-adds the field when it creates README.md |
| 2026-07-03 | Added `.dockerignore` (not in M00 file list) | Keep build contexts small; exclude .env/plan/.venv from images | None |
| 2026-07-05 | shopapi DB_WORK_SECONDS=0.4, POOL_ACQUIRE_TIMEOUT=0.3; loadgen LOADGEN_CONCURRENCY=12 | Make S4 pool exhaustion deterministic under closed-loop load (pool=2 times out, pool=10 clean) | Baseline /products latency ~400ms (well under the 1500ms alert threshold); no behavior change to other scenarios |
| 2026-07-05 | shopapi redis client: no retries + 0.3s timeouts; poller GET timeout 3→5s | During S1, /internal/stats stalled ~4s on redis retries+DNS, exceeding poller timeout → outage missing from metrics | S1 now shows up in metrics fast; residual ~3s is DNS of the stopped host, covered by the poller's 5s timeout |
| 2026-07-05 | Added `psycopg-pool` and `docker` (SDK) deps | shopapi needs a real connection pool (S4); actuator needs the Docker API (restart/stop by label) | Recorded in uv.lock |
| 2026-07-05 | Actuator gained `/admin/stop_container` (not in 03 §5) | S1 injection needs to stop a container; keeps inject pure-HTTP (no Docker access in inject/tester). Agents never get it — only /restart | Minor API addition, admin-scoped |

## Environment facts (fill during build)

- Tooling: uv 0.11.26; project venv Python 3.12.5 (uv-managed 3.12.13 also installed).
- Locked versions of note (from uv.lock): langgraph 1.2.7, langgraph-checkpoint-postgres 3.1.0,
  langchain-core 1.4.8, langchain-google-genai 4.2.6, langchain-groq 1.1.3, celery 5.6.3,
  fastapi 0.139.0, pydantic 2.13.4, sqlalchemy 2.0.51, fastembed 0.8.0, pytest 9.1.1, ruff 0.15.20.
- LLM model ids actually used (free tier, verified live): _tbd at M03_
- Windows/Docker-Desktop: **installed & working 2026-07-05** — WSL 2.7.10 (Ubuntu distro,
  WSL v2 default), Docker Desktop engine server **29.6.1**, no reboot needed. Docker CLI at
  `C:\Program Files\Docker\Docker\resources\bin` (add to Bash PATH in commands).
  uv installed to `%USERPROFILE%\.local\bin`.
- **Relocated 2026-07-05**: repo moved to **`E:\Desktop\argus`** (`/e/Desktop/argus` in
  Bash); Docker Desktop disk image moved to **E:** (Settings → Resources → Advanced).
  Move was lossless (git in sync, all images survived, poe verify green after venv rebuild).
  Because the uv cache stays on C: (cross-drive), `link-mode = "copy"` is pinned in
  pyproject `[tool.uv]`; after any host move, recreate the venv: `rm -rf .venv && uv sync`.

## Open questions for the user

> Only things that would change an ADR or the product behavior. Everything else:
> conservative default + deviation entry.

- (none)
