"""Structured JSONL logging + defensive reading for the demo world (03 §2, 08 #6).

Services append 03 §2 log records to ``worldstate/logs/<service>.jsonl``. Readers must
tolerate torn trailing lines from concurrent writes, so :func:`read_jsonl` skips any
line that does not parse instead of raising.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROTATE_BYTES = 50 * 1024 * 1024  # 50MB safety valve (08 #6)


def now_iso() -> str:
    """UTC ISO-8601 with millisecond precision and a ``Z`` suffix (03 §2)."""
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def log_line(service: str, level: str, msg: str, **fields: Any) -> dict[str, Any]:
    """Build a 03 §2 log record. ``None`` fields are dropped so lines stay compact."""
    rec: dict[str, Any] = {"ts": now_iso(), "service": service, "level": level, "msg": msg}
    rec.update({k: v for k, v in fields.items() if v is not None})
    return rec


def read_jsonl(path: str | Path, *, limit: int | None = None) -> list[dict[str, Any]]:
    """Read a JSONL file oldest-first, skipping blank/torn lines (08 #6).

    Missing files yield ``[]``. ``limit`` returns only the most recent N records.
    """
    p = Path(path)
    if not p.exists():
        return []
    out: list[dict[str, Any]] = []
    with p.open("r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue  # partial write / torn line — skip defensively
            if isinstance(obj, dict):
                out.append(obj)
    if limit is not None:
        out = out[-limit:]
    return out


class JsonLogger:
    """Appends JSON records to ``<logs_dir>/<service>.jsonl`` with size-based rotation."""

    def __init__(
        self, logs_dir: str | Path, service: str, *, rotate_bytes: int = ROTATE_BYTES
    ) -> None:
        self._dir = Path(logs_dir)
        self._service = service
        self._path = self._dir / f"{service}.jsonl"
        self._rotate_bytes = rotate_bytes

    @property
    def path(self) -> Path:
        return self._path

    def write(self, level: str, msg: str, **fields: Any) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        self._maybe_rotate()
        rec = log_line(self._service, level, msg, **fields)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")

    def _maybe_rotate(self) -> None:
        try:
            size = self._path.stat().st_size
        except FileNotFoundError:
            return
        if size >= self._rotate_bytes:
            backup = Path(f"{self._path}.1")
            backup.unlink(missing_ok=True)
            self._path.rename(backup)
