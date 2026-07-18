# Argus Build Progress

> Maintained by the builder. Update at the start and end of every milestone.
> Never mark a milestone `done` with a red gate.

## Milestone status

| # | Milestone | Status | Verify before | Gate after | Commit | Notes |
|---|---|---|---|---|---|---|
| M00 | Scaffold & tooling | done | ✅ 2026-07-03 (empty repo) | ✅ 2026-07-05 poe verify + all 4 docker gates | 827ea31 | Complete — Docker installed, full gate green |
| M01 | Demo world | done | ✅ 2026-07-05 | ✅ 2026-07-05 poe verify (45) + world gate 5/5 passed (554s) | 141696a + gate | Complete — all 5 scenarios produce evidence + recover |
| M02 | Platform core | done | ✅ 2026-07-05 | ✅ 2026-07-05 poe verify (54) + integration 4/4 + gate curl | 588e878+ | Alert→incident→worker pipe live; full schema migrated |
| M03 | LLM layer | done | ✅ 2026-07-05 | ✅ 2026-07-05 poe verify (74) + integration 4/4 + live smoke 7/7 roles | a552414+ | Router/limits/retry/record-replay; real Gemini+Groq verified |
| M04 | Tool layer | done | ✅ 2026-07-05 | ✅ 2026-07-05 poe verify (84) + tool-world 3/3 + all 9 tools logged | 496747e+ | 9 tools, permission-enforced, evidence verified vs live world |
| M05 | Graph v1 | done | ✅ 2026-07-06 (clean; verify 84) | ✅ 2026-07-06 verify (99) + graph 9/9 + live S1 RESOLVED/NOTIFY + live S3 WAITING_APPROVAL + integration 8/8 + world 7/8 (S1 flake, green standalone) | cb994aa+ | Autonomous S1 resolution live; S3 approval hold; specialists use real tools |
| M06 | Human-in-the-loop | done | ✅ 2026-07-06 (clean; verify 99) | ✅ 2026-07-06 verify (104) + graph 11/11 + hitl 7/7 + live S3 approve→RESOLVED across a worker restart | f8d1312+ | Real interrupts; approve/reject/modify/takeover; durable pause |
| M07 | Memory | done | ✅ 2026-07-06 (clean; verify 104) | ✅ 2026-07-06 verify (119) + graph 12/12 + memory 4/4 + live repeat 13→6 LLM calls (54% lift) | 03eb924+ | pgvector recall + postmortem + fast-path; memory-lift proven |
| M08 | Parallelism & resilience | done | ✅ 2026-07-06 (clean; verify 119 + graph 12) | ✅ 2026-07-06 verify (133) + graph 19 (chaos a–e, seq fallback, span-overlap) + live S1 spans overlap 1.876s + world 8/8 | 6906152 | Send-API fan-out + 2-wave deps; resilience degrades to conf-0; budget via spec_llm_calls reducer |
| M09 | Observability | done | ✅ 2026-07-06 (clean; verify 133 + graph 19) | ✅ 2026-07-07 verify (141) + graph 19 + test_dashboard 2/2 + live dashboard sane + Jaeger 34-span single-root trace | 4c0797f | OTel dual sink; `incident` root span; pure-SQL /dashboard/summary; Jaeger profile |
| M10 | React UI | done | ✅ 2026-07-07 (clean; verify 141 + graph 19) | ✅ 2026-07-07 ui lint+typecheck+build clean + vitest 10/10 + docker ui 200 + nginx→api proxy + live drill-down (llm+tool) | ffd4d96 | 5-page console: live incidents, trace explorer w/ prompt+tool drill-down, approval card (modify round-trip), memory, dashboard |
| M11 | Evaluation harness | done | ✅ 2026-07-10 (clean; verify 158 @ 49c9cae) | ✅ 2026-07-10 (see log) — verify 166 + graph 23 + integration 20/21 (test_platform flake→4/4 standalone) + world 8/8 + replay smoke + baseline 15/15 graded + ablation lift table + /api/evals/runs 23 + UI panel live | 6cce150 | Harness complete + validated; **clean headline run 2026-07-18** (7/15 PASS, cerebras:gpt-oss-120b supervisor, recovery 8/8) + memory ablation → EVALUATION.md regenerated (see 2026-07-18 log) |
| M12 | Demo & docs | in_progress | ✅ 2026-07-10 (clean; verify 169) | – | – | Writing done; **EVALUATION.md clean numbers DONE 2026-07-18**; **UI verified vs the clean run**; `demo --auto` (S3 fails on free model), `docs/img/` screenshots (need a screenshot tool), `down -v` clean-boot (destructive) still deferred |

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

### Post-M11 hardening — 2026-07-19 (#3: eval incident-selection fix + demo→S4)
- **Root-caused the "0 llm_calls" artifact — it was a false FAIL, not a metrics slip.** A case can fire
  SEVERAL incidents (alert re-fires + the service-level dedupe gap), and `await_incident` locked onto the
  *newest* — sometimes a 0-call straggler — while the agent's real investigation ran on a sibling. DB
  proof: S1-v3's graded `b4a7b8a2` had siblings `b3f77d92`/`31642d46` **RESOLVED (14 calls)**; S2-v2's
  sibling `22bc8aa5` **RESOLVED (10)**. So the 2026-07-18 **7/15 is an undercount** (S1-v3 + S2-v2
  primaries actually resolved). A confirmed corrected headline needs a live re-run (quota).
- **Fix (`evals/run.py`):** `select_case_incident` — among a case's incidents, grade the most-investigated
  (max `llm_calls`, tie-break newest); effort-based, NOT outcome-biased (a big FAILED outranks a small
  RESOLVED), so it can't inflate the pass rate. Wired via a new defaulted `Platform.list_incidents_since`
  → single-incident cases (the common path) are unchanged. +6 unit tests (`test_eval_selection.py`) + 1
  graph integration test (multi-incident → grades the investigated one).
- **Demo repointed S3→S4 (`demo.py`):** S3 (`bad_deploy_env`) is the one scenario the free gpt-oss-120b
  reliably fails; S4 (`db_pool_exhaustion`) is the same APPROVE_ACTION→rollback arc but one it handles.
  Act 2 now re-injects the **identical** fault (was +1 decoy) so the memory fast-path actually fires.
  `test_demo` updated. Makes `demo --auto` a dependable recording without a paid model.
- **Gate:** `poe verify` **177** (+6) + `poe test-graph` **24** (+1), both green. Host-side only (no image
  rebuild). Well-behaved single-incident cases unchanged.

### M11 — 2026-07-18 (CLEAN headline eval run + memory ablation — DONE)
- **Clean 15-case baseline** (`run 41cd9251`, live, supervisor `cerebras:gpt-oss-120b`, memory off):
  `uv run python -m argus.evals.run --suite all --memory off --supervisor-model cerebras:gpt-oss-120b`
  → **7/15 PASS** · RCA 7/15 (47%) · remediation 8/15 · **recovery 8/8 (100%)** · escalation
  precision 91% / recall 83% · median MTTR 253.5s · 16 calls · $0.0164. **Supersedes** the 2026-07-10
  quota-degraded 2/15 (08 #27 clean re-run — no fresh Gemini needed; the Cerebras fallback chain did it).
- **Genuine finding (not tuned away):** S3 (a deploy broke `payment_url` → checkout 502s) fails all
  three variants — full 18–28-call investigations that misread the symptom as a paymentsvc dependency
  outage / monitoring glitch and escalate to TAKE_OVER (fail-closed, wrong RCA). Change-correlation-
  precision gap in gpt-oss-120b; strong on S1/S2/S4/S5 (7/11 non-artifact). See EVALUATION.md §Failures.
- **Run conditions:** free-tier rate-limited (Gemini daily-exhausted; cerebras/groq per-minute 429s,
  cerebras auto-retries ~56 s). 3 cases (S1-v3/S2-v2/S5-v1) recorded 0 `llm_calls` — a dedupe/counter
  metrics artifact (2 of 3 still diagnosed); **7/15 is a floor.** Actuator stayed 200 the whole ~5 h run
  (it survived a mid-run PC sleep because the runner is nohup-detached + results persist in Postgres).
- **Memory ablation** (`--repeat-for-memory --suite S1`; re-run clean after a rate-degraded 1st attempt:
  ON=`de400216` OFF=`cf7fe938`): all 4 cases RESOLVED; repeat S1-v2 recalled the memory
  (`memory_used=True`) but **15 ON vs 12 OFF calls = no fast-path lift** — v1(clean)→v2(+2 decoys) is
  below the 0.92 similarity threshold, so memory was context not a shortcut. Same-fault fast-path lift
  stays proven at M07 (13→6, 54%). Reported honestly, not re-run to chase a positive number.
- **EVALUATION.md regenerated** (`argus.evals.report`) + hand-augmented (run-conditions caveat, memory
  interpretation, S3 §Failures synthesis). The auto supervisor-model table was **removed** — its only
  gemini comparators are quota-degraded 0–6-call runs (unfair). `.env` restored to live/off/true
  (supervisor override dropped); `/api/health` echo confirms.

### M12 — 2026-07-18 (UI verified against the clean run; demo/screenshots/down-v deferred)
- **UI console verified live** against the fresh M11 data (`docker compose up -d ui`, `localhost:8081`
  → 200, `/api/dashboard/summary` proxied 200): the Incidents feed renders the whole run — S1
  "Dependency down"→Resolved/Notify, S3 "High error rate"→Taken over, S2 "High latency", with
  **memory-recalled badges** on the ablation incidents, escalation levels, per-incident cost, and a
  health footer echoing the restored baseline (`gemini-2.5-flash · live · memory on`). The M10 console
  + M11 data integration works end-to-end (verified via read_page; the in-app browser can't save PNGs).
- **Deferred (user-approved "pause M12 here"), each with a real blocker:** (1) `docs/img/` screenshots —
  no headless-screenshot tool in the repo (no playwright/puppeteer) and the browser can't export
  committable PNGs → needs a devDep add or a manual capture; (2) `python -m argus.demo --auto` — the
  storyline is scripted on **S3**, which `gpt-oss-120b` fails (→ TAKE_OVER, breaking the
  approve→resolve→memory-win beats) → needs a stronger/paid supervisor; (3) `docker compose down -v`
  clean-boot — destructive (wipes the eval DB the UI/dashboard show) → do last, deliberately.
  M12 stays in_progress.

### M12 — 2026-07-10 (demo & docs — writing DONE; runtime gate deferred to fresh quota)
- **Written + verify-green (169 unit, +3 demo):** `src/argus/demo.py` — the guided 7-beat
  storyline (01 §demo: inject S3 → review → risk gate → approve → resolve → repeat-fault memory
  win with a side-by-side comparison; `--auto` = policy_sim for recording, interactive = approve
  in the UI/API), reusing the M11 runner's validated platform machinery; `README.md` (pitch +
  mermaid architecture + 5-claims→code-links + eval section + quickstart + repo tour + ADR index +
  honest limitations); `INTERVIEW_NOTES.md` (3 safety layers, memory-lift/model numbers, §Failures,
  scaling answers, free-LLM robustness framing, recording checklist); `LICENSE` (MIT); pyproject
  `readme` re-added (closes the M00 deferral). All 16 doc-linked file paths verified to exist.
- **Deferred (same blockers as the M11 headline):** `python -m argus.demo --auto` full run + the
  `docker compose down -v` clean-boot quickstart test need LLM quota (and `down -v` wipes the eval
  data the UI/EVALUATION.md reference) → run on fresh Gemini quota; `docs/img/` screenshots
  (incidents, trace drill-down, approval card, dashboard, Jaeger) need a browser; README/
  INTERVIEW_NOTES eval numbers regenerate when EVALUATION.md is re-run clean. Stays in_progress.

### M11 — 2026-07-10 (evaluation harness — engineering DONE + validated; headline quota-degraded)
- **Engineering completion** (`5deb2ef`, on top of 49c9cae which was verify-green but CLI/report/
  platform/UI-incomplete — gaps ruff+mypy+unit can't catch): run.py `--repeat-for-memory` (07 §4)
  + `--resume`; `reset()` → actuator `/admin/reset_worldstate` (07 §2 — kills cross-case config/chaos
  drift) + health-wait; `set_platform_env` verifies the `/api/health` config echo (07 §2); recovery
  grading fix (the `/tail` body is `{lines:[...]}` not raw JSONL — the old code fed the wrapper dict
  to the rule matcher, so recovery was **always false**) + poll up to 120s ("≤120s after
  remediation"); UTF-8 stdout (cp1252 crashed on →/Δ); report.py `memory_lift_table` +
  `model_comparison_table` + auto-composed EVALUATION.md ablation sections; **worker/tasks.py
  policy_sim auto-approver** (AUTO_APPROVE was defined but never consumed → eval-mode S2–S5 hung at
  WAITING_APPROVAL forever); UI Dashboard eval panel → `/api/evals/runs`. verify **166** unit + graph
  **23** (+recovery-rederivation, ablation-renderer, resume-skip tests).
- **Validated live end-to-end:** `--suite S3-v1 --memory off` → **PASS** (RCA ✓ · remediation ✓ ·
  recovery ✓ · escalation ✓) — the policy_sim auto-approver resolves an APPROVE_ACTION case to
  RESOLVED (not a 480s hang); reset_worldstate + health-echo + recovery grading all proven.
- **Verification gate:** `poe verify` 166 + `test_grading` green · replay smoke `--suite S1
  --llm-mode replay` completes + writes an eval_run · `--suite all --memory off` **15/15 graded**
  (live) · `--repeat-for-memory` prints the lift table · `report` → EVALUATION.md · `/api/evals/runs`
  = **23** (≥2) + UI panel live (proxied 200 through nginx) · verify-all: verify 166 + graph 23 +
  integration 20/21 (test_platform webhook flake → **4/4 standalone** after a queue drain) + world
  **8/8** (worker paused).
- **Headline numbers QUOTA-DEGRADED — a finding, not a system fault (07 §6):** the full baseline
  (`a6313997`) graded 15/15 but scored **2/15 PASS**. Gemini's free-tier daily cap (~20 req)
  exhausted after the health smoke + S3-v1 validations, and Groq — bearing the doubled load once
  every Gemini-role call fell back to it — hit its per-minute TPM (429) → **10/15 cases FAILED on
  the first LLM call** (0–1 `llm_calls`, no investigation). This measures the free-tier quota, not
  Argus (isolated S3-v1 PASS + M05–M07 live successes prove the system works with capacity). The
  memory ablation is likewise quota-degraded ("insufficient data"). **Clean full-suite headline +
  ablation re-run DEFERRED to fresh Gemini quota** (08 #27) — user-approved ("finish now, re-run
  clean later"). EVALUATION.md committed with a prominent quota caveat + honest §Failures (incl. the
  quota-independent **S1-v2**: RCA ✓ but decoys → wrong remediation + over-escalation — a real
  change-correlation-precision finding); it will regenerate with clean numbers on fresh quota.

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

### M10 — 2026-07-07 (React UI — review console + trace explorer — DONE)
- **UX-first IA:** a persistent sidebar (Incidents · Approvals · Memory · Dashboard) with a
  live **pending-approvals badge** so the on-call engineer sees when they're needed, and a
  health footer (LLM mode / model / memory). `WAITING_APPROVAL` rows are pulled to attention
  (amber accent) in the triage table. Dark "control-room" palette, no component library
  (Tailwind only, 05).
- **Pages (`ui/src/`):** Incidents (live 2s table, filters, memory/⚡ badges); IncidentDetail
  (header timeline + tabs) — the **Trace** tab is a collapsible span tree built once from
  `parent_span_id` with a side panel that drills an llm span → exact prompt/response + tokens +
  cost and a tool span → args/result; Hypothesis & Review, Remediation, Memory tabs derived
  from incident fields + key spans; **Approvals** (the HITL hero: risk level, hypothesis +
  confidence bar, evidence, proposed action, Approve / Modify [JSON param editor, server
  re-validates + re-gates] / Reject [comment required], NOTIFY feed with Ack, decided history);
  Memory (vector search, kind filter, delete, Consolidate); Dashboard (stat cards + recharts
  cost/token charts + eval empty-state until M11). Empty states on every page.
- Infra: `api.ts` typed client mirroring 03 §4; TanStack Query (2s active / 10s calm poll,
  ADR-08); nginx serves the build + proxies `/api` (no prod CORS, 08 #25); vite dev proxy for
  `npm run dev`.
- **Gates:** `cd ui && npm run lint && npm run typecheck && npm run build` → clean (2408
  modules; tsc strict, eslint --max-warnings 0). `npx vitest run` → **10/10** (span-tree
  builder incl. 30-span + orphan cases, status→tone mapping, ApprovalCard render + approve
  click + reject-requires-comment). `docker compose up -d --build ui` → `curl localhost:8081`
  **200**, and `localhost:8081/api/dashboard/summary` **200** through the nginx proxy.
- **Live data plumbing verified** against the running platform (50 resolved incidents): an
  incident's 18 spans render all kinds; **llm span → `/llm_calls/{span_id}`** returns
  role/model/tokens/cost + messages; **tool span → `/tool_calls/{span_id}`** returns
  agent/tool/args/result; 94 approvals + 2 memories available for their pages. `uv run poe
  verify` still **141 unit** (the two small API additions below are covered).
- **Storyline note:** the interactive inject-S3→approve→RESOLVED click-through is constrained
  this session by the exhausted Gemini quota + an offline browser-automation extension; the
  approval **decide → resume → RESOLVED** path the UI's button triggers is the exact flow
  `test_hitl` proves (M06, 7/7), and the UI's `decideApproval` mutation posts to that endpoint.

### M09 — 2026-07-07 (observability — dual sink, dashboard, root span — DONE)
- **OTel dual sink (ADR-07):** `obs/otel.py` wires a TracerProvider at api/worker boot
  (`setup_tracing`) with an OTLP→Jaeger BatchSpanProcessor **only** when
  `OTEL_EXPORT_JAEGER=true`; the Postgres exporter stays the primary sink. `obs/spans.py`
  now mirrors each span to the OTLP sink (parent linked via an in-process span map) and
  **auto-parents** any parentless node span to the incident's root span — no per-node edits.
- **Root span (08 #24):** the worker opens one `incident` root span around `graph.invoke`
  (run + resume), writes its trace_id to `incidents.trace_id`, and registers it so every span
  becomes a child; `intake` reuses that trace (fresh one for direct graph runs). One incident
  = one trace.
- `obs/pg_exporter.py`: per-attr 2 KB cap with a WARN on truncation (nothing dropped
  silently); ERROR status already captured. `api/routers/dashboard.py`: GET
  /dashboard/summary — pure-SQL rollups (status counts, resolution/escalation rates, avg+median
  MTTR, cost+tokens by role/model, per-incident cost, steps-to-diagnosis, memory share),
  replacing the 501 stub. compose: `jaeger` (observability profile, OTLP) + endpoint plumbed.
- Host `uv run poe verify` green — **141 unit** (+8: span attr contract per kind). `poe
  test-graph` **19** (unchanged). `test_dashboard.py` (tester) **2/2**: /dashboard/summary
  reconciles with direct SQL on incidents/llm_calls (self-consistent) + real emitted spans
  satisfy the per-kind attr contract.
- **Live `GET /api/dashboard/summary`** → sane non-null: total 133, resolution 0.56,
  escalation 0.53, avg_mttr 5.04s, cost $0.241, steps-to-diagnosis 9.8.
- **Jaeger smoke (record):** `--profile observability up jaeger`, `OTEL_EXPORT_JAEGER=true`,
  inject S1 → Jaeger service `argus-worker` shows **one trace, 34 spans, single `incident`
  root**, full hierarchy (intake→recall→plan→3 specialists w/ real llm+tool spans→synthesize→
  review). Verified via the Jaeger query API. Gemini daily quota exhausted → supervisor/reviewer
  routed to Groq for the run (the span tree is provider-independent).
- **Jaeger off (default) ⇒ nothing degrades:** the OTLP setup is a guarded no-op; all host +
  graph + integration tiers pass with `OTEL_EXPORT_JAEGER=false`. Integration tier green; the
  `test_platform` webhook backlog flake + a leftover-incident dedupe clash from the live smoke
  both cleared on isolated re-run (env, not M09).
- **Deferred:** `docs/img/jaeger.png` screenshot → M12 docs assembly (needs a browser; the
  live trace is proven here via the Jaeger query API). 08 #25 (dev CORS) was handled in M02.

### M08 — 2026-07-06 (parallel specialists & resilience — DONE)
- Specialists swapped from the M05 sequential chain to a **Send-API parallel fan-out**
  (`graph/build.py`, `graph/fanout.py`): after `plan`, `_route_after_plan` dispatches one
  `Send` per ready step (no unmet `depends_on`); the specialist nodes append findings
  concurrently and converge on a new deterministic `gather` join, which dispatches a dependent
  second wave (≤2 waves; plan caps at 5 steps) before `synthesize`. Interrupts stay strictly
  post-join (08 #20). The M05 sequential chain is retained behind `PARALLEL_SPECIALISTS=false`
  for the A/B latency demo.
- **Budget** (04 §6): specialists no longer write the non-reducer `budget` dict (3 concurrent
  writers = InvalidUpdateError); their calls land in a new `spec_llm_calls` reducer channel,
  and `support.total_llm_calls` folds them into the running total — checked once before the
  fan-out (after plan) and once after the join (gather), never per branch. Boundary unit-tested
  (39 ok / 40 trips, incl. specialist calls). Specialist tool-call cap 4→6 (04 §4).
- **Resilience**: the specialist node degrades any provider/tool/infra failure to a
  confidence-0 finding (never a naked raise); `gather` escalates to take_over when >50% of a
  cycle's findings failed ("investigation degraded"). Worker task `soft_time_limit`=max_wall+60s
  (480s) → FAILED with a clear reason on expiry (hard 540s). `FakeLLM` made thread-safe
  (per-role bound view + lock — specialists now run on LangGraph's thread pool) + optional
  scripted tool_calls to drive the tool loop in tests.
- Host `uv run poe verify` green — **133 unit** (+14: budget-guard boundary + fan-out wave/
  degradation logic). `uv run poe test-graph` **19** (12 M05/M06/M07 unchanged + 7 M08).
- **Chaos (a–e)** green (FakeLLM + monkeypatched tools): (a) a tool raising twice → conf-0
  finding → synthesize plans around it → RESOLVED; (b) one specialist's provider giving up →
  1 degraded finding, still RESOLVED; (c) 2/3 degraded → TAKEN_OVER; (d) budget trip →
  TAKEN_OVER; (e) 3 independent steps → all 3 findings present (reducer, no loss). Plus a
  sequential-fallback resolve and a deterministic span-overlap parallelism proof.
- **Live parallelism proof (record):** inject S1 → incident `d8b216b6`, 33 spans
  ({node:10, llm:16, tool:7}). `node.log_analyst` [45.316–47.192] and `node.metrics_analyst`
  [45.306–47.508] **overlap 1.876s** (parallel wave 1); `node.change_analyst` [47.523–49.565]
  ran in the dependency-driven wave 2 — proving both fan-out and the 2-wave join live. Gemini
  free-tier daily quota was exhausted (429), so supervisor/reviewer were routed to Groq via
  `ARGUS_MODEL__*` for this run; the weaker supervisor's low-confidence hypothesis correctly
  escalated to TAKE_OVER — autonomous S1 resolution stays proven at M05/M07 + the graph tier.
- Integration (tester): `-m integration` green with an idle worker; `test_platform` 4/4
  standalone (a busy worker + the exhausted Gemini quota backs the queue up past the webhook's
  30s deadline — a timing flake, not an M08 regression). `-m world` **8/8** (worker paused,
  622s); the S1 M01 flake did not recur.

### M07 — 2026-07-06 (memory — write, recall, fast-path, management)
- `src/argus/memory/`: `embedder` (fastembed bge-small-en-v1.5, 384-d, lazy + baked into
  the image — 08 #22), `vectorstore` Protocol (Pinecone-swappable, ADR-01) + `pgvector_store`
  (cosine over the memories HNSW index), `fingerprint` (deterministic {alert_rule, services,
  templates} via the M04 normalizer + embed-text builders), `scoring`
  (`0.6·sim + 0.2·recency(30d) + 0.2·log1p(use_count)`), `recall` (top-5, bumps usage,
  fast-path when top sim > 0.92 AND source RESOLVED), `writer` (memory_writer LLM postmortem;
  take-overs become deterministic 'lesson' memories), `consolidate` (cosine≥0.90 clusters →
  merge + supersede, importance decay 0.98^idle floor 0.1).
- Nodes `recall_memory` + `postmortem` replace the M05 no-ops (recall/writer injected via
  GraphDeps so host graph tests stay embedder-free; both honor MEMORY_ENABLED). `memories`
  API (list/vector-search/delete/consolidate) replaces the stubs.
- Host `uv run poe verify` green — **119 unit** (scoring/recency goldens, fingerprint,
  consolidation clustering, modify re-gate). `poe test-graph` **12** (+h: recall injects the
  memory block + fast-path, never skipping review/risk_gate).
- `test_memory.py` (tester, real pgvector + baked embedder) **4/4**: write→recall round
  trip, delete stops recall, consolidation merges a near-duplicate pair (originals
  superseded), and the repeat test (run #1 seeds → run #2 memory_used=true + plan prompt
  carries the memory block). Model baked into the image (08 #22).
- **Live memory-lift (record):** clean slate → S1 run A `ecedf03b` (memory_used=false,
  **13 LLM calls**, wrote memory) → S1 run B `6065f0c0` (memory_used=**true**, **6 LLM
  calls**) = **54% fewer** (target ≥20%). `GET /api/memories` → 2 (run A's use_count bumped
  by run B's recall); vector search `?query=redis+down` returns the memory (sim 0.65).

### M06 — 2026-07-06 (human-in-the-loop — real interrupts)
- Replaced M05's approval holds with LangGraph `interrupt()`. Probe confirmed a node
  **re-runs from the top on resume**, so side effects (PENDING approvals row +
  WAITING_APPROVAL status) live in the worker task, not the node. `human_approval` and
  `take_over` are pure preamble → `interrupt(payload)` → route on the resume decision.
- `worker/tasks.py` v2: run_incident detects `__interrupt__` → `_park_for_human`;
  `resume_incident(incident_id, approval_id)` guards on status (idempotent, 08 #19) →
  `graph.invoke(Command(resume=payload))`. `api/routers/approvals.py`: GET queue + POST
  decision (atomic `UPDATE…RETURNING` flip → 409 on double-decide; `modify` re-validates +
  re-gates, 422 if it raises risk; `ack` for NOTIFY). `incidents.py`: takeover_resolution.
- Host `uv run poe verify` green — **104 unit** (+5 modify re-gate). `poe test-graph`
  **11** (M05 a–e updated for the takeover interrupt + new f: APPROVE_ACTION approve→RESOLVED,
  g: reject→replan). `test_hitl.py` (tester, in-process fake router + REAL PostgresSaver +
  REAL approvals API) **7/7**: (i) approve→RESOLVED, (ii) reject→replan→approve→RESOLVED,
  (iii) modify→modified action executed, (iv) double-decision→409, (v) duplicate resume→
  no-op, (vi) takeover_resolution→TAKEN_OVER, (vii) fresh graph resumes from the Postgres
  checkpoint (durability).
- **Live S3 (record):** inject → incident `3ae068c1` WAITING_APPROVAL/APPROVE_ACTION with
  a PENDING `rollback_deploy(d-0001)`. **`docker compose restart worker`**, then approve via
  API → the restarted worker resumed from the durable checkpoint → REMEDIATING → **RESOLVED**
  (MTTR 224s, rollback ok, world recovered). One `human` span, decision=approve,
  human_review_seconds=107. 39 spans (node/llm/tool/policy/human).

### M05 — 2026-07-06 (graph v1 — the agents come alive)
- Built the full LangGraph pipeline: `agents/` (schemas verbatim 04 §3, prompts, supervisor
  plan+synthesize, specialist tool-loop, reviewer), `policy/risk_gate.py` (pure), `graph/`
  (state, deps, support, verify, 13 node modules, build.py), `graph/runtime.py` (PostgresSaver
  singleton), `worker/tasks.py` run_incident v1.
- Host `uv run poe verify` green — **99 unit** (+15 risk_gate table). `uv run poe test-graph`
  green — **9** (a: S1 happy path RESOLVED; b: revise→approve; c: reject×2→TAKEN_OVER;
  d: budget breach→TAKEN_OVER; e: 5-scenario risk levels), FakeLLM + MemorySaver, platform pg.
- **Live S1 (LLM_MODE=record), fully autonomous:** inject S1 → incident `7abc0255` →
  `{"status":"RESOLVED","escalation_level":"NOTIFY"}` in ~50s (MTTR 50s). Remediation
  `restart_service(shopredis)` ok; world recovered (redis dep up). **36 spans, all OK, one
  trace**, kinds `{node:12, llm:14, tool:9, policy:1}` — specialists ran real tools
  (search_logs, log_error_summary, query_metrics, service_health, list_deploys,
  recent_actions, deploy_diff) + remediate restart_service. Counters: 14 llm / 9 tool calls,
  10581/5440 tok, **$0.017**. AUTO NOTIFY approvals row present. root_cause = redis stopped.
- **Live S3:** inject bad payment_url deploy (d-0001) → incident `76f2ca08` →
  `WAITING_APPROVAL` / `APPROVE_ACTION`; remediation `null`; one **PENDING** approval
  proposing `rollback_deploy(deploy_id=d-0001)` on shopapi. 32 spans incl. a `human` span.
- Grep gates: no direct `incident.status =` writes in graph/worker (all 8 transitions via
  `incident_repo.transition`); no prompt text outside `prompts.py`.
- Integration tier (tester): `-m integration` **8/8** (test_platform incl. updated M05
  handoff + test_llm_layer). `-m world` run with the worker paused (see deviations):
  **7 passed, 1 failed** — `test_s1_redis_down` hit a pre-existing M01 timing flake
  (`_wait_for_alert` accepts high_error_rate; reset-noise can fire one pre-fault so
  `dep_up[redis]` still reads 1 at the assert). **Passes standalone (100s)**; S2–S5 +
  tool-world all green. M05 changed no world/poller/actuator code → not an M05 regression.

### M04 — 2026-07-05 (tool layer — DONE)
- `tools/`: worldstate (own defensive JSONL reader — no demoworld import; time-window filter;
  error-template normalization), schemas (9 Pydantic arg models), telemetry_tools (search_logs,
  log_error_summary, query_metrics, service_health), change_tools (list_deploys, deploy_diff,
  recent_actions), remediation_tools (restart_service, rollback_deploy → actuator), registry
  (ToolSpec + ToolExecutor: validate args, enforce allowed_agents, refuse mutating outside
  remediate node, truncate ≤50/8KB, tool_calls + tool span, structured errors vs ToolError),
  langchain_bridge (per-agent StructuredTools for M05). `tests/conftest.py` clears settings cache.
- Host: `poe verify` green — **84 unit** (worldstate readers + normalize goldens, registry matrix
  == 04 §5, truncation, per-agent toolset). mypy 63 files.
- Integration (tester, platform+world up) **3/3**: permission enforcement (specialist can't mutate;
  remediate tool refused outside remediate node; wrong agent; bad args); S3 evidence across all
  read tools (search_logs finds checkout 502s, log_error_summary, list_deploys+deploy_diff show the
  payment_url deploy, query_metrics err_rate, service_health) + rollback recovers; S1 restart via tool.
- Gate: **all 9 tools logged** to tool_calls with OK + ERROR paths.
- **M04 complete.** Next: M05 (graph v1 — the agents come alive; S1 resolves autonomously).

### M03 — 2026-07-05 (LLM layer — DONE)
- `llm/`: config (role→model + ARGUS_MODEL__<ROLE> overrides), costs (usage + list-price,
  len//4 fallback), parsing (fence-strip + validate, PEP695 generics), recorder (sha256
  cache_key + lookup), ratelimit (Redis sliding-window per provider), providers (only SDK
  import site), fake (FakeLLM + LLM_MODE=fake loader), logging (llm_calls write), router
  (structured + with_tools: replay/record cache → ratelimit → validation-retry ≤2 → cost →
  llm_calls + llm span), smoke CLI. `obs/spans.py` + `pg_exporter.py` (span→Postgres).
- Host: `poe verify` green — **74 unit** (costs 5, parsing 6, recorder 2, config 2, fake 5);
  mypy 55 files.
- Integration (tester) **4/4**: structured+fake writes llm_call+span; validation_retries=1
  on bad→good; record→replay serves cache + miss raises LLMReplayMissError; ratelimiter
  blocks the 4th call at rpm=3.
- **Live smoke 7/7 roles** (real Gemini + Groq): all servable; llm_calls rows with real
  tokens+cost (gemini 82in/114out $0.00031; groq 114in/13out $0.00008); 10 llm spans.
- **M03 complete.** Next: M04 (tool layer — registry + 9 tools + tool_calls logging).

### M02 — 2026-07-05 (platform core — DONE)
- Full 03 §1 schema in `db/models.py` (8 tables + pgvector Vector + HNSW index + partial-unique
  dedupe index); Alembic migration 0001 (extension + create_all). `db/session.py` engine/session.
- `repo/incidents.py`: state machine (STATE_TRANSITIONS) enforced by `transition()` (illegal →
  PolicyError); create/find_open_for_service/append_alert_event/list. `errors.py` hierarchy.
- `worker/` Celery app (acks_late, prefetch 1) + v0 tasks (INVESTIGATING→FAILED "graph not
  implemented (M05)"); `resume_incident` stub. API imports only the celery app to send_task by name.
- `api/` factory + routers: health (db/redis/worldstate + config echo), alerts webhook (dedupe +
  race guard, enqueue after commit), incidents (list/detail/spans/llm_calls), 501 stubs for the
  rest of 03 §4. api container runs `alembic upgrade head` before uvicorn.
- Host: `poe verify` green — **54 unit tests** (+state machine 6, alert payload 3); mypy 41 files.
- Integration (tester): **4/4** — health ready; webhook→incident→worker FAILED (full pipe);
  dedupe partial-unique-index (IntegrityError on 2nd open incident/service); alembic up→down→up
  roundtrip on a temp DB. Gate curl: fixture webhook → 201 → FAILED; approvals stub → 501.
- **M02 complete.** Next: M03 (LLM layer — router, rate limits, structured retry, record/replay).

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
| 2026-07-05 | incidents gained `service` + `status_reason` columns (not explicit in 03 §1) | `service` is required for the service-level dedupe partial-unique index + UI display; `status_reason` persists IncidentState.status_reason (why FAILED/TAKEN_OVER) | Additive columns; no shape divergence |
| 2026-07-05 | `alert_events` is a JSONB array column (03 said `jsonb[]`); migration 0001 uses `metadata.create_all` | Simpler + equivalent for append semantics; single-migration demo doesn't need per-table op.create_table | None functional |
| 2026-07-05 | ruff: allow FastAPI Depends/Query/Body in arg defaults (flake8-bugbear extend-immutable-calls) | Idiomatic FastAPI DI pattern that bugbear (B008) flags | Lint config only |
| 2026-07-05 | `settings.model_overrides()` reads `ARGUS_MODEL__*` env directly | Dynamic per-role keys can't be pydantic fields; kept in settings so env access stays there (03 §3 spec'd mechanism) | None |
| 2026-07-05 | PEP 695 generic syntax (`def f[T: BaseModel]`) in parsing/router | ruff UP047 prefers it on py3.12 | None |
| 2026-07-06 | review routing disambiguation: approve→gate; else if reviews ≥ max_review_loops → take_over; else → synthesize (revise OR reject loops back while under budget) | 04 §1 edge table only spells out revise<2→synthesize and reject≥2→take_over; this fills the reject-early / revise-late gaps deterministically and satisfies tests (b)/(c) | Behavior within plan intent ("reject after 2 loops → take_over") |
| 2026-07-06 | Budget breach carried as a transient `breached` flag inside `state["budget"]` dict | State shape (04 §2) has no routing flag; budget is a free dict ({llm_calls_used, started_at_iso}); the guard sets breached and the post-node conditional edge routes to take_over | Additive transient key; no named-state-key divergence |
| 2026-07-06 | Per-incident trace_id read from `incidents.trace_id` in each node (not a state key) | 04 §2 state has no trace_id; 03 §1 says intake writes incidents.trace_id — nodes read it so all node/llm/tool/policy spans share one trace | One small SELECT per node |
| 2026-07-06 | run_incident: nodes own all status transitions via incident_repo; the task only invokes the graph + maps unhandled errors → FAILED | Reconciles M05's "map outcomes → status" with the "no node writes status except via incident_repo" acceptance gate | None |
| 2026-07-06 | PostgresSaver built from a psycopg `Connection(autocommit=True, row_factory=dict_row)` via a per-process `lru_cache` singleton; `.setup()` on `worker_process_init` (08 #17). Graph tests use MemorySaver | langgraph-checkpoint-postgres needs a live sync connection; lazy per-fork build avoids sharing an fd across Celery prefork children | None |
| 2026-07-06 | M05 regression `-m world` tier run with the worker **paused**; `test_platform` v0 "graph not implemented → FAILED" assertion updated to M05 handoff (incident leaves OPEN) | M05 is the first milestone where the worker actively remediates; a live worker would race the world tests' own inject/remediate cycle (esp. S3 double-rollback). Worker's live behavior is proven separately by the S1/S3 live gates | World tier validates the world in isolation, as designed pre-M05 |
| 2026-07-06 | M06: interrupt side effects (approvals row + WAITING_APPROVAL) live in the worker task, not the interrupt node | LangGraph re-runs a node from the top on resume (verified by probe) — pre-interrupt side effects would double-fire | Node interior stays pure preamble + interrupt() + post-resume routing |
| 2026-07-06 | `take_over` became an interrupt (was a terminal hold in M05): parks WAITING_APPROVAL with a PENDING TAKE_OVER approval, resumes to TAKEN_OVER via `/incidents/{id}/takeover_resolution` | M06 makes every escalation a real human hand-off | M05 graph tests (c)/(d) updated to resume through the takeover interrupt |
| 2026-07-06 | Atomic decision flip via `UPDATE … RETURNING` (not `.rowcount`); takeover resolution `{root_cause, action_taken}` stored in the approval's `modified_action` jsonb | SQLAlchemy 2.0 `Result` has no typed `rowcount`; takeover has no dedicated column | Race-safe (409 on double-decide); resume reads the resolution from the row |
| 2026-07-06 | `test_hitl` drives the graph in-process (fake router + real PostgresSaver + real approvals API), not via the celery worker with baked fake scripts | Avoids shipping test fixtures in the prod image + the FakeLLM-singleton multi-incident script exhaustion; the celery→worker→resume path + worker-restart durability is proven by the live S3 gate | Deterministic HITL suite; live path covered separately |
| 2026-07-06 | M07 consolidation merge is deterministic (combine titles/contents + union fingerprints), not an LLM-merge | Consolidation is a maintenance op; deterministic merge is reliable + testable and spends no LLM quota on housekeeping | Originals still superseded_by the merged memory (acceptance met) |
| 2026-07-06 | recall/write_postmortem injected via GraphDeps (defaults = real memory fns); postmortem's memory_writer call is not billed to the investigation budget | Keeps host graph tests embedder-free; llm_calls counts investigation calls consistently across runs (matters for the memory-lift comparison) | test_memory drives the graph in-process with the real memory fns + PostgresSaver |
| 2026-07-06 | Live memory-lift used a prior clean S1 run (ecedf03b, 13 calls, no memory) as run A rather than re-running | It was already a valid clean baseline that wrote the seed memory; run B (6 calls) recalled it — both S1, memory ON | Saved one full live run; 54% lift recorded |
| 2026-07-06 | M08: parallel specialists count LLM calls in a new `spec_llm_calls: Annotated[list[int], operator.add]` channel folded into the total by `support.total_llm_calls` (not the milestone's "router callback"); added `current_step` (Send-payload carrier) + `cycle_findings_baseline` (replan-safe wave scoping) state keys | `budget` is a plain non-reducer dict — three concurrent specialists writing it = InvalidUpdateError; a reducer counter is the plan/prompt-endorsed alternative and 04 §6 budget *values* are unchanged | Additive transient state keys; no divergence from 04 §2 named shape |
| 2026-07-06 | M08: `counter_rollup` reports `llm_calls` from the authoritative DB row count (was `budget.llm_calls_used or count`) | specialists no longer bill `budget.llm_calls_used`, so the logged-row count is the accurate total incl. specialists; keeps the M07 memory-lift metric correct | Reporting only; the guard stays state-based (test_d seeds budget in state) |
| 2026-07-06 | M08 introduces a `gather` join node (not named in 04 §1) between the specialist fan-out and synthesize | The Send API needs a single fan-in anchor for the post-wave budget re-check, the >50%-degraded escalation, and the dependent-wave dispatch; per-branch checks would race/duplicate | Deterministic control-only node (no LLM, no status write); 04 §1 behaviour contract preserved |
| 2026-07-06 | M08 live parallelism proof routed supervisor+reviewer to Groq via `ARGUS_MODEL__*` env overrides for one S1 run | Gemini free-tier daily request quota was exhausted (429 RESOURCE_EXHAUSTED); the span-overlap property is provider-independent (specialists are Groq either way) | Live proof only; in-repo `models.yaml`/roles unchanged and `.env` overrides reverted after; autonomous resolution proven at M05/M07 |
| 2026-07-07 | M09: the OTLP→Jaeger sink *mirrors* each span from `obs.spans` (parent linked via an in-process span map) instead of replacing the Postgres write with an OTel SpanProcessor | our spans thread explicit parent_span_ids across LangGraph's thread pool (not OTel context); mirroring keeps the tested Postgres sink primary while giving Jaeger a correct single-rooted tree | Best-effort second sink; guarded so Jaeger off/down changes nothing |
| 2026-07-07 | M09 root `incident` span opened in the worker (not a graph node) + an in-process registry so `obs.spans` auto-parents node spans to it | avoids editing all ~15 node span sites; direct graph/unit runs (no worker) keep parentless roots, unchanged | trace_id still originates once (worker → incidents.trace_id; intake reuses it); one incident = one trace |
| 2026-07-07 | M09 live Jaeger smoke routed supervisor+reviewer to Groq (Gemini daily quota exhausted) and verified the trace via the Jaeger query API; `docs/img/jaeger.png` screenshot deferred to M12 | see [[argus-live-gate-ops]]; the span-tree hierarchy is provider-independent, and the PNG is an M12 `docs/img/` deliverable | Live-proof `.env` config reverted (gitignored) |
| 2026-07-07 | M10 added `GET /tool_calls/{id}` (sibling of the existing `/llm_calls/{id}`) and made both resolve by **span_id** as well as pk | 03 §4 lists the llm_calls drill-down but the trace tab only knows a span's `span_id`; the tool_calls table (03 §1) had no read surface. A pk-guarded lookup (`_pk_or_none`) avoids a 500 when a 16-hex span_id is passed to the UUID pk | Additive read endpoints mirroring an existing pattern; no shape of an existing endpoint changed |
| 2026-07-07 | M10 interactive browser click-through (inject S3 → Approve → RESOLVED) not driven this session | exhausted Gemini free-tier quota + offline browser-automation extension; the decide→resume→RESOLVED flow is proven by `test_hitl` (M06) and every UI-consumed endpoint returns live data | UI verified via npm gates + vitest + docker-200 + live data plumbing; interactive walkthrough pending quota/extension |
| 2026-07-07 | Added opt-in provider fallback to the M03 router (`LLM_FALLBACK=provider:model`): a rate-limited/quota-exhausted call transparently retries on the fallback model (Gemini→Groq) | user request — testing must not stall when the Gemini free-tier daily quota exhausts; Groq (llama-3.3-70b) is the already-integrated powerful free alternative | Default empty = off (no behaviour/test change); +5 unit tests; live-proven (forced 429 → Groq completed; non-429 propagates). Not a milestone — cross-cutting test-infra |
| 2026-07-10 | M11: added policy_sim auto-approver to `worker/tasks.py` (`_park_for_human` → `_auto_decide_and_resume`) | `AUTO_APPROVE=policy_sim` (07 §2) was defined in settings + echoed by /health but NEVER consumed — eval-mode APPROVE_ACTION cases (S2–S5) would park at WAITING_APPROVAL forever with no human to decide. Now auto-decides (status APPROVED, `decided_by=policy_sim`) + resumes via the existing task | Eval mode resolves autonomously; human mode unchanged (branch is policy_sim-gated); take_over self-resolves to TAKEN_OVER. Completes the 07 §2 mechanism |
| 2026-07-10 | M11: fixed recovery grading in `evals/run.py` — `_recovered_via_tail` parsed the actuator `/tail` JSON `{lines:[...]}` as raw JSONL (fed the wrapper dict to `_rule_ok_from_lines` → recovery **always false**); + poll up to 120s | pre-existing bug in 49c9cae; recovery is the graph-independent grading signal (07 §3), so a false-negative capped every case at ≤PARTIAL | +5 recovery-rederivation unit tests; live S3-v1 flipped PARTIAL→PASS |
| 2026-07-10 | M11: runner `reset()` now calls actuator `/admin/reset_worldstate` before injecting + waits for API/actuator health; `set_platform_env` verifies the `/api/health` config echo; UTF-8 stdout | 07 §2 requires a per-case worldstate clear (a prior case's bad deploy / in-memory chaos leaked into the next) + the health-echo verify; Windows cp1252 crashed the run on the →/Δ/≥ printed by the lift table | Correct per-case isolation; no schema/shape change |
| 2026-07-10 | M11: headline eval run quota-degraded (2/15) — both free-tier LLM providers exhausted (Gemini daily cap + Groq per-minute TPM under the doubled fallback load); clean full-suite + ablation re-run **deferred to fresh quota** | 08 #27 (daily caps block the run → finish next day rather than degrade); user-approved "finish now, re-run clean later". Harness validated live (S3-v1 PASS) | EVALUATION.md committed with a prominent quota caveat + honest §Failures; regenerates clean on fresh quota. Gates mechanically green |
| 2026-07-10 | M11 session: Docker Desktop was wedged (`docker-desktop` WSL2 distro Stopped while Docker Desktop.exe ran → `docker info` hangs); recovered via `wsl --shutdown` + relaunch + `up -d --wait` | environment (not code) — the recurring "Docker keeps crashing" root cause | Recorded in [[argus-live-gate-ops]]; no code impact |
| 2026-07-18 | M11 clean run: forced supervisor to `cerebras:gpt-oss-120b`; ran the S1 memory ablation twice (1st rate-degraded → "insufficient data"); **removed** the auto supervisor-model table from EVALUATION.md | Gemini free tier is per-DAY useless (~1 case); the 1st ablation's seed didn't RESOLVE under 429s so no memory was seeded; the only gemini `--suite all` comparators are quota-degraded (0–6 calls) → an unfair "model comparison" | Headline + ablation on Cerebras; ablation 2nd run clean (v1→v2 no-lift, reported honestly); EVALUATION.md comparison omitted with a note. No code changed |

## Environment facts (fill during build)

- Tooling: uv 0.11.26; project venv Python 3.12.5 (uv-managed 3.12.13 also installed).
- Locked versions of note (from uv.lock): langgraph 1.2.7, langgraph-checkpoint-postgres 3.1.0,
  langchain-core 1.4.8, langchain-google-genai 4.2.6, langchain-groq 1.1.3, celery 5.6.3,
  fastapi 0.139.0, pydantic 2.13.4, sqlalchemy 2.0.51, fastembed 0.8.0, pytest 9.1.1, ruff 0.15.20.
- LLM model ids actually used (free tier, **verified live 2026-07-05**): supervisor/reviewer/judge
  = `gemini-2.5-flash`; log/metrics/change_analyst + memory_writer = `llama-3.3-70b-versatile` (groq).
  Per-call cost ≈ $0.00031 (gemini) / $0.00008 (groq); full 7-role smoke ≈ $0.0012. Config ids in
  config/models.yaml are correct — no drift.
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
