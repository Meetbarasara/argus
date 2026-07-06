"""FakeLLM — a chat-model stand-in for deterministic tests and LLM_MODE=fake (08 #16).

Scripts map role → an ordered list of responses. When a role has multiple scripted
responses they are consumed in order (so a test can script "bad JSON, then good"); the
last one repeats once exhausted. Exposes the tiny slice of the chat-model interface the
router uses: ``bind_tools`` and ``invoke``.

Thread-safety (M08): the specialists now fan out on LangGraph's thread pool, so several
roles invoke the fake concurrently. ``for_role`` therefore returns a *bound view* carrying
its own role (never a shared ``self._role`` that a second thread could clobber between
``for_role`` and ``invoke``), and script consumption is guarded by a lock.

A response entry is normally a plain string (the message content). A ``dict`` entry may
carry ``{"content": ..., "tool_calls": [{"name", "args", "id"?}]}`` so a test can drive the
specialist tool loop (the real FakeLLM never emits tool calls otherwise)."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import yaml
from langchain_core.messages import AIMessage

FAKE_SCRIPTS_DIR = "tests/fixtures/fake_scripts"
_FALLBACK = "{}"
_USAGE = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}


def _to_message(entry: Any) -> AIMessage:
    if isinstance(entry, dict):
        tool_calls = [
            {
                "name": call["name"],
                "args": dict(call.get("args", {})),
                "id": call.get("id", f"call_{i}"),
                "type": "tool_call",
            }
            for i, call in enumerate(entry.get("tool_calls", []))
        ]
        return AIMessage(
            content=entry.get("content", ""), tool_calls=tool_calls, usage_metadata=_USAGE
        )
    return AIMessage(content=str(entry), usage_metadata=_USAGE)


class _BoundFakeLLM:
    """A role-bound view so concurrent specialists never share role/script cursor state."""

    def __init__(self, parent: FakeLLM, role: str) -> None:
        self._parent = parent
        self._role = role

    def bind_tools(self, tools: Any) -> _BoundFakeLLM:  # noqa: ARG002 - tools ignored by the fake
        return self

    def invoke(self, messages: Any) -> AIMessage:  # noqa: ARG002 - fake ignores prompt content
        return _to_message(self._parent.next_response(self._role))


class FakeLLM:
    def __init__(self, scripts: dict[str, list[Any]] | None = None) -> None:
        self._scripts: dict[str, list[Any]] = {k: list(v) for k, v in (scripts or {}).items()}
        self._lock = threading.Lock()

    def for_role(self, role: str) -> _BoundFakeLLM:
        return _BoundFakeLLM(self, role)

    def bind_tools(self, tools: Any) -> FakeLLM:  # noqa: ARG002 - kept for direct/back-compat use
        return self

    def next_response(self, role: str) -> Any:
        with self._lock:
            seq = self._scripts.get(role or "", [])
            if not seq:
                return _FALLBACK
            return seq.pop(0) if len(seq) > 1 else seq[0]


def load_fake_from_scripts(directory: str = FAKE_SCRIPTS_DIR) -> FakeLLM:
    """Build a FakeLLM from tests/fixtures/fake_scripts/*.yaml (each file: {role: [texts]})."""
    scripts: dict[str, list[Any]] = {}
    d = Path(directory)
    if d.exists():
        for f in sorted(d.glob("*.yaml")):
            data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            for role, responses in data.items():
                scripts.setdefault(role, []).extend(responses)
    return FakeLLM(scripts)
