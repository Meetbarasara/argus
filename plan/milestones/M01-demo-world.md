# M01 — Demo World (the patient)

**Objective:** a running, self-instrumented microservice world with 5 reproducible
fault scenarios, file-based telemetry, an alerting watcher, and a privileged actuator.
Fully verifiable **without any LLM or platform code** — this is the ground truth the
whole project stands on, so it must be boringly deterministic.

**Read first:** 01 (scenario contract), 02 (world containers, ADR-02/03/09),
03 §2 (worldstate formats — follow to the letter), 03 §5 (actuator API).
**Prerequisites:** M00 gate green.

## Deliverables (`src/demoworld/`)

| Path | Responsibility |
|---|---|
| `common/jsonlog.py` | JSONL logger writing 03 §2 log lines to `worldstate/logs/<svc>.jsonl` (rotation, 08 #6) |
| `common/hotconfig.py` | load + 5s-poll `worldstate/config/<svc>.json`; exposes current config + version (ADR-02) |
| `common/stats.py` | in-process rolling 60s window (req/err/latency p95) + dep probes → `/internal/stats` shape (03 §2) |
| `shopapi/app.py` | FastAPI: `GET /products` (shopdb query + shopredis cache, honors `cache_enabled`, `feature_flags.recs_v2` — broken code path when true), `POST /checkout` (calls paymentsvc at `payment_url` with `request_timeout_ms`), `GET /health`, `GET /internal/stats`; DB pool sized from `db_pool_size` (re-created on config change) |
| `paymentsvc/app.py` | `POST /pay` (sleeps `base_latency_ms` + `chaos_extra_latency_ms`), `/health`, `/internal/stats`, `POST /admin/chaos` (sets in-memory extra latency; also settable via actuator) |
| `loadgen.py` | steady ≈5 rps mix: 70% /products, 30% /checkout; logs nothing to worldstate |
| `poller.py` | every 5s: GET both services' `/internal/stats` → metric lines per 03 §2 |
| `alertwatch.py` | every 10s: evaluate `config/alert_rules.yaml` over recent metrics; `for_checks` consecutive breaches → alert (03 §2 payload) appended to `alerts/sent.jsonl` **always**, POSTed to `ALERT_WEBHOOK_URL` best-effort (08 #5); refire cooldown per rule+service |
| `actuator/app.py` + `docker_ops.py` + `deploys.py` | 03 §5 API: token check, restart-by-compose-label (08 #4), deploy/rollback with snapshots + history, audit log, chaos passthrough, whitelisted `/tail` debug reader; plus `POST /admin/reset_worldstate` (truncates logs/metrics/alerts, reseeds config to baseline, resets deploy counter) — used by tests and the eval runner |
| `inject.py` | CLI `python -m demoworld.inject --scenario S1..S5 [--decoy-deploys N] [--warmup-seconds N]` — drives faults exactly as 01's table describes (S1 stop container via actuator; S2 chaos endpoint; S3/S4/S5 deploys via actuator) |
| `seed/` | baseline config JSONs + shopdb init SQL (a `products` table with ~20 rows) |

Compose: wire all world services (M00 already declared them) — this milestone makes
them actually run: worldstate volume mounts (services rw only to their own log file;
actuator rw everywhere; others ro), healthchecks, `ALERT_WEBHOOK_URL` env
(default `http://api:8080/api/alerts/webhook`), `ACTUATOR_TOKEN`.

## Steps

1. `common/` trio first, with unit tests (rolling-window math, hot-reload version
   bump, log rotation + torn-line-safe reader).
2. shopapi + paymentsvc + seed; verify locally in containers (`curl /health`, `/products`).
3. loadgen + poller; confirm metrics.jsonl accumulates all six metric names.
4. actuator (deploy/rollback/restart/audit/reset) with integration tests.
5. alertwatch + rules; integration test: force err_rate above threshold → alert line.
6. inject.py, one scenario at a time, each verified against 01's evidence contract.
7. Table-driven integration test `tests/integration/test_scenarios.py` (marker `world`):
   for each scenario → reset → inject → assert expected alert rule+service in
   sent.jsonl within 90s AND expected evidence signature exists (S1: ConnectError logs
   + dep_up{redis}=0; S2: latency_p95 breach + chaos audit line + **zero** deploys since
   warmup; S3: 502 logs + deploy touching payment_url; S4: pool-timeout errors + deploy
   touching db_pool_size; S5: 5xx on /products only + deploy touching recs_v2).
   Then: apply the correct remediation via actuator → within 120s the breached metric
   is back under threshold (proves scenarios are *recoverable* — verify_recovery's
   ground truth).

## Acceptance criteria

- [ ] `docker compose --profile world up -d` → 8 services healthy from cold start.
- [ ] All five scenarios pass the table-driven test, including recovery.
- [ ] `reset_worldstate` returns the world to quiet baseline (no alert for 3 min after).
- [ ] S2 leaves no deploy-history trace; S3–S5 each leave exactly their deploy (+decoys when asked).
- [ ] Log/metric/deploy/alert lines validate against 03 §2 shapes (schema test).

## Verification gate

```
$ docker compose --profile world up -d && docker compose ps
        → shopapi, paymentsvc, shopdb, shopredis, loadgen, poller, alertwatch, actuator all healthy
$ docker compose run --rm tester pytest -m world -q   → all pass (5 scenarios × evidence+recovery)
$ python -m demoworld.inject --scenario S3
$ curl -s -H "X-Actuator-Token: dev-actuator-token" "localhost:8010/tail?file=alerts/sent.jsonl&last=1"
        → rule=high_error_rate service=shopapi within 90s of injection
$ curl -s -X POST -H "X-Actuator-Token: dev-actuator-token" localhost:8010/rollback \
       -d '{"deploy_id":"<from /deploys>","author":"human"}' → 200; error rate recovers ≤120s
$ uv run poe verify                        → green
```

(The `world` tier runs inside the `tester` service so it can read the worldstate
volume and reach services by name — see 05.)

**Gotchas:** 08 #4–#7. **Out of scope:** platform anything; webhook receiver (POSTs
will fail until M02 — that's fine, sent.jsonl is the oracle).
