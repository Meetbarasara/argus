import json

import pytest
from pydantic import BaseModel, ValidationError

from argus.llm.parsing import extract_json, parse_structured, strip_fences

pytestmark = pytest.mark.unit


class Toy(BaseModel):
    name: str
    count: int


def test_strip_fences():
    assert strip_fences('```json\n{"a":1}\n```') == '{"a":1}'
    assert strip_fences('{"a":1}') == '{"a":1}'


def test_extract_json_ignores_surrounding_prose():
    assert extract_json('Result: {"name":"x","count":2} — done') == '{"name":"x","count":2}'


def test_parse_valid():
    t = parse_structured('{"name":"x","count":2}', Toy)
    assert t.name == "x"
    assert t.count == 2


def test_parse_fenced_json():
    assert parse_structured('```json\n{"name":"y","count":3}\n```', Toy).count == 3


def test_parse_invalid_json_raises():
    with pytest.raises(json.JSONDecodeError):
        parse_structured("not json at all", Toy)


def test_parse_schema_violation_raises():
    with pytest.raises(ValidationError):
        parse_structured('{"name":"x"}', Toy)  # missing count
