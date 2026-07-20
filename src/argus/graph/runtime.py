"""Worker-side graph runtime: a per-process compiled graph backed by the LangGraph
PostgresSaver (08 #17 — sync saver, autocommit + dict_row, .setup() once). Kept out of
build.py so graph tests can compile with an in-memory saver and never open this
connection. The connection is created lazily (inside the worker child, after fork)."""

from __future__ import annotations

import inspect
from functools import lru_cache
from typing import Any

import structlog
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg import Connection
from psycopg.rows import dict_row
from pydantic import BaseModel

from argus.agents import schemas
from argus.graph.build import build_graph
from argus.graph.deps import default_deps
from argus.settings import get_settings

log = structlog.get_logger(__name__)


def _conn_string() -> str:
    # PostgresSaver takes a raw psycopg conn string, not SQLAlchemy's "+psycopg" URL.
    return get_settings().database_url.replace("postgresql+psycopg://", "postgresql://")


def _checkpointed_models() -> list[type[BaseModel]]:
    """Every pydantic model in ``agents.schemas`` — IncidentState stores plan / findings /
    hypothesis / review_history directly (04 §2) and the nested ones (PlanStep, Evidence,
    RemediationAction, ReviewChecks) ride inside those. LangGraph only *warns* on unregistered
    msgpack types today but will BLOCK them in a future release — which would break the HITL
    resume, the one path that reads state back out of the checkpoint. Collected from the module
    rather than hand-listed so a schema added later can't silently fall off the allowlist;
    SAFE_MSGPACK_TYPES stay allowed regardless, so this is additive."""
    return [
        obj
        for _, obj in inspect.getmembers(schemas, inspect.isclass)
        if issubclass(obj, BaseModel) and obj.__module__ == schemas.__name__
    ]


@lru_cache
def get_compiled_graph() -> Any:
    """Compile the graph once per process with a Postgres-backed checkpointer."""
    conn = Connection.connect(_conn_string(), autocommit=True, row_factory=dict_row)
    saver = PostgresSaver(
        conn, serde=JsonPlusSerializer(allowed_msgpack_modules=_checkpointed_models())
    )
    saver.setup()  # idempotent; creates the checkpointer's own tables
    log.info("graph.compiled", checkpointer="postgres")
    return build_graph(default_deps(), saver)
