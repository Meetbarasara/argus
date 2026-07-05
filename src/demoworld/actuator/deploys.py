"""Deploy / rollback over the worldstate config + history (ADR-02).

A "deploy" rewrites a service's hot-reloaded config file and records an auditable history
entry with before/after snapshots. Rollback restores a prior deploy's pre-change config.
This is pure filesystem logic (no Docker), so it is unit-tested on the host.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from demoworld.common.jsonlog import append_jsonl, now_iso, read_jsonl
from demoworld.seed.defaults import config_default


def get_by_path(data: dict[str, Any], path: str) -> Any:
    """Read a possibly-dotted key (e.g. ``feature_flags.recs_v2``)."""
    cur: Any = data
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def set_by_path(data: dict[str, Any], path: str, value: Any) -> None:
    """Set a possibly-dotted key, creating intermediate dicts."""
    parts = path.split(".")
    cur = data
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


class DeployManager:
    def __init__(self, worldstate: str | Path) -> None:
        self.ws = Path(worldstate)

    # ---- paths
    def _config_path(self, service: str) -> Path:
        return self.ws / "config" / f"{service}.json"

    def _history_path(self) -> Path:
        return self.ws / "deploys" / "history.jsonl"

    def _snapshot_path(self, service: str, version: str) -> Path:
        return self.ws / "deploys" / "snapshots" / service / f"{version}.json"

    def _rel(self, path: Path) -> str:
        return str(path.relative_to(self.ws)).replace(os.sep, "/")

    # ---- io
    def _read_config(self, service: str) -> dict[str, Any]:
        p = self._config_path(service)
        if p.exists():
            try:
                return dict(json.loads(p.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                pass
        return config_default(service)

    def _write_json(self, path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)  # atomic — services never read a torn config

    # ---- queries
    def history(self) -> list[dict[str, Any]]:
        return read_jsonl(self._history_path())

    def next_deploy_id(self) -> str:
        mx = 0
        for entry in self.history():
            did = str(entry.get("deploy_id", ""))
            if did.startswith("d-") and did[2:].isdigit():
                mx = max(mx, int(did[2:]))
        return f"d-{mx + 1:04d}"

    def list_deploys(self, service: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        entries = self.history()
        if service:
            entries = [e for e in entries if e.get("service") == service]
        return list(reversed(entries))[:limit]

    def find_deploy(self, deploy_id: str) -> dict[str, Any] | None:
        for entry in self.history():
            if entry.get("deploy_id") == deploy_id:
                return entry
        return None

    # ---- mutations
    def deploy(
        self, service: str, changes: dict[str, Any], message: str, author: str
    ) -> dict[str, Any]:
        cfg = self._read_config(service)
        prev_version = str(cfg.get("version", "d-0000"))
        # snapshot the current (pre-deploy) config so rollback has a target
        before_path = self._snapshot_path(service, prev_version)
        self._write_json(before_path, cfg)

        new_id = self.next_deploy_id()
        recorded: dict[str, Any] = {}
        for key, new_val in changes.items():
            recorded[key] = {"old": get_by_path(cfg, key), "new": new_val}
            set_by_path(cfg, key, new_val)
        cfg["version"] = new_id

        after_path = self._snapshot_path(service, new_id)
        self._write_json(after_path, cfg)
        self._write_json(self._config_path(service), cfg)

        entry = {
            "deploy_id": new_id,
            "ts": now_iso(),
            "service": service,
            "author": author,
            "message": message,
            "changes": recorded,
            "snapshot_before": self._rel(before_path),
            "snapshot_after": self._rel(after_path),
        }
        append_jsonl(self._history_path(), entry)
        return entry

    def rollback(self, deploy_id: str, author: str) -> dict[str, Any]:
        target = self.find_deploy(deploy_id)
        if target is None:
            raise KeyError(f"unknown deploy_id: {deploy_id}")
        service = str(target["service"])
        before_ref = self.ws / target["snapshot_before"]
        restored = dict(json.loads(before_ref.read_text(encoding="utf-8")))

        current = self._read_config(service)
        prev_version = str(current.get("version", "d-0000"))
        self._write_json(self._snapshot_path(service, prev_version), current)

        new_id = self.next_deploy_id()
        restored["version"] = new_id
        after_path = self._snapshot_path(service, new_id)
        self._write_json(after_path, restored)
        self._write_json(self._config_path(service), restored)

        reversed_changes = {
            key: {"old": chg.get("new"), "new": chg.get("old")}
            for key, chg in target.get("changes", {}).items()
        }
        entry = {
            "deploy_id": new_id,
            "ts": now_iso(),
            "service": service,
            "author": author or "rollback",
            "message": f"rollback of {deploy_id}",
            "changes": reversed_changes,
            "rollback_of": deploy_id,
            "snapshot_before": self._rel(self._snapshot_path(service, prev_version)),
            "snapshot_after": self._rel(after_path),
        }
        append_jsonl(self._history_path(), entry)
        return entry
