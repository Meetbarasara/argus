import pytest
from langchain_core.messages import AIMessage

from argus.llm.fake import FakeLLM

pytestmark = pytest.mark.unit


def test_single_response_is_reused():
    f = FakeLLM({"supervisor": ['{"a":1}']}).for_role("supervisor")
    assert f.invoke([]).content == '{"a":1}'
    assert f.invoke([]).content == '{"a":1}'


def test_multiple_responses_consumed_in_order_then_last_repeats():
    f = FakeLLM({"supervisor": ["bad", '{"ok":true}']}).for_role("supervisor")
    assert f.invoke([]).content == "bad"
    assert f.invoke([]).content == '{"ok":true}'
    assert f.invoke([]).content == '{"ok":true}'


def test_unknown_role_returns_empty_object():
    assert FakeLLM({}).for_role("nobody").invoke([]).content == "{}"


def test_invoke_returns_aimessage_with_usage():
    ai = FakeLLM({"r": ["x"]}).for_role("r").invoke([])
    assert isinstance(ai, AIMessage)
    assert ai.usage_metadata is not None
    assert ai.usage_metadata["input_tokens"] == 10


def test_bind_tools_returns_self():
    f = FakeLLM()
    assert f.bind_tools([]) is f
