# 05 — Conventions & Definition of Done

## Python

- Python 3.12, `uv` for everything (`uv sync`, `uv run`). Dependencies are added only
  via `uv add` (never hand-edit pins); notable version locks recorded in PROGRESS.
- Layout: `src/` layout, packages `argus` and `demoworld` (see 02). Tests in `tests/`,
  never inside `src/`.
- **Style:** ruff (lint + format), line length 100. Type hints everywhere in `src/`;
  mypy with `disallow_untyped_defs = true` for `src/argus`, relaxed for `tests/` and
  `src/demoworld` (it's a fixture, keep it readable, but still typed at function level).
- **Errors:** exception hierarchy in `argus/errors.py`:
  `ArgusError → ToolError, LLMError (LLMRateLimitError, LLMValidationError), PolicyError,
  WorldError`. Never bare `except:`; never swallow exceptions silently — log with context
  and re-raise or convert. Graph nodes catch only what they can handle (e.g. specialist
  catches ToolError for its retry); everything else bubbles to the task wrapper which
  marks the incident FAILED with `status_reason`.
- **Logging:** structlog, JSON output, one logger per module. Never `print` in `src/`
  (CLIs may use `rich`/stdout for human output). Log keys: `incident_id`, `node`,
  `agent`, `tool` wherever applicable. Never log secrets or full prompts (prompts go to
  `llm_calls`, not stdout).
- **Time:** timezone-aware UTC `datetime` only (`datetime.now(tz=UTC)`); ISO-8601 with
  `Z` in JSON. **Ids:** `str(uuid4())`.
- **Settings:** all env access via `argus/settings.py` (pydantic-settings). No
  `os.environ` reads anywhere else. demoworld has its own tiny `demoworld/common/settings.py`.
- **Comments:** sparse; only for non-obvious constraints (e.g. "read-only mount —
  never write here"). No narration comments.

## Testing

- Markers (registered in pyproject) and where each tier runs:
  - `unit` — pure logic; no network, no containers. Runs on the **host**.
  - `graph` — the full compiled graph with `FakeLLM`, a `world_fixture` tmp dir
    standing in for worldstate, and a `fake_actuator` (httpx MockTransport).
    Deterministic, no live LLM; needs only platform postgres (localhost:5433) for the
    checkpointer + repo writes. Runs on the **host** with platform infra up.
  - `integration` / `world` — against real compose services (worldstate volume,
    actuator, celery). These run **inside the `tester` compose service** (platform
    image, dev-deps target, worldstate mounted, service-name networking):
    `docker compose run --rm tester pytest -m integration`.
  - `e2e` — world + platform together (tester service).
  - `live_llm` — hits real APIs; excluded from all aggregate targets; run explicitly.
- Fixtures policy: `tests/conftest.py` provides `db_session` (transactional rollback),
  `fake_llm` (scripted responses keyed by role+step), `world_fixture` (tmp worldstate
  dir seeded from `tests/fixtures/worldstate/`, settings path override),
  `fake_actuator` (httpx MockTransport standing in for the actuator API), `world`
  (integration only: resets real worldstate via actuator + reseeds), `client`
  (FastAPI TestClient).
- Deterministic LLM for out-of-process runs: `LLM_MODE=fake` makes the router serve
  scripted responses from `tests/fixtures/fake_scripts/*.yaml` (keyed by role +
  matcher). In-process tests inject `FakeLLM` directly; containerized workers (HITL
  integration suite) get the same determinism via the env var.
- Every bug found during the build gets a regression test before the fix is considered
  done.

## Task runner (poethepoet — `[tool.poe.tasks]` in pyproject)

| Task | Definition |
|---|---|
| `poe fmt` | `ruff format . && ruff check --fix .` |
| `poe lint` | `ruff format --check . && ruff check .` |
| `poe types` | `mypy src` |
| `poe test` | `pytest -m unit -q` (host, no containers) |
| `poe verify` | lint + types + test (the standard gate — runs anywhere) |
| `poe test-graph` | `pytest -m graph -q` (host; platform postgres must be up) |
| `poe test-integration` | `docker compose run --rm tester pytest -m "integration or world" -q` |
| `poe verify-all` | verify + test-graph + test-integration |
| `poe up` / `poe down` | `docker compose --profile platform --profile world up -d --build` / `down` |

## Git

- Commit messages: `M0X: <imperative summary>` for milestone commits; small interim
  commits allowed (`M0X wip: ...`). No merges/rebases needed — linear history.
- Never commit: `.env`, `worldstate` contents, `node_modules`, `uv` caches,
  recorded LLM fixtures containing keys (they never should).
- `.gitattributes`: `* text=auto eol=lf` (Windows host, Linux containers).

## UI (`ui/`)

- Vite + React 18 + TypeScript strict + Tailwind. Data: TanStack Query only (no
  Redux/Zustand); poll active pages every 2–3s via `refetchInterval`.
- Routing: react-router; pages `Incidents`, `IncidentDetail`, `Approvals`, `Memory`,
  `Dashboard`. Components in `ui/src/components`, API client (typed, thin fetch
  wrapper) in `ui/src/api.ts` — response types mirror 03 §4.
- Charts: recharts. Icons: lucide-react. No component library — Tailwind only.
- Quality gates: `npm run lint` (eslint), `npm run typecheck` (tsc --noEmit),
  `npm run build`.

## Definition of Done (every milestone)

1. All acceptance criteria in the milestone file checked.
2. `poe verify` green; milestone gate commands green with expected output.
3. New logic has tests at the right tier; no weakened/skipped tests.
4. PROGRESS.md updated (status, gate evidence, deviations).
5. Committed with `M0X:` prefix. Working tree clean.
