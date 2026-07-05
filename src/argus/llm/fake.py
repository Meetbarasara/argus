"""FakeLLM — a chat-model stand-in for deterministic tests and LLM_MODE=fake (08 #16).

Scripts map role → an ordered list of response texts. When a role has multiple scripted
responses they are consumed in order (so a test can script "bad JSON, then good"); the
last one repeats once exhausted. Exposes the tiny slice of the chat-model interface the
router uses: ``bind_tools`` and ``invoke``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from langchain_core.messages import AIMessage

FAKE_SCRIPTS_DIR = "tests/fixtures/fake_scripts"
_FALLBACK = "{}"


class FakeLLM:
    def __init__(self, scripts: dict[str, list[str]] | None = None) -> None:
        self._scripts: dict[str, list[str]] = {k: list(v) for k, v in (scripts or {}).items()}
        self._role: str | None = None

    def for_role(self, role: str) -> FakeLLM:
        self._role = role
        return self

    def bind_tools(self, tools: Any) -> FakeLLM:  # noqa: ARG002 - tools ignored by the fake
        return self

    def _next_text(self) -> str:
        seq = self._scripts.get(self._role or "", [])
        if not seq:
            return _FALLBACK
        return seq.pop(0) if len(seq) > 1 else seq[0]

    def invoke(self, messages: Any) -> AIMessage:  # noqa: ARG002 - fake ignores prompt content
        return AIMessage(
            content=self._next_text(),
            usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        )


def load_fake_from_scripts(directory: str = FAKE_SCRIPTS_DIR) -> FakeLLM:
    """Build a FakeLLM from tests/fixtures/fake_scripts/*.yaml (each file: {role: [texts]})."""
    scripts: dict[str, list[str]] = {}
    d = Path(directory)
    if d.exists():
        for f in sorted(d.glob("*.yaml")):
            data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            for role, responses in data.items():
                scripts.setdefault(role, []).extend(responses)
    return FakeLLM(scripts)
