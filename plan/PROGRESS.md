# Argus Build Progress

> Maintained by the builder. Update at the start and end of every milestone.
> Never mark a milestone `done` with a red gate.

## Milestone status

| # | Milestone | Status | Verify before | Gate after | Commit | Notes |
|---|---|---|---|---|---|---|
| M00 | Scaffold & tooling | in_progress | ✅ 2026-07-03 (empty repo) | partial — poe verify ✅; docker items pending | see log | Docker Desktop not installed; 4 docker gate cmds pending user install |
| M01 | Demo world | in_progress | ✅ 2026-07-03 (poe verify green) | partial — common/ trio unit-tested ✅; services + world gate need Docker | see log | Blocked on Docker Desktop for services + world/integration gate |
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
- **Pending (Docker Desktop not installed on host):** `docker compose config --quiet`,
  `up -d postgres redis` health, `docker compose build api shopapi`. Run these first
  thing after Docker Desktop is installed, before starting M01.

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

## Deviations log

> Anything done differently from plan/ docs: version bumps, renamed LLM model ids,
> workarounds. Format: date, what, why, impact.

| Date | Deviation | Why | Impact |
|---|---|---|---|
| 2026-07-03 | Folder not renamed to `argus`; compose pinned with `name: argus` instead | Windows locks the CWD of the running session — rename impossible mid-session | None for docker; user may rename folder later when no session is open |
| 2026-07-03 | `readme` field omitted from pyproject | README.md is an M12 deliverable; hatchling build fails on missing file | M12 re-adds the field when it creates README.md |
| 2026-07-03 | Added `.dockerignore` (not in M00 file list) | Keep build contexts small; exclude .env/plan/.venv from images | None |

## Environment facts (fill during build)

- Tooling: uv 0.11.26; project venv Python 3.12.5 (uv-managed 3.12.13 also installed).
- Locked versions of note (from uv.lock): langgraph 1.2.7, langgraph-checkpoint-postgres 3.1.0,
  langchain-core 1.4.8, langchain-google-genai 4.2.6, langchain-groq 1.1.3, celery 5.6.3,
  fastapi 0.139.0, pydantic 2.13.4, sqlalchemy 2.0.51, fastembed 0.8.0, pytest 9.1.1, ruff 0.15.20.
- LLM model ids actually used (free tier, verified live): _tbd at M03_
- Windows/Docker-Desktop: **Docker Desktop not installed yet** (user action needed);
  uv installed to `%USERPROFILE%\.local\bin` (new shells may need it on PATH).

## Open questions for the user

> Only things that would change an ADR or the product behavior. Everything else:
> conservative default + deviation entry.

- (none)
