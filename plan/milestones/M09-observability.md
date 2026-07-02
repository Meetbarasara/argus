# M09 — Observability Completion

**Objective:** finish the observability story that M03–M08 have been feeding: proper
OTel SDK wiring with the dual sinks (ADR-07), the optional Jaeger profile, and the
aggregation endpoints the dashboard and interview narrative need. Small milestone —
the hard part (spans-from-day-one) already exists.

**Read first:** 02 ADR-07, 03 §1 (spans), 03 §4 (dashboard endpoint), 08 #24–#25.
**Prerequisites:** M08 green.

## Deliverables

| Path | Responsibility |
|---|---|
| `obs/otel.py` | TracerProvider setup at api/worker boot: service.name, resource attrs (git sha), **two** processors — PostgresSpanExporter (existing, now via the standard SpanProcessor interface) + OTLP→Jaeger when `OTEL_EXPORT_JAEGER=true` |
| `obs/pg_exporter.py` | finalize: batch writes, ERROR status capture, attr size cap (2KB/attr), drops nothing silently (WARN on truncation) |
| span audit | sweep all emit sites for required attrs (04 node table / 03 spans.attrs): llm spans carry role/model/tokens/cost; tool spans carry agent/tool/status; policy span carries rule_trace; human spans carry decision/latency. One unit test asserts the attr contract per kind against recorded fixtures |
| `api/routers/dashboard.py` | GET /dashboard/summary (03 §4): incidents by status; resolution & escalation rates; avg/median MTTR; cost + tokens by role/model; per-incident cost list (last 20); steps-to-diagnosis (llm span count per incident); memory usage share. Pure SQL aggregates — no Python loops over rows |
| `worker` root span | ensure every incident has exactly one root span (`incident`) whose trace_id is written to incidents.trace_id at intake (08 #24) |
| compose | jaeger service under `observability` profile; OTLP endpoint env plumbed |

Tests: unit for exporter batching/truncation + attr contracts; integration: run a
FakeLLM incident → /dashboard/summary numbers reconcile exactly with direct SQL on
incidents/llm_calls (self-consistency check).

## Steps

1. otel.py + exporter finalization; boot wiring in api and worker.
2. Span attr audit + contract test.
3. Dashboard endpoint + reconciliation test.
4. Jaeger smoke (live): one incident visible as a full tree in Jaeger UI.

## Acceptance criteria

- [ ] One incident = one trace: `select count(distinct trace_id) from spans where incident_id=…` → 1.
- [ ] Attr contract test green for all 6 span kinds.
- [ ] Dashboard numbers == SQL ground truth on a seeded dataset (test).
- [ ] With profile `observability` up, Jaeger shows the incident trace end-to-end
      (screenshot saved to `docs/img/jaeger.png` — README material).
- [ ] With Jaeger down/profile off, nothing degrades (exporter optional).

## Verification gate

```
$ uv run poe verify && docker compose run --rm tester pytest tests/integration/test_dashboard.py -q   → green
$ docker compose --profile observability up -d jaeger
$ python -m demoworld.inject --scenario S1     → RESOLVED
$ curl -s localhost:8080/api/dashboard/summary | jq '{resolution_rate, escalation_rate, avg_mttr_s, total_cost_usd}'
        → sane non-null numbers
$ # Jaeger: http://localhost:16686 → service "argus-worker" → trace shows intake…close hierarchy
```

**Out of scope:** UI rendering of any of this (M10).
