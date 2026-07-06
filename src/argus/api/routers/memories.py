"""Memory management API (03 §4, M07): browse (vector search when ``query`` is given,
else recency), delete (user-data story), and consolidate. Datetimes are serialized by
FastAPI's encoder."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from argus.memory.consolidate import consolidate as run_consolidate
from argus.memory.embedder import embed
from argus.memory.pgvector_store import PgVectorStore

router = APIRouter()
_store = PgVectorStore()


@router.get("/memories")
def list_memories(
    query: str | None = None, kind: str | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    if query:
        results = _store.search(embed(query), k=limit, kind=kind)
        return [{**memory, "similarity": round(similarity, 4)} for memory, similarity in results]
    return _store.all(kind=kind, limit=limit)


@router.delete("/memories/{memory_id}")
def delete_memory(memory_id: str) -> dict[str, str]:
    if not _store.delete(memory_id):
        raise HTTPException(status_code=404, detail="memory not found")
    return {"deleted": memory_id}


@router.post("/memories/consolidate")
def consolidate_memories() -> dict[str, int]:
    return run_consolidate(store=_store)
