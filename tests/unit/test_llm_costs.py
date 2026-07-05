from decimal import Decimal

import pytest

from argus.llm.costs import compute_cost, extract_usage, load_prices

pytestmark = pytest.mark.unit


class _Resp:
    def __init__(self, usage: dict | None) -> None:
        self.usage_metadata = usage


def test_extract_usage_from_metadata():
    r = _Resp({"input_tokens": 100, "output_tokens": 50})
    assert extract_usage(r, "prompt", "out") == (100, 50, False)


def test_extract_usage_fallback_estimate():
    ti, to, estimated = extract_usage(_Resp(None), "a" * 40, "b" * 20)
    assert estimated is True
    assert (ti, to) == (10, 5)


def test_compute_cost_known_model():
    prices = {"gemini": {"gemini-2.5-flash": {"in_per_mtok": 0.30, "out_per_mtok": 2.50}}}
    assert compute_cost("gemini", "gemini-2.5-flash", 1_000_000, 1_000_000, prices) == Decimal(
        "2.800000"
    )


def test_compute_cost_unknown_model_is_zero():
    assert compute_cost("x", "y", 100, 100, {}) == Decimal("0")


def test_load_prices_reads_real_config():
    assert "gemini" in load_prices()
