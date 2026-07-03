"""Hot-reloadable JSON config for demo-world services (ADR-02).

A "deploy" is an actuator write to ``worldstate/config/<service>.json``. Services poll
that file every few seconds; when the ``version`` changes they pick up the new config
without restarting. Reads are defensive: a missing or malformed file keeps the last
known-good config so a torn write never crashes a service.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any


class HotConfig:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._current: dict[str, Any] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.reload()

    @property
    def current(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._current)

    @property
    def version(self) -> str:
        return str(self.current.get("version", ""))

    def get(self, key: str, default: Any = None) -> Any:
        return self.current.get(key, default)

    def reload(self) -> bool:
        """Re-read the file. Returns True iff ``version`` changed. Keeps last-known on error."""
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return False
        if not isinstance(data, dict):
            return False
        with self._lock:
            changed = data.get("version") != self._current.get("version")
            self._current = data
        return changed

    def start(self, interval: float = 5.0) -> None:
        """Begin polling the config file on a daemon thread (no-op if already started)."""
        if self._thread is not None:
            return

        def _loop() -> None:
            while not self._stop.wait(interval):
                self.reload()

        self._thread = threading.Thread(target=_loop, daemon=True, name="hotconfig")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
