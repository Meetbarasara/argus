"""Text embedding via fastembed BAAI/bge-small-en-v1.5 (384-d). The model is baked into
the worker/tester image (08 #22) and loaded lazily + cached, so import is cheap and the
first embed is fast/offline at runtime."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

MODEL_NAME = "BAAI/bge-small-en-v1.5"
EMBED_DIM = 384


@lru_cache(maxsize=1)
def _model() -> Any:
    from fastembed import TextEmbedding

    return TextEmbedding(MODEL_NAME)


def embed(text: str) -> list[float]:
    vector = next(iter(_model().embed([text])))
    return [float(x) for x in vector]
