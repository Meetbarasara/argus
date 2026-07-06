"""VectorStore Protocol — the Pinecone-swappable seam (ADR-01). Recall/writer/consolidate
depend only on this interface; ``pgvector_store`` is the concrete implementation. Memories
cross the boundary as plain dicts so a different backend needs no ORM."""

from __future__ import annotations

from typing import Any, Protocol


class VectorStore(Protocol):
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
        """Insert a memory, return its id."""
        ...

    def search(
        self, embedding: list[float], k: int, kind: str | None = None
    ) -> list[tuple[dict[str, Any], float]]:
        """Nearest memories (non-superseded) as (memory_dict, cosine_similarity), best first."""
        ...

    def delete(self, memory_id: str) -> bool: ...

    def all(self, kind: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        """Most recent memories (non-superseded)."""
        ...

    def bump(self, memory_id: str) -> None:
        """Record a use: use_count += 1, last_used_at = now."""
        ...
