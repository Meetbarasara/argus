# M10 — React UI (review console + trace explorer)

**Objective:** the human-facing console: watch incidents live, drill into the full
decision trace down to prompts and costs, approve/modify/reject escalations, browse
and manage memory, and read the dashboards. This is what the demo video shows —
polish matters here more than anywhere.

**Read first:** 03 §4 (API — the UI consumes it verbatim; api.ts types mirror it),
01 (demo storyline — every beat must be visible), 05 (UI conventions), 08 #25.
**Prerequisites:** M09 green (all endpoints real; evals endpoints still 501 — the
Dashboard eval panel renders an empty-state until M11).

## Pages & key components (`ui/src/`)

| Page (route) | Content |
|---|---|
| **Incidents** `/` | auto-refreshing table: status chip (color per state machine), severity, title, age, escalation level, cost, memory-used badge, fast-path ⚡ badge; row → detail |
| **IncidentDetail** `/incidents/:id` | header: status timeline (created → … → resolved with durations); tabs: **Trace** — collapsible span tree built from parent_span_id (indent + kind icon + name + duration + status color; click → right side panel: attrs; llm spans add prompt/response viewer via /llm_calls/{id} with token/cost header; tool spans show args/result JSON); **Hypothesis & Review** — plan, findings with evidence excerpts, hypothesis card (confidence bar), review verdicts with checks; **Remediation** — proposed vs executed action, actuator result, recovery checks; **Memory** — hits used (similarity scores) + memory written |
| **Approvals** `/approvals` | pending cards: alert summary, hypothesis + confidence, evidence excerpts, proposed action (params pretty-printed), risk level + policy rule trace, similar-past-incidents refs; buttons Approve / Modify (JSON param editor, validated server-side) / Reject (comment required); NOTIFY feed below with Ack; decided history collapsed |
| **Memory** `/memory` | search box (vector search via ?query=), kind filter, cards: title/content/kind/importance/use_count/last_used, delete (confirm), Consolidate button with result toast |
| **Dashboard** `/dashboard` | stat cards (incidents, resolution rate, escalation rate, median MTTR, total cost); charts (recharts): cost per incident (bar, last 20), tokens by role (stacked bar); eval panel: latest eval_runs table + per-case PASS/PARTIAL/FAIL grid + ablation comparison (renders "no runs yet" until M11) |

Infra: `api.ts` typed client (fetch, base `/api`); TanStack Query with
refetchInterval 2s on Incidents/Approvals/active IncidentDetail, 10s elsewhere;
error boundary + toast on API failure; empty states everywhere (a quiet system must
not look broken). Nginx serves build + proxies `/api` → api:8080 (no CORS in prod
mode); `npm run dev` against localhost:8080 with dev CORS (08 #25).

## Steps

1. Scaffold (Vite+TS+Tailwind+router+Query), api.ts against 03 §4, layout shell + nav.
2. Incidents + IncidentDetail Trace tab (the tree is the hard part: build once from
   the flat span list, memoize; unit-test tree building with a fixture of 30 spans).
3. Hypothesis/Remediation/Memory tabs.
4. Approvals incl. modify editor round trip.
5. Memory + Dashboard pages.
6. Component tests (vitest): span-tree builder, status-chip mapping, approval card
   render from fixture. E2E happens via the manual checklist (below) — no Playwright
   (deliberate scope decision).
7. `docker compose up ui` production-mode pass.

## Acceptance criteria

- [ ] `npm run lint && npm run typecheck && npm run build` clean; vitest green.
- [ ] Full storyline drivable from the browser (checklist): inject S3 → watch
      INVESTIGATING trace grow (polling) → approval card appears → Approve → status
      flows to RESOLVED → memory visible in Memory page → dashboard counters moved.
- [ ] Modify path works from the UI (change rollback target → server validates).
- [ ] Prompt drill-down shows exact prompt/response + tokens + cost for any llm span.
- [ ] Empty states: fresh DB renders cleanly on all 5 pages.
- [ ] No API shape invented: api.ts types match 03 §4 (review diff).

## Verification gate

```
$ cd ui && npm run lint && npm run typecheck && npm run build && npx vitest run   → all green
$ docker compose up -d --build ui && curl -s -o /dev/null -w '%{http_code}' localhost:8081   → 200
$ # Manual checklist (record results in PROGRESS gate evidence):
#  1. localhost:8081 shows Incidents (empty-state or history)
#  2. inject S3 → incident appears ≤5s, trace tree grows live
#  3. Approvals: card with evidence + rule trace → Approve → RESOLVED in UI
#  4. IncidentDetail: open an llm span → prompt/response + cost visible
#  5. Memory: entries present; delete works; Dashboard: counters + charts render
$ uv run poe verify        → green (host tests untouched but protocol says run it)
```

**Out of scope:** websockets/streaming (ADR-08), auth, mobile layout (desktop demo only),
eval-run *triggering* from UI (runs are CLI; UI only displays — keeps docker access host-side).
