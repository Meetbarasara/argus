"""Recall (04 §4, M07): embed the alert, fetch nearest memories, re-rank by the scoring
formula, bump usage, and offer a fast-path hint when the top match is near-identical AND
its source incident actually resolved. Never raises into the graph — recall failures
degrade to "no memories"."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog

from argus.db.models import Incident
from argus.db.session import session_scope
from argus.graph.state import MemoryHit
from argus.memory import fingerprint as fp
from argus.memory.embedder import embed
from argus.memory.pgvector_store import PgVectorStore
from argus.memory.scoring import FAST_PATH_SIMILARITY, RECALL_TOP_K, score
from argus.memory.vectorstore import VectorStore
from argus.tools import worldstate

log = structlog.get_logger(__name__)


def _alert_templates(alert: dict[str, Any]) -> list[str]:
    try:
        return fp.error_templates(worldstate.read_logs(alert.get("service"), 30))
    except Exception:
        return []


def _created(memory: dict[str, Any]) -> datetime:
    created = memory.get("created_at")
    return created if isinstance(created, datetime) else datetime.now(UTC)


def _fast_path(top_memory: dict[str, Any], similarity: float) -> dict[str, Any] | None:
    """Only fire on sim > 0.92 AND a RESOLVED source incident (04 §4)."""
    if similarity <= FAST_PATH_SIMILARITY:
        return None
    source_id = top_memory.get("source_incident_id")
    if not source_id:
        return None
    with session_scope() as session:
        incident = session.get(Incident, source_id)
        if incident is None or incident.status != "RESOLVED":
            return None
        remediation = incident.remediation
    return {
        "memory_id": top_memory["id"],
        "previous_remediation": remediation,
        "similarity": round(similarity, 4),
    }


def recall(
    alert: dict[str, Any],
    *,
    store: VectorStore | None = None,
    k: int = RECALL_TOP_K,
    now: datetime | None = None,
) -> tuple[list[MemoryHit], dict[str, Any] | None]:
    store = store or PgVectorStore()
    now = now or datetime.now(UTC)
    try:
        query = fp.alert_embed_text(alert, _alert_templates(alert))
        candidates = store.search(embed(query), k=k * 3)
    except Exception:  # embedding/store failure must not break the investigation
        log.warning("recall.failed", exc_info=True)
        return [], None

    ranked = sorted(
        candidates,
        key=lambda cs: score(cs[1], _created(cs[0]), int(cs[0].get("use_count", 0)), now),
        reverse=True,
    )[:k]

    hits: list[MemoryHit] = []
    for memory, similarity in ranked:
        store.bump(memory["id"])
        hits.append(
            {
                "memory_id": memory["id"],
                "title": memory["title"],
                "content": memory["content"],
                "similarity": round(similarity, 4),
                "kind": memory["kind"],
            }
        )

    fast_path = _fast_path(*ranked[0]) if ranked else None
    return hits, fast_path
