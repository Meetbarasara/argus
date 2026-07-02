# Argus — Builder Instructions

You are building **Argus**, an AI on-call engineer: a multi-agent incident-response
platform (LangGraph + FastAPI + Celery + Postgres/pgvector + React) that investigates
alerts from a demo microservice world, remediates faults, escalates to a human when
risk or uncertainty is high, and learns from past incidents.

The complete, pre-approved design lives in `plan/`. **Do not redesign it.** Your job
is faithful execution, milestone by milestone.

## Start here

1. Read `plan/00-README.md` (doc index, milestone order, builder protocol).
2. Read `plan/PROGRESS.md` to find the current milestone.
3. Read ONLY the docs listed for that milestone in the doc map, plus its milestone file.
4. Execute the milestone following the verification protocol below.

## Non-negotiable rules

- **Verify before**: at milestone start, `git status` must be clean and `uv run poe verify`
  must be green (M00 bootstraps this). If red, fix that first — it is a regression.
- **Verify after**: run `uv run poe verify` AND every command in the milestone's
  "Verification gate" section, comparing against the expected output. All green before
  the milestone is done.
- **Never** weaken, skip, or delete a failing test/gate to get to green. Fix the code.
- Update `plan/PROGRESS.md` at start (status → in_progress) and end (status → done,
  gate evidence, deviations) of every milestone.
- One git commit per milestone minimum: `M0X: <short description>`.
- Schemas, API shapes, and config formats are defined ONLY in `plan/03-data-model.md`
  and `plan/04-agents-graph.md`. Milestones cite them; never invent divergent shapes.
- Blocked or forced to deviate? Choose the most conservative option consistent with the
  plan, and log it in the Deviations section of `plan/PROGRESS.md`. Do not stop to ask
  unless the deviation would change an ADR in `plan/02-architecture.md`.

## Environment facts

- Host is **Windows 11 + Docker Desktop (WSL2)**. All application code runs in Linux
  containers; the host runs only `uv`, `pytest` (unit tier), `node` (UI dev), and `docker`.
- Never create `.sh` shell scripts — use Python entrypoints (`python -m ...`) so nothing
  breaks on Windows. `.gitattributes` enforces LF.
- Milestone gate commands are written in POSIX syntax — run them with the **Bash tool**
  (Git Bash), not PowerShell.
- Temporary/scratch files go outside the repo, never committed.
- LLM API keys (`GOOGLE_API_KEY`, `GROQ_API_KEY`) live in `.env` (gitignored). If keys are
  missing, everything except live-LLM gates still works (`LLM_MODE=replay` + fake-LLM tests);
  mark live gates as "pending keys" in PROGRESS rather than faking their results.
