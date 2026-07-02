# M03 — LLM Layer (router, limits, structure, record/replay)

**Objective:** every LLM interaction in Argus goes through one hardened component:
role-based model routing, Redis rate limiting, structured-output validation with
feedback retries, record/replay caching, full call logging with cost. Built and tested
**before any agent exists** so agents are thin.

**Read first:** 03 §1 (llm_calls), 03 §3 (models.yaml, prices.yaml), 04 §3 (schemas it
must produce), 08 #11–#16, #27.
**Prerequisites:** M02 green. `.env` with GOOGLE_API_KEY + GROQ_API_KEY (live smoke
only; everything else runs without keys).

## Deliverables (`src/argus/llm/`)

| Path | Responsibility |
|---|---|
| `router.py` | `LLMRouter` facade: `structured(role, messages, schema, *, span_ctx) -> BaseModel` and `with_tools(role, messages, tools, *, span_ctx) -> AIMessage`; resolves role→provider/model from config + `ARGUS_MODEL__<ROLE>` overrides; orchestrates limiter → cache → provider call → parse/validate → log |
| `providers.py` | builds LangChain chat models (`langchain-google-genai`, `langchain-groq`) from models.yaml; one place that touches provider SDKs |
| `ratelimit.py` | Redis token bucket per provider (rpm from config, ±10% jitter, blocking acquire with timeout); tenacity retry policy for 429/5xx (08 #14) |
| `recorder.py` | cache_key = sha256(role + model + canonical-json(messages+schema/tool names)); modes live/record/replay against `llm_calls` (replay miss ⇒ `LLMReplayMissError`) |
| `parsing.py` | fence-stripping + Pydantic validation; on failure re-prompt with validation errors appended (≤2, 08 #12) |
| `costs.py` | usage extraction (+`len//4` fallback, 08 #15) and list-price cost from prices.yaml |
| `logging.py` | writes llm_calls rows (03 §1) + emits an `llm` OTel span (obs helpers arrive fully in M09; span emission API defined now in `argus/obs/spans.py` with the Postgres exporter minimal version) |
| `fake.py` | `FakeLLM` for tests: scripted responses keyed by (role, matcher). Also backs `LLM_MODE=fake` (03 §6): the router serves scripts from `tests/fixtures/fake_scripts/*.yaml`, giving containerized workers the same determinism (M06 uses this) — the graph-test backbone (08 #16) |
| `smoke.py` | CLI `python -m argus.llm.smoke`: per configured role → verify model id is servable, one structured call (tiny schema), print tokens/latency/cost, write llm_calls row. First step: list/validate current free-tier model ids and print guidance if config ids are stale (08 #11) |

Also: minimal `argus/obs/spans.py` + `pg_exporter.py` now (span context manager that
writes `spans` rows) — LLM/tool/node code uses this API from day one; M09 only adds
OTLP export + aggregation.

## Steps

1. costs + parsing + recorder as pure units (test-first; no network).
2. ratelimit against real Redis (integration test with rpm=3 → third call waits).
3. providers + router happy path with FakeLLM injected; then validation-retry path
   (Fake returns bad JSON once, good on retry → `validation_retries=1` logged).
4. Record/replay integration test: record with Fake, flip to replay, identical result,
   zero provider calls; replay miss raises.
5. Live smoke last (needs keys): both providers, model-id verification; update
   models.yaml + PROGRESS Environment facts with the verified ids.

## Acceptance criteria

- [ ] All agent-facing entry points (`structured`, `with_tools`) typed and documented.
- [ ] Validation-retry, rate-limit wait, 429 backoff, record/replay each unit/integration tested.
- [ ] Every call (incl. smoke) leaves an llm_calls row with tokens/cost/latency/mode/cache_key and a `spans` row (kind=llm).
- [ ] No provider SDK import outside `providers.py`; no model id outside config.
- [ ] Live smoke: one structured response from Gemini and Groq each.

## Verification gate

```
$ uv run poe verify                                → green (incl. new unit suites)
$ docker compose run --rm tester pytest tests/integration/test_llm_layer.py -q   → green
$ uv run python -m argus.llm.smoke                 → per role: model id OK, structured reply parsed,
                                                     tokens+cost printed; exit 0
$ docker compose exec postgres psql -U argus -c \
  "select role, mode, validation_retries from llm_calls order by created_at desc limit 5;"
                                                   → smoke rows present
```
If keys are absent: run everything except smoke; mark smoke `pending keys` in PROGRESS
(06 failure playbook) — do not fake it.

**Gotchas:** 08 #11–#16, #27. **Out of scope:** prompts/agents (M05), embeddings (M07).
