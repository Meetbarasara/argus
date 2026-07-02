# M04 — Tool Layer & Registry

**Objective:** the 9 tools from 04 §5 with a registry that enforces who may call what,
full tool_calls logging + spans, and integration proof that the tools can actually
find each scenario's evidence in the live world. Tools are plain functions — no LLM
involvement in this milestone.

**Read first:** 04 §5 (registry table — the contract), 03 §2 (file formats they read),
03 §5 (actuator API they call), 02 ADR-03 (capability model).
**Prerequisites:** M03 green; world profile running for integration tests.

## Deliverables (`src/argus/tools/`)

| Path | Responsibility |
|---|---|
| `registry.py` | `ToolSpec {name, description, args_schema, allowed_agents, risk}`; `ToolExecutor.run(agent, tool, args, *, context)` → validates args (Pydantic), enforces `allowed_agents`, **refuses risk=mutating unless context.node == "remediate"** (ADR-03/04), truncates results (≤50 items / 8KB, `truncated` flag), writes tool_calls row + `tool` span, returns result-or-structured-error (08 #13: errors are data for the LLM loop, not exceptions — but also logged status=ERROR) |
| `worldstate.py` | defensive JSONL readers (torn lines, rotation — 08 #6), time-window filtering; the only module that touches worldstate paths |
| `telemetry_tools.py` | search_logs, log_error_summary (template normalization per 04 §5), query_metrics, service_health |
| `change_tools.py` | list_deploys, deploy_diff, recent_actions (actuator GET endpoints or direct worldstate read — use worldstate read for uniformity; actuator only for mutations) |
| `remediation_tools.py` | restart_service, rollback_deploy → actuator POSTs with token; response includes actuator's result verbatim |
| `langchain_bridge.py` | expose registry entries as LangChain `Tool`s for specialist tool-loops (M05), bound per agent from `allowed_agents` |

Tests:
- unit: arg validation failures, permission denials (wrong agent; mutating outside
  remediate context), truncation, template normalization (goldens: 5 raw error lines →
  expected templates), torn-line reader.
- integration (`tests/integration/test_tools_world.py`): per scenario — inject, then
  assert the *designated* tools surface its evidence (S3 example: `list_deploys`
  shows the deploy; `deploy_diff` shows payment_url change; `search_logs
  (service=shopapi, level=ERROR)` shows 502/ConnectError; `log_error_summary` ranks the
  template #1). Plus: `rollback_deploy` restores config (world recovers); `restart_service`
  restarts shopredis (S1 recovers); both write audit trails.

## Steps

1. worldstate readers (+unit goldens under `tests/fixtures/worldstate/`).
2. registry/executor with permission tests.
3. Read tools → integration against injected scenarios.
4. Mutating tools → integration incl. recovery.
5. langchain_bridge (unit: bound toolset per agent matches 04 §5 table exactly).

## Acceptance criteria

- [ ] Registry table in code == 04 §5 table (a unit test literally asserts the matrix).
- [ ] Mutating tools unreachable outside remediate context — tested.
- [ ] Every invocation logged (tool_calls + span), including errors.
- [ ] Each scenario's evidence reachable via its designated tools against the live world.
- [ ] No tool ever raises to the caller for *expected* failures (bad args, empty
      results) — structured error strings instead; unexpected failures raise ToolError.

## Verification gate

```
$ uv run poe verify                                        → green
$ docker compose --profile world up -d
$ docker compose run --rm tester pytest tests/integration/test_tools_world.py -q   → green (all 5 scenarios)
$ docker compose exec postgres psql -U argus -c \
  "select tool, status, count(*) from tool_calls group by 1,2;"   → rows for all 9 tools, OK + ERROR paths
```

**Out of scope:** LLM anything; tool use *by* agents (M05).
