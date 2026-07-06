"""Worker-side graph runtime: a per-process compiled graph backed by the LangGraph
PostgresSaver (08 #17 — sync saver, autocommit + dict_row, .setup() once). Kept out of
build.py so graph tests can compile with an in-memory saver and never open this
connection. The connection is created lazily (inside the worker child, after fork)."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import structlog
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg import Connection
from psycopg.rows import dict_row

from argus.graph.build import build_graph
from argus.graph.deps import default_deps
from argus.settings import get_settings

log = structlog.get_logger(__name__)


def _conn_string() -> str:
    # PostgresSaver takes a raw psycopg conn string, not SQLAlchemy's "+psycopg" URL.
    return get_settings().database_url.replace("postgresql+psycopg://", "postgresql://")


@lru_cache
def get_compiled_graph() -> Any:
    """Compile the graph once per process with a Postgres-backed checkpointer."""
    conn = Connection.connect(_conn_string(), autocommit=True, row_factory=dict_row)
    saver = PostgresSaver(conn)
    saver.setup()  # idempotent; creates the checkpointer's own tables
    log.info("graph.compiled", checkpointer="postgres")
    return build_graph(default_deps(), saver)
