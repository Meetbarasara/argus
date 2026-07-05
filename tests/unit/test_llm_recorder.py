import pytest

from argus.llm.recorder import cache_key

pytestmark = pytest.mark.unit

MSGS = [{"role": "user", "content": "hi"}]


def test_cache_key_deterministic():
    assert cache_key("supervisor", "m", MSGS, "Plan") == cache_key("supervisor", "m", MSGS, "Plan")


def test_cache_key_varies_by_every_input():
    base = cache_key("supervisor", "m", MSGS, "Plan")
    assert cache_key("reviewer", "m", MSGS, "Plan") != base
    assert cache_key("supervisor", "m2", MSGS, "Plan") != base
    assert cache_key("supervisor", "m", [{"role": "user", "content": "bye"}], "Plan") != base
    assert cache_key("supervisor", "m", MSGS, "Other") != base
