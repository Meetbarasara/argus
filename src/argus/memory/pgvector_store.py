"""pgvector-backed VectorStore over the ``memories`` table (cosine via the HNSW index).
Superseded memories (consolidation) are excluded from search + all."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from argus.db.models import Memory
from argus.db.session import session_scope


def _to_dict(m: Memory) -> dict[str, Any]:
    return {
        "id": m.id,
        "kind": m.kind,
        "title": m.title,
        "content": m.content,
        "fingerprint": m.fingerprint,
        "importance": m.importance,
        "use_count": m.use_count,
        "last_used_at": m.last_used_at,  # datetime; scoring needs it native, API serializes it
        "created_at": m.created_at,
        "source_incident_id": m.source_incident_id,
        "superseded_by": m.superseded_by,
    }


class PgVectorStore:
    def add(
        self,
        *,
        kind: str,
        title: str,
        content: str,
        fingerprint: dict[str, Any],
        embedding: list[float],
        source_incident_id: str | None = None,
        importance: float = 1.0,
    ) -> str:
        memory = Memory(
            kind=kind,
            title=title,
            content=content,
            fingerprint=fingerprint,
            embedding=embedding,
            importance=importance,
            source_incident_id=source_incident_id,
        )
        with session_scope() as session:
            session.add(memory)
            session.flush()
            return str(memory.id)

    def search(
        self, embedding: list[float], k: int, kind: str | None = None
    ) -> list[tuple[dict[str, Any], float]]:
        # cosine_distance is provided by pgvector's Vector column type
        distance = Memory.embedding.cosine_distance(embedding).label("distance")
        stmt = select(Memory, distance).where(Memory.superseded_by.is_(None))
        if kind:
            stmt = stmt.where(Memory.kind == kind)
        stmt = stmt.order_by(distance).limit(k)
        with session_scope() as session:
            rows = session.execute(stmt).all()
            session.expunge_all()
            return [(_to_dict(m), 1.0 - float(dist)) for m, dist in rows]

    def delete(self, memory_id: str) -> bool:
        with session_scope() as session:
            memory = session.get(Memory, memory_id)
            if memory is None:
                return False
            session.delete(memory)
            return True

    def all(self, kind: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        stmt = select(Memory).where(Memory.superseded_by.is_(None))
        if kind:
            stmt = stmt.where(Memory.kind == kind)
        stmt = stmt.order_by(Memory.created_at.desc()).limit(limit)
        with session_scope() as session:
            rows = list(session.scalars(stmt).all())
            session.expunge_all()
            return [_to_dict(m) for m in rows]

    def bump(self, memory_id: str) -> None:
        with session_scope() as session:
            memory = session.get(Memory, memory_id)
            if memory is not None:
                memory.use_count = (memory.use_count or 0) + 1
                memory.last_used_at = datetime.now(UTC)
                session.add(memory)

    # --- consolidation helpers (store-specific maintenance, not part of the Protocol) ---
    def supersede(self, old_ids: list[str], new_id: str) -> None:
        with session_scope() as session:
            for old in old_ids:
                memory = session.get(Memory, old)
                if memory is not None:
                    memory.superseded_by = new_id
                    session.add(memory)

    def set_importance(self, memory_id: str, importance: float) -> None:
        with session_scope() as session:
            memory = session.get(Memory, memory_id)
            if memory is not None:
                memory.importance = importance
                session.add(memory)
