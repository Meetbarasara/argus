"""Unit goldens for recall scoring + fingerprinting (M07). Pure — no DB, no embedder."""

import math
from datetime import UTC, datetime, timedelta

import pytest

from argus.memory.fingerprint import (
    alert_embed_text,
    fingerprint,
    memory_embed_text,
)
from argus.memory.scoring import FAST_PATH_SIMILARITY, recency, score

pytestmark = pytest.mark.unit

NOW = datetime(2026, 7, 6, tzinfo=UTC)


# --- recency (30-day half-life) ------------------------------------------------------
def test_recency_fresh_is_one() -> None:
    assert recency(NOW, NOW) == pytest.approx(1.0)


def test_recency_halves_at_30_days() -> None:
    assert recency(NOW - timedelta(days=30), NOW) == pytest.approx(0.5)
    assert recency(NOW - timedelta(days=60), NOW) == pytest.approx(0.25)


# --- score = 0.6*sim + 0.2*recency + 0.2*log1p(use_count) ----------------------------
def test_score_fresh_high_sim_no_use() -> None:
    assert score(1.0, NOW, 0, NOW) == pytest.approx(0.8)  # 0.6 + 0.2 + 0


def test_score_uses_similarity_dominantly() -> None:
    assert score(0.5, NOW, 0, NOW) == pytest.approx(0.5)  # 0.3 + 0.2 + 0


def test_use_count_boosts_score() -> None:
    base = score(0.5, NOW, 0, NOW)
    boosted = score(0.5, NOW, 10, NOW)
    assert boosted == pytest.approx(base + 0.2 * math.log1p(10))
    assert boosted > base


def test_higher_similarity_wins_at_equal_use_count() -> None:
    assert score(0.9, NOW, 2, NOW) > score(0.6, NOW, 2, NOW)


def test_fast_path_threshold_constant() -> None:
    assert FAST_PATH_SIMILARITY == 0.92


# --- fingerprint ---------------------------------------------------------------------
def test_fingerprint_sorts_dedupes_and_caps() -> None:
    fp = fingerprint(
        alert_rule="dependency_down",
        services=["shopapi", "shopredis", "shopapi", ""],
        templates=["b", "a", "b", "c", "d", "e", "f"],
    )
    assert fp["alert_rule"] == "dependency_down"
    assert fp["services"] == ["shopapi", "shopredis"]  # sorted, deduped, no empties
    assert fp["error_templates"] == ["a", "b", "c", "d", "e"]  # sorted, deduped, capped 5


def test_fingerprint_is_deterministic() -> None:
    a = fingerprint(alert_rule="r", services=["y", "x"], templates=["t2", "t1"])
    b = fingerprint(alert_rule="r", services=["x", "y"], templates=["t1", "t2"])
    assert a == b


# --- embed-text builders -------------------------------------------------------------
def test_memory_embed_text_includes_parts() -> None:
    text = memory_embed_text("redis down", "restart fixed it", ["connection refused"])
    assert "redis down" in text and "restart fixed it" in text and "connection refused" in text


def test_alert_embed_text_includes_rule_and_service() -> None:
    alert = {"rule": "dependency_down", "service": "shopapi", "summary": "dep_up[redis]=0"}
    text = alert_embed_text(alert, ["conn refused"])
    assert "dependency_down" in text and "shopapi" in text and "conn refused" in text
