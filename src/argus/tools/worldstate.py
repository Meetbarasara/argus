"""The only module that reads the worldstate volume (mounted read-only in the worker).
Defensive JSONL reading (08 #6), time-window filtering, and error-template normalization.
Kept independent of the demoworld package so the platform never imports the world."""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from argus.settings import get_settings

SERVICES = ("shopapi", "paymentsvc")

_UUID = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE
)
_QUOTED = re.compile(r"""(['"]).*?\1""")
_NUM = re.compile(r"-?\d+(?:\.\d+)?")


def worldstate_dir() -> Path:
    return Path(get_settings().worldstate_path)


def read_jsonl(path: Path, *, limit: int | None = None) -> list[dict[str, Any]]:
    """Read JSONL oldest-first, skipping blank/torn lines. Missing file → []."""
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                out.append(obj)
    return out[-limit:] if limit is not None else out


def _parse_ts(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _within(ts: str, since_minutes: float, now: datetime) -> bool:
    dt = _parse_ts(ts)
    if dt is None:
        return True  # keep unparseable lines rather than silently dropping evidence
    return dt >= now - timedelta(minutes=since_minutes)


def normalize_template(msg: str) -> str:
    """Group similar error messages: lowercase, mask quoted strings / uuids / numbers,
    collapse whitespace (04 §5)."""
    t = _QUOTED.sub("<*>", msg.lower())
    t = _UUID.sub("<*>", t)
    t = _NUM.sub("<*>", t)
    return re.sub(r"\s+", " ", t).strip()


# ---- readers
def read_logs(service: str | None, since_minutes: float) -> list[dict[str, Any]]:
    now = datetime.now(UTC)
    services = [service] if service else list(SERVICES)
    out: list[dict[str, Any]] = []
    for svc in services:
        for line in read_jsonl(worldstate_dir() / "logs" / f"{svc}.jsonl"):
            if _within(str(line.get("ts", "")), since_minutes, now):
                out.append(line)
    return out


def read_metrics(
    service: str | None, metric: str | None, since_minutes: float
) -> list[dict[str, Any]]:
    now = datetime.now(UTC)
    out: list[dict[str, Any]] = []
    for line in read_jsonl(worldstate_dir() / "metrics" / "metrics.jsonl"):
        if service and line.get("service") != service:
            continue
        if metric and line.get("name") != metric:
            continue
        if _within(str(line.get("ts", "")), since_minutes, now):
            out.append(line)
    return out


def latest_health() -> dict[str, Any]:
    """Reconstruct each service's latest health snapshot from recent metrics."""
    health: dict[str, Any] = {}
    for m in read_metrics(None, None, since_minutes=5):
        svc = str(m.get("service"))
        name = m.get("name")
        value = m.get("value")
        labels = m.get("labels") or {}
        h = health.setdefault(svc, {"deps": {}, "db_pool": {}})
        if name == "dep_up":
            h["deps"][labels.get("dep", "?")] = "up" if value else "down"
        elif name == "db_pool_in_use":
            h["db_pool"]["in_use"] = value
        elif name == "db_pool_size":
            h["db_pool"]["size"] = value
        elif name is not None:
            h[name] = value
    return health


def read_deploys(since_minutes: float) -> list[dict[str, Any]]:
    now = datetime.now(UTC)
    return [
        d
        for d in read_jsonl(worldstate_dir() / "deploys" / "history.jsonl")
        if _within(str(d.get("ts", "")), since_minutes, now)
    ]


def find_deploy(deploy_id: str) -> dict[str, Any] | None:
    for d in read_jsonl(worldstate_dir() / "deploys" / "history.jsonl"):
        if d.get("deploy_id") == deploy_id:
            return d
    return None


def read_actions(since_minutes: float) -> list[dict[str, Any]]:
    now = datetime.now(UTC)
    return [
        a
        for a in read_jsonl(worldstate_dir() / "deploys" / "actions.jsonl")
        if _within(str(a.get("ts", "")), since_minutes, now)
    ]


def read_snapshot_ref(ref: str | None) -> dict[str, Any] | None:
    if not ref:
        return None
    path = worldstate_dir() / ref
    if not path.exists():
        return None
    try:
        return dict(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError):
        return None


def error_templates(lines: list[dict[str, Any]], top: int = 10) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter(
        normalize_template(str(ln.get("msg", ""))) for ln in lines if ln.get("level") == "ERROR"
    )
    return [{"template": tmpl, "count": n} for tmpl, n in counts.most_common(top)]
