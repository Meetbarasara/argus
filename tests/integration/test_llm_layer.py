"""LLM layer integration (tester container): the router's structured path with a FakeLLM
writes llm_calls + span rows, validation-retry is counted, record→replay serves from cache
(and misses raise), and the Redis rate limiter blocks when a provider is exhausted.

    docker compose --profile platform up -d
    docker compose run --rm tester pytest -q -m integration tests/integration/test_llm_layer.py
"""

from __future__ import annotations

import time
import uuid

import pytest
import redis
from langchain_core.messages import HumanMessage
from pydantic import BaseModel

from argus.db.models import LLMCall, Span
from argus.db.session import get_sessionmaker
from argus.errors import LLMReplayMissError
from argus.llm.fake import FakeLLM
from argus.llm.ratelimit import acquire
from argus.llm.router import LLMRouter
from argus.settings import get_settings

pytestmark = pytest.mark.integration


class Reply(BaseModel):
    ok: bool
    n: int


def _latest_call(role: str) -> LLMCall:
    session = get_sessionmaker()()
    try:
        return (
            session.query(LLMCall)
            .filter(LLMCall.role == role)
            .order_by(LLMCall.created_at.desc())
            .first()
        )
    finally:
        session.close()


def test_structured_with_fake_writes_llm_call_and_span():
    router = LLMRouter(mode="fake", fake=FakeLLM({"supervisor": ['{"ok": true, "n": 7}']}))
    out = router.structured("supervisor", [HumanMessage(content=f"q-{uuid.uuid4()}")], Reply)
    assert out.ok is True and out.n == 7

    call = _latest_call("supervisor")
    assert call.mode == "fake"
    assert call.cache_key
    assert call.response["parsed"] == {"ok": True, "n": 7}
    session = get_sessionmaker()()
    try:
        sp = session.get(Span, call.span_id)
        assert sp is not None and sp.kind == "llm"
        assert sp.attrs["role"] == "supervisor"
    finally:
        session.close()


def test_validation_retry_is_counted():
    router = LLMRouter(
        mode="fake", fake=FakeLLM({"reviewer": ["not json at all", '{"ok": true, "n": 1}']})
    )
    out = router.structured("reviewer", [HumanMessage(content=f"q-{uuid.uuid4()}")], Reply)
    assert out.n == 1
    assert _latest_call("reviewer").validation_retries == 1


def test_record_then_replay_serves_cache_and_miss_raises():
    marker = uuid.uuid4().hex
    rec = LLMRouter(mode="record", fake=FakeLLM({"judge": ['{"ok": true, "n": 42}']}))
    out1 = rec.structured("judge", [HumanMessage(content=marker)], Reply)

    replay = LLMRouter(mode="replay")  # no fake, no provider — cache only
    out2 = replay.structured("judge", [HumanMessage(content=marker)], Reply)
    assert out1 == out2

    with pytest.raises(LLMReplayMissError):
        replay.structured("judge", [HumanMessage(content=f"unseen-{marker}")], Reply)


def test_ratelimiter_blocks_when_provider_exhausted():
    client = redis.Redis.from_url(get_settings().redis_url)
    provider = f"test-{uuid.uuid4().hex[:8]}"
    for _ in range(3):
        assert acquire(client, provider, rpm=3, window=3.0) < 0.5
    started = time.monotonic()
    acquire(client, provider, rpm=3, window=3.0, max_wait=10.0)
    assert time.monotonic() - started > 1.0  # had to wait for a slot to age out
