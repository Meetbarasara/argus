"""Opt-in provider fallback (LLM_FALLBACK): a rate-limited primary call retries on the
fallback model so a Gemini free-tier exhaustion doesn't halt testing; other errors propagate."""

from __future__ import annotations

from typing import Any

import pytest

from argus.llm.router import _FallbackModel, _is_rate_limited

pytestmark = pytest.mark.unit


class _Boom:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    def bind_tools(self, _tools: Any) -> _Boom:
        return self

    def invoke(self, _messages: Any) -> Any:
        raise self.exc


class _Echo:
    def __init__(self, value: str) -> None:
        self.value = value

    def bind_tools(self, _tools: Any) -> _Echo:
        return self

    def invoke(self, _messages: Any) -> str:
        return self.value


def test_detects_rate_limit_markers_across_providers() -> None:
    assert _is_rate_limited(Exception("429 RESOURCE_EXHAUSTED: quota exceeded"))
    assert _is_rate_limited(Exception("Rate limit reached for model"))
    assert _is_rate_limited(Exception("Too Many Requests"))


def test_ignores_non_rate_limit_errors() -> None:
    assert not _is_rate_limited(Exception("400 invalid request"))
    assert not _is_rate_limited(ValueError("schema mismatch"))


def test_falls_back_when_primary_is_rate_limited() -> None:
    model = _FallbackModel(_Boom(Exception("429 RESOURCE_EXHAUSTED")), _Echo("from-fallback"))
    assert model.invoke([]) == "from-fallback"


def test_propagates_non_rate_limit_errors() -> None:
    model = _FallbackModel(_Boom(ValueError("bad schema")), _Echo("unused"))
    with pytest.raises(ValueError):
        model.invoke([])


def test_bind_tools_preserves_fallback_behaviour() -> None:
    model = _FallbackModel(_Boom(Exception("quota")), _Echo("from-fallback")).bind_tools([])
    assert isinstance(model, _FallbackModel)
    assert model.invoke([]) == "from-fallback"
