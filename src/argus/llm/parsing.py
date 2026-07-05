"""Structured-output parsing: strip markdown fences / surrounding prose, then validate
against the Pydantic schema (08 #12). Callers catch these to drive validation-retry."""

from __future__ import annotations

import json
import re

from pydantic import BaseModel

_FENCE = re.compile(r"^```(?:json)?|```$", re.MULTILINE)


def strip_fences(text: str) -> str:
    t = text.strip()
    if "```" in t:
        t = _FENCE.sub("", t).strip()
    return t


def extract_json(text: str) -> str:
    """Best-effort isolate the JSON object even if the model added prose around it."""
    t = strip_fences(text)
    start, end = t.find("{"), t.rfind("}")
    if start != -1 and end > start:
        return t[start : end + 1]
    return t


def parse_structured[T: BaseModel](text: str, schema: type[T]) -> T:
    """Parse+validate. Raises json.JSONDecodeError or pydantic.ValidationError on failure."""
    return schema.model_validate(json.loads(extract_json(text)))
