"""``python -m argus.demo`` — the guided 5-minute storyline (01 §demo, M12).

Resets the world + memories, injects **S4** (`db_pool_exhaustion` — a bad deploy that shrinks
shopapi's DB pool; an APPROVE_ACTION rollback the free-tier model handles reliably), and narrates
the investigate → review → risk-gate → approve → remediate → learn arc; then injects the **same**
fault a second time to show the **memory fast-path** (fewer LLM calls / shorter MTTR), printed as a
side-by-side comparison. Ends by pointing at the dashboard + eval panel.

    python -m argus.demo            # interactive: pauses for you to Approve in the UI
    python -m argus.demo --auto     # zero-interaction (AUTO_APPROVE=policy_sim) — recording-safe

The orchestration takes its platform interactions as the eval harness's ``Platform`` bundle,
so the beat sequencing + the comparison renderer unit-test without docker or LLM quota;
``main`` wires the real platform (reusing the M11 runner's validated client/injector/env)."""

from __future__ import annotations

import argparse
import io
import sys
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from argus.evals.run import Platform, _real_platform, wipe_memories

S4 = "db_pool_exhaustion"  # the demo scenario — an APPROVE_ACTION deploy the free model handles
TERMINAL = {"RESOLVED", "TAKEN_OVER", "FAILED", "CLOSED"}


def _say(msg: str, pause: float = 1.2) -> None:
    """Narrate one beat, then breathe so a live audience can follow along."""
    print(msg, flush=True)
    time.sleep(pause)


def comparison_table(first: dict[str, Any], second: dict[str, Any]) -> str:
    """Memory fast-path proof (01 §demo beat 6): run 1 (cold) vs run 2 (memory) on the same
    fault — LLM calls / MTTR / memory_used, with the delta. Pure → unit-tested."""

    def g(d: dict[str, Any], k: str) -> int:
        v = d.get(k)
        return int(v) if isinstance(v, int | float) else 0

    c1, c2 = g(first, "llm_calls"), g(second, "llm_calls")
    m1, m2 = first.get("mttr_seconds"), second.get("mttr_seconds")
    # Only claim a lift when BOTH runs actually completed. A timed-out second act reports 0
    # calls, which the old formula rendered as a triumphant "100% fewer" — a lie on screen.
    if c1 and c2:
        pct = round(100 * (c1 - c2) / c1)
        delta = f"{abs(pct)}% {'fewer' if pct >= 0 else 'more'} LLM calls on the repeat incident"
    else:
        delta = "— a run did not complete, so no comparison"
    mt = lambda v: f"{v}s" if isinstance(v, int | float) else "—"  # noqa: E731
    w = 66  # inner box width — keep every row identical so the frame lines up on screen

    def row(label: str, a: str, b: str) -> str:
        return "│" + f"  {label:<14}{a:>16}{b:>18}".ljust(w) + "│"

    lines = [
        "",
        "┌" + "─ Memory lift — same fault, second time ".ljust(w, "─") + "┐",
        row("", "run 1 (cold)", "run 2 (memory)"),
        row("LLM calls", str(c1), str(c2)),
        row("MTTR", mt(m1), mt(m2)),
        row(
            "memory used",
            str(first.get("memory_used", False)),
            str(second.get("memory_used", False)),
        ),
        "│" + f"  → {delta}".ljust(w) + "│",
        "└" + "─" * w + "┘",
        "",
    ]
    return "\n".join(lines)


def _await_status(
    platform: Platform, incident_id: str, wanted: set[str], timeout: float
) -> dict[str, Any]:
    deadline = time.time() + timeout
    inc = platform.fetch_incident(incident_id)
    while time.time() < deadline and inc.get("status") not in wanted:
        time.sleep(3)
        inc = platform.fetch_incident(incident_id)
    return inc


def _one_incident(
    platform: Platform,
    params: dict[str, Any],
    *,
    auto: bool,
    approve: Any,
    label: str,
) -> dict[str, Any]:
    """Inject S4 once, narrate through to a terminal status, return the final incident."""
    platform.reset()
    since = datetime.now(UTC).isoformat()
    _say(f"⚡ Injecting {label}  (a deploy shrank shopapi's DB pool → pool timeouts under load)…")
    platform.inject(S4, params)

    incident_id = platform.await_incident(since, 120.0)
    if incident_id is None:
        _say("   …no alert fired within 120s — is the world warmed up + poller running?", 0.2)
        return {}
    _say(f"🔍 Incident {incident_id[:8]} is INVESTIGATING — watch the live trace tree in the UI.")

    inc = _await_status(platform, incident_id, {"WAITING_APPROVAL", *TERMINAL}, 300.0)
    if inc.get("status") == "WAITING_APPROVAL":
        _say("⏸  Risk gate says APPROVE_ACTION → paused for a human. The approval card shows the")
        _say("   evidence, the proposed rollback, and the agent's confidence.", 0.4)
        if auto:
            _say("   (--auto) policy_sim approves as policy dictates…")
        else:
            approve(incident_id)
        inc = _await_status(platform, incident_id, TERMINAL, 420.0)
    elif inc.get("status") not in TERMINAL:
        # --auto approves inside the graph, so WAITING_APPROVAL is never observed and the one
        # window above has to cover the whole arc (investigate → remediate → verify recovery).
        # A memory-warm act 2 measured 278s, so give it a second window instead of printing a
        # mid-flight status (REMEDIATING · 0 calls) as if it were the final result.
        _say("   …still working (remediating / verifying recovery) — waiting for the finish…", 0.4)
        inc = _await_status(platform, incident_id, TERMINAL, 420.0)

    status = inc.get("status", "?")
    icon = "✅" if status == "RESOLVED" else "🛑"
    mttr = inc.get("mttr_seconds")
    _say(
        f"{icon} → {status} · MTTR {f'{mttr}s' if isinstance(mttr, int | float) else '—'} · "
        f"{inc.get('llm_calls', 0)} LLM calls · memory_used={inc.get('memory_used', False)}"
    )
    return inc


def run_demo(platform: Platform, *, auto: bool, approve: Any, ui_url: str) -> dict[str, Any]:
    """The 7-beat storyline (01 §demo). Returns the two incidents for the comparison."""
    _say("━━━ Argus — AI on-call engineer · guided demo ━━━")
    _say(f"A quiet e-commerce world is running. Dashboard: {ui_url}", 1.5)

    _say("\n── Act 1 · a bad deploy, caught and rolled back ──")
    first = _one_incident(platform, {}, auto=auto, approve=approve, label="S4")
    if first.get("status") == "RESOLVED":
        _say("📝 A postmortem memory was written — it'll make the next one faster.", 1.5)

    _say("\n── Act 2 · the same fault recurs — memory pays off ──")
    second = _one_incident(platform, {}, auto=auto, approve=approve, label="S4 again (same fault)")

    if first and second:
        print(comparison_table(first, second), flush=True)
    _say(f"📊 Full scores, the memory-lift ablation, and every trace: {ui_url}/dashboard", 0.2)
    return {"first": first, "second": second}


# --- real wiring ---------------------------------------------------------------------
def _api_approver(api_url: str, auto: bool) -> Any:
    client = httpx.Client(base_url=api_url, timeout=15.0)

    def approve(incident_id: str) -> None:
        pend = [
            a
            for a in client.get(f"/api/incidents/{incident_id}").json().get("approvals", [])
            if a.get("status") == "PENDING"
        ]
        if not pend:
            return
        ans = input("   Approve in the UI, or press 'a' + Enter to approve via API here: ").strip()
        if ans.lower().startswith("a"):
            client.post(f"/api/approvals/{pend[-1]['id']}/decision", json={"decision": "approve"})
            print("   approved.", flush=True)
        else:
            print("   waiting for your decision in the UI…", flush=True)

    return approve


def _set_demo_env(*, auto: bool, llm_mode: str) -> None:
    """Point the platform at the demo config — MEMORY_ENABLED=true always (Act 2 needs it);
    AUTO_APPROVE=policy_sim only for --auto, else off so YOU approve in the UI — then recreate
    api+worker so they pick it up (`restart` does not reload env_file)."""
    import re
    import subprocess
    from pathlib import Path

    env = Path(".env")
    body = env.read_text(encoding="utf-8") if env.exists() else ""

    def upsert(text: str, key: str, value: str) -> str:
        line = f"{key}={value}"
        if re.search(rf"(?m)^{key}=.*$", text):
            return re.sub(rf"(?m)^{key}=.*$", line, text)
        return text + ("" if text.endswith("\n") or not text else "\n") + line + "\n"

    body = upsert(body, "MEMORY_ENABLED", "true")
    body = upsert(body, "AUTO_APPROVE", "policy_sim" if auto else "off")
    body = upsert(body, "LLM_MODE", llm_mode)
    env.write_text(body, encoding="utf-8")
    subprocess.run(["docker", "compose", "up", "-d", "api", "worker"], check=False)
    time.sleep(8)


def main(argv: list[str] | None = None) -> None:
    # Windows stdout defaults to cp1252, which can't encode the box-drawing/emoji beats — the
    # very first _say() died with UnicodeEncodeError. Force UTF-8 so the demo never dies on
    # output (same guard the eval runner's main already carries).
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="argus.demo")
    ap.add_argument("--auto", action="store_true", help="zero-interaction (policy_sim approvals)")
    ap.add_argument("--llm-mode", choices=["live", "record", "replay"], default="live")
    ap.add_argument("--api-url", default="http://localhost:8080")
    ap.add_argument("--actuator-url", default="http://localhost:8010")
    ap.add_argument("--ui-url", default="http://localhost:8081")
    ap.add_argument("--token", default="dev-actuator-token")
    args = ap.parse_args(argv)

    _set_demo_env(auto=args.auto, llm_mode=args.llm_mode)
    wipe_memories()

    platform = _real_platform(args.api_url, args.actuator_url, args.token)
    approve = _api_approver(args.api_url, args.auto)
    run_demo(platform, auto=args.auto, approve=approve, ui_url=args.ui_url)


if __name__ == "__main__":
    main()
