# M07 — Memory (write, recall, fast path, management)

**Objective:** incidents leave lessons behind and future incidents start smarter:
postmortem writes structured memories (pgvector), recall injects scored memories into
planning, near-identical incidents take a verification fast path, and memory is
manageable (list/search/delete/consolidate). Gate: the same fault class twice ⇒
measurably cheaper second run.

**Read first:** 03 §1 (memories), 04 (recall_memory + postmortem nodes, fast-path
rule, budgets), 07 §4 (how memory lift will be measured — build compatibly), 08 #22–#23.
**Prerequisites:** M06 green.

## Deliverables (`src/argus/memory/`)

| Path | Responsibility |
|---|---|
| `embedder.py` | fastembed bge-small-en-v1.5 (384-d); model baked into worker image (08 #22); embed(text)->list[float] |
| `vectorstore.py` | `VectorStore` Protocol: add, search(embedding, k, filter), delete, all — the Pinecone-swappable seam (ADR-01) |
| `pgvector_store.py` | implementation over memories table (cosine via pgvector) |
| `fingerprint.py` | deterministic fingerprint (03 §1) using the M04 template normalizer; embed-text builder: title + content + templates |
| `recall.py` | recall(alert) → top-5 by `0.6·sim + 0.2·recency(30d half-life) + 0.2·log1p(use_count)`; bumps use_count/last_used_at; returns MemoryHits + fast_path_hint when top sim > 0.92 and source incident RESOLVED |
| `writer.py` | postmortem pipeline: memory_writer LLM (04 §4) → PostmortemMemory + code-side fingerprint → insert; takeover resolutions become memories too (kind lesson, content includes "human resolved:") |
| `consolidate.py` | pairwise sim > 0.90 same-kind clusters → LLM-merge into one (originals get superseded_by), importance decay `0.98^days_idle`, floor 0.1 |
| `graph/nodes/recall_memory.py` + `postmortem.py` | replace M05 no-ops; recall respects MEMORY_ENABLED (off ⇒ empty hits, still a span with `memory_enabled=false`) |
| `api/routers/memories.py` | 03 §4: list/search (vector when `query` given), delete, consolidate |
| tests | unit: scoring math goldens, fingerprint goldens, fast-path threshold edges (0.92 boundary), consolidation clustering; integration: write→recall round trip on real pgvector; **the repeat test**: FakeLLM S1 run #1 (seeds memory) → S1 run #2 asserts memory_used=true, plan prompt contains the memory block, fewer specialist steps executed. Live version in the gate. |

## Steps

1. embedder + pgvector_store + Protocol (integration round trip).
2. fingerprint + scoring (pure, golden-tested).
3. recall + fast-path; wire into recall_memory node; plan prompt gets the memory block
   (04 §4 — supervisor prompt already has the slot).
4. writer + postmortem node (incl. takeover path); incident.memory_used/fast_path flags.
5. consolidate + memories API.
6. Repeat tests (Fake then live).

## Acceptance criteria

- [ ] MEMORY_ENABLED=false produces byte-identical planning prompts minus the memory
      block (ablation-clean — 07 depends on this).
- [ ] Fast path only fires on sim>0.92 AND source RESOLVED; it never skips review or
      risk_gate (assert in graph test).
- [ ] Live repeat: second S1 (or S3) run shows memory_used=true and **lower llm_calls
      than run #1** (record both counts in PROGRESS as the first memory-lift datapoint).
- [ ] Delete endpoint removes a memory and recall stops returning it.
- [ ] Consolidation merges an injected near-duplicate pair; originals superseded.

## Verification gate

```
$ uv run poe verify && uv run poe test-graph && docker compose run --rm tester pytest tests/integration/test_memory.py -q  → green
$ docker compose exec postgres psql -U argus -c "truncate memories;"     # clean slate
$ python -m demoworld.inject --scenario S1   → RESOLVED (run A) ; note llm_calls
$ python -m demoworld.inject --scenario S1   → RESOLVED (run B)
$ curl -s localhost:8080/api/incidents?limit=1 | jq '.[0] | {memory_used, llm_calls}'
        → memory_used=true, llm_calls(B) < llm_calls(A)
$ curl -s localhost:8080/api/memories | jq 'length'    → ≥2 (patterns from both runs)
```

**Gotchas:** 08 #22–#23. **Out of scope:** eval-grade lift numbers (M11), memory UI (M10).
