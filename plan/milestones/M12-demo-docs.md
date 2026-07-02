# M12 — Demo, Docs & Portfolio Polish

**Objective:** make the project presentable and reproducible by a stranger: a
one-command demo that walks the full storyline, a README that sells the architecture
in 30 seconds, interview notes with the numbers, and a verified fresh-clone
quickstart. This milestone is finish carpentry — no behavior changes.

**Read first:** 01 (storyline — the demo script implements it beat for beat),
07 §5/§7 (numbers + talking points feed INTERVIEW_NOTES).
**Prerequisites:** M11 green; EVALUATION.md has real numbers.

## Deliverables

| Path | Responsibility |
|---|---|
| `src/argus/demo.py` | `python -m argus.demo`: guided storyline runner — resets world+memories, prints narrated steps with pauses: inject S3 → link to watch UI → detect WAITING_APPROVAL → prompt "approve in UI (or press a to approve via API)" → wait for RESOLVED → inject S3-v2 → show memory fast-path + before/after llm_calls/MTTR comparison → print dashboard link. `--auto` flag = zero-interaction version (policy_sim approvals) for recording safety takes. LLM_MODE configurable; document `record` first / `replay` fallback for live-audience insurance (ADR-05) |
| `README.md` | hero: one-paragraph pitch + architecture diagram (mermaid: 02's diagram embedded) + demo GIF placeholder; "Why this is interesting" (the 5 resume claims from 01 mapped to code links); headline eval numbers table (from EVALUATION.md); quickstart (below); tour of the repo; ADR index (one-liners linking 02); honest limitations section (from 01 non-goals + eval failures) |
| Quickstart (in README) | exactly: clone → `cp .env.example .env` (+ 2 free API keys with signup links) → `docker compose --profile platform --profile world up -d --build` → `docker compose exec actuator python -m demoworld.inject --scenario S1` → open localhost:8081. Must work on a machine with only Docker + git (no local Python needed — everything runs in containers; the guided demo below additionally offers `docker compose exec api python -m argus.demo`) |
| `INTERVIEW_NOTES.md` | per-topic talking points with pointers: architecture walkthrough order; the 3 safety layers (reviewer, deterministic gate, HITL) with file links; memory-lift and model-comparison numbers; "what failed and why" from EVALUATION.md §Failures; scaling answers (what changes for real infra: Loki/Prometheus adapters behind the same tool interfaces, k8s operator for actuator, authz); the free-LLM story framed as robustness engineering (validation-retry, review, escalation) |
| `docs/img/` | architecture diagram export, Jaeger screenshot (M09), UI screenshots (incidents, trace drill-down, approval card, dashboard) |
| Recording checklist (in INTERVIEW_NOTES) | <5 min video beats: quiet dashboard → inject → live trace → approval with evidence → recovery → repeat-fault memory win → eval dashboard. Pre-flight: `LLM_MODE=record` dry run, then record the video against `replay` if API nerves demand |
| Housekeeping | `docker compose down -v && up --build` clean-boot test; `.env.example` complete; LICENSE (MIT); repo description + topics suggestions; final `uv run poe verify-all` |

## Steps

1. demo.py (+ `--auto`), tested via `--auto` end to end.
2. README + images + quickstart, then **execute the quickstart verbatim from a clean
   state** (`docker compose down -v`, fresh `.env` from example) — the doc is the test.
3. INTERVIEW_NOTES.md (pull real numbers from EVALUATION.md — no placeholders).
4. Housekeeping + final regression checkpoint.

## Acceptance criteria

- [ ] `python -m argus.demo --auto` runs the full storyline unattended to RESOLVED ×2
      with the memory comparison printed.
- [ ] Quickstart executed verbatim from clean volumes — every command as written.
- [ ] README numbers match EVALUATION.md (no hand-typed drift); limitations section exists.
- [ ] INTERVIEW_NOTES cites only real, current numbers and file paths that exist.
- [ ] `poe verify-all` green; working tree clean; final commit `M12: demo & docs`.

## Verification gate

```
$ docker compose down -v && docker compose --profile platform --profile world up -d --build
$ uv run python -m argus.demo --auto        → storyline completes; exit 0; comparison table printed
$ uv run poe verify-all                     → green (final regression checkpoint)
$ git status                                → clean
```

**Out of scope:** actually recording the video (user does that with the checklist);
publishing to GitHub (user's call — but the repo is ready).
