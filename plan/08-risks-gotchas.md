# 08 — Known Risks & Gotchas (read before the milestone that hits them)

Ordered by the milestone where each first bites.

## M00 — Host & repo

1. **Folder name has a space** (`Agentic project`). Docker Compose derives the project
   name from it and some tooling dislikes spaces. M00 step 0 recommends renaming the
   folder to `argus` before `git init`; if the user's session can't rename (folder in
   use), set `name: argus` at the top of docker-compose.yml and proceed — log a note.
2. **CRLF.** Windows host + Linux containers: commit `.gitattributes` (`* text=auto
   eol=lf`) in the very first commit, before any other file. Never write `.sh` scripts;
   all entrypoints are `python -m ...` (works identically in containers and on host).
3. **Long paths / OneDrive.** If the repo sits under OneDrive sync, `node_modules` and
   `uv` caches cause pain — recommend a plain path like `C:\dev\argus` (note, not blocker).

## M01 — Demo world

4. **Docker socket on Docker Desktop.** Mount `/var/run/docker.sock` into the actuator
   (works on WSL2 backend). The actuator restarts services by compose label
   (`com.docker.compose.service=<name>`), not container name — container names vary with
   the project name.
5. **Containers → host webhooks.** alertwatch's webhook URL is configurable; in M01
   (no platform yet) tests read `worldstate/alerts/sent.jsonl` instead — alertwatch
   *always* appends there and treats the webhook POST as best-effort (3 retries, then log).
6. **File growth & partial lines.** JSONL files grow unbounded: poller/services check
   size on write and rotate at 50MB (truncate-to-recent is fine for a demo). Readers
   must skip malformed/partial trailing lines (read defensively, never crash on a torn
   write).
7. **Determinism of stats.** The rolling 60s window lives in-process per service; a
   service restart resets it (expected — that's *why* verify_recovery waits for two
   consecutive OK checks). Loadgen must send steady traffic (≈5 rps) or error *rates*
   get noisy; keep request mix constant.

## M02 — Platform core

8. **Alembic + pgvector.** First migration must `CREATE EXTENSION IF NOT EXISTS vector`.
   The HNSW index is created in the same migration as the `memories` table (empty-table
   index build is instant).
9. **Celery on Windows** is broken (prefork). Non-issue here — worker runs only in
   Linux containers. Never add a "run worker on host" convenience path.
10. **Alert dedupe race.** Two webhook posts can race; guard with a partial unique
    index on incidents (service) WHERE status not terminal, and catch the
    IntegrityError as the dedupe path. (Dedupe is service-level — see 03 §4.)

## M03 — LLM layer

11. **Model id drift.** Free-tier model ids change (e.g. Gemini Flash versions, Groq
    catalog). M03's first step is a live "list/verify models" smoke; record the chosen
    ids in PROGRESS and config. Never hardcode ids outside `config/models.yaml`.
12. **Gemini structured output**: use `with_structured_output` (json mode). Quirks:
    occasionally wraps JSON in markdown fences or returns trailing text — the router's
    parser strips fences before Pydantic validation; validation failure → retry with
    the error appended (max 2), then raise `LLMValidationError`.
13. **Groq tool calling** is OpenAI-style and reliable, but weaker models sometimes
    call tools with wrong arg names — tool executor returns a structured error string
    (not an exception) so the loop can self-correct within its retry budget.
14. **429 handling.** Free tiers throttle hard. Router order: local Redis token bucket
    (configured RPM, small jitter) → tenacity exponential backoff on 429/5xx (max 5,
    cap 60s) → count `Retry-After` if present. Rate-limit state is per-provider, shared
    across workers via Redis.
15. **Token usage metadata** differs per provider (`usage_metadata` on LangChain
    messages normalizes most of it); when absent, estimate `len(text)//4` and mark
    `attrs.estimated=true`.
16. **Replay cache invalidation.** Any prompt change ⇒ new cache key ⇒ replay misses.
    Graph-test fixtures therefore use the FakeLLM (scripted by role+step), not recorded
    live replays; recorded replays are for demos/smoke only.

## M05/M06 — Graph & HITL

17. **Checkpointer setup.** `PostgresSaver` needs `.setup()` once at worker start
    (idempotent). Use the sync saver + sync graph (ADR-06). Connection kwargs:
    `autocommit=True`, `row_factory=dict_row` per langgraph-checkpoint-postgres docs.
18. **Interrupt semantics.** `graph.invoke(...)` returns with `__interrupt__` info when
    paused; the Celery task detects it, writes the approvals row, sets
    WAITING_APPROVAL, and *ends*. Resume = new Celery task calling
    `graph.invoke(Command(resume=payload), config={thread_id})`. Test both halves in
    integration (kill nothing — the pause IS the task boundary).
19. **Resume idempotency.** Decision endpoint flips approval status PENDING→decided
    atomically (`UPDATE ... WHERE status='PENDING'` returning); only a successful flip
    enqueues resume. Duplicate resumes for an already-running thread: the resume task
    re-checks incident status first and no-ops.
20. **Send API + interrupt.** Parallel specialist branches (M08) must all join at
    `synthesize` *before* any interrupt can occur (interrupts live after the join) —
    keep it that way; interrupting inside a fan-out is where LangGraph dragons live.
21. **State bloat.** Checkpoints persist full state every superstep — cap evidence
    excerpts (schema caps in 04) and never put raw tool dumps in state (findings carry
    excerpts + refs; full results live in tool_calls).

## M07 — Memory

22. **fastembed model download** happens at first use — bake it into the worker image
    (`RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5')"`)
    so runtime is offline and fast.
23. **Memory leakage between eval conditions.** The eval runner truncates `memories`
    between ablation conditions (07 §4). Never share memory across model-comparison
    runs either.

## M09–M11

24. **OTel span/trace ids** are 8/16-byte hex — store as hex strings; derive nothing
    from incident uuid except via the tracer's own ids (map incident→trace via the
    root span attribute + incidents.trace column... incidents stores `trace_id` when
    the root span opens).
25. **CORS in dev.** Vite dev server (5173) → api 8080 needs CORS; nginx (8081)
    proxies `/api` so prod-mode needs none. Enable permissive CORS only when
    `settings.dev_mode`.
26. **Eval wall-clock.** 15 cases × world reset (~30s) + warmup (~30s) + investigation
    (1–4 min) ≈ 60–90 min. The runner prints per-case progress and supports `--suite S3`
    for debugging single cases. Don't "optimize" by shortening warmups below what the
    rolling window needs (60s), or metrics lie.

## Cross-cutting

27. **Free-tier daily quotas.** Development discipline: `LLM_MODE=record` during graph
    bring-up, replay for iteration; live runs are deliberate (smokes, evals, demos).
    If a 429 storm hits daily caps, stop and note it — don't churn retries.
28. **The plan is not the enemy.** When implementation friction appears, the answer is
    usually in 03/04/08; deviate only with a PROGRESS entry. If an ADR seems wrong,
    stop and surface it to the user in Open questions rather than silently re-architecting.
