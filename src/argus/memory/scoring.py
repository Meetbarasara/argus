"""Recall scoring (04 §4, M07): rank candidates by
``0.6·similarity + 0.2·recency + 0.2·log1p(use_count)`` where recency has a 30-day
half-life. Pure + golden-tested; the fast-path threshold lives here too."""

from __future__ import annotations

import math
from datetime import UTC, datetime

FAST_PATH_SIMILARITY = 0.92
RECALL_TOP_K = 5
HALF_LIFE_DAYS = 30.0


def recency(created_at: datetime, now: datetime | None = None) -> float:
    """1.0 for a brand-new memory, 0.5 after 30 days, decaying exponentially."""
    now = now or datetime.now(UTC)
    days = max(0.0, (now - created_at).total_seconds() / 86400.0)
    return float(0.5 ** (days / HALF_LIFE_DAYS))


def score(
    similarity: float, created_at: datetime, use_count: int, now: datetime | None = None
) -> float:
    return 0.6 * similarity + 0.2 * recency(created_at, now) + 0.2 * math.log1p(max(0, use_count))
