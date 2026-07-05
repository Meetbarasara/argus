"""Per-provider sliding-window rate limiter over Redis (08 #14), shared across workers.
Blocks until a slot is free; raises LLMRateLimitError if it waits past max_wait."""

from __future__ import annotations

import random
import time
import uuid
from typing import cast

import redis

from argus.errors import LLMRateLimitError


def acquire(
    client: redis.Redis,
    provider: str,
    rpm: int,
    *,
    max_wait: float = 60.0,
    window: float = 60.0,
) -> float:
    """Reserve a request slot for ``provider``. Returns seconds waited."""
    key = f"ratelimit:{provider}"
    start = time.monotonic()
    deadline = start + max_wait
    while True:
        now = time.time()
        client.zremrangebyscore(key, 0, now - window)
        if cast("int", client.zcard(key)) < rpm:
            client.zadd(key, {f"{now}:{uuid.uuid4().hex[:8]}": now})
            client.expire(key, int(window) + 1)
            return time.monotonic() - start
        if time.monotonic() >= deadline:
            raise LLMRateLimitError(f"rate limit for {provider}: waited {max_wait}s")
        time.sleep(0.3 + random.uniform(0, 0.15))  # noqa: S311 - jitter, not security
