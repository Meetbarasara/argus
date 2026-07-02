# 06 — Verification Protocol (before/after gates)

The user's core requirement: **every milestone verifies the system before starting and
after finishing**, so regressions are caught at the boundary where they're cheapest to
fix. This document is the procedure; each milestone file supplies the specific gate.

## The loop

### BEFORE starting a milestone (baseline)
1. `git status` → working tree clean. If not: commit or stash-and-decide first.
2. `uv run poe verify` → must be green. If red, the previous milestone regressed or
   was mis-marked: **fix that first** and record what happened in PROGRESS
   (this is the "before test catches the bug" half of the protocol).
3. If the milestone declares compose services as prerequisites, start them and confirm
   health (`docker compose ps` — all `healthy`).
4. Record in PROGRESS: `Verify before: ✅ <date>`.

### DURING
- Test-first for pure logic (risk gate, fingerprinting, scoring, cost calc,
  validation-retry). Test-alongside for integrations.
- Run the narrowest relevant tests frequently (`pytest tests/unit/test_risk_gate.py -q`);
  run `poe verify` before any commit.
- A discovered bug gets a failing regression test *before* the fix (proves the fix).

### AFTER finishing (gate)
1. `uv run poe verify` green.
2. Run the milestone's **Verification gate** commands *verbatim* and compare each with
   its expected output. Do not substitute "similar" checks.
3. At M05, M08, M11, M12 also run `uv run poe verify-all`.
4. Record evidence in PROGRESS (commands + observed key lines).
5. Commit `M0X: <title>`.

## Failure playbook

| Situation | Action |
|---|---|
| Gate command fails | Diagnose root cause. Fix code — never the gate. Re-run the *whole* gate, not just the failed command. |
| Pre-existing test breaks (regression) | Fix before continuing the milestone; add a note in PROGRESS about which milestone introduced it. |
| Gate seems wrong/impossible as written | 03/04 win over milestone text. If genuinely wrong (typo, impossible expectation), implement the closest correct check, and log a Deviation explaining the discrepancy. |
| Flaky gate (timing) | Fix determinism (longer poll windows, explicit waits on health endpoints) — never re-run-until-green. Document the fix. |
| Blocked on missing API key / external factor | Complete everything not requiring it; mark the specific gate item `pending keys` in PROGRESS. Never fabricate gate evidence. |
| Dependency version conflict | Resolve with the nearest compatible version; record old→new in Deviations. |

## Hard prohibitions

- Never delete, skip, `xfail`, or loosen an assertion to make a gate pass.
- Never mark a milestone `done` with any red gate item.
- Never reorder milestones or start the next one on a red baseline.
- Never "verify" by reasoning that it should work — run the command.

## Gate anatomy (how milestone gates are written)

Each gate item = **command (verbatim) + expected observable**. Example:

```
$ python -m demoworld.inject --scenario S1
expected: exits 0; within 90s worldstate alerts/sent.jsonl gains a line with
rule=dependency_down, service=shopapi  (check: curl actuator
/tail?file=alerts/sent.jsonl&last=1)
```

Expected outputs are stated as observable facts (exit codes, JSON fields, row counts,
HTTP statuses), never vibes ("should look right").
