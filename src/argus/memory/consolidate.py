"""Memory consolidation (M07): cluster same-kind near-duplicates (cosine ≥ 0.90) and merge
each cluster into one memory (originals get ``superseded_by``); decay importance by
``0.98^days_idle`` with a 0.1 floor. Clustering is pure + golden-tested; the merge is
deterministic (a maintenance op — no LLM quota spent on housekeeping)."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

import structlog

from argus.memory.embedder import embed
from argus.memory.fingerprint import memory_embed_text
from argus.memory.pgvector_store import PgVectorStore

log = structlog.get_logger(__name__)

SIM_THRESHOLD = 0.90
DECAY = 0.98
IMPORTANCE_FLOOR = 0.1


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def cluster(
    items: list[tuple[str, list[float]]], threshold: float = SIM_THRESHOLD
) -> list[list[str]]:
    """Greedy clustering by cosine ≥ threshold. items = [(id, embedding)]; returns id groups."""
    clusters: list[list[str]] = []
    assigned: set[str] = set()
    for i, (id_i, emb_i) in enumerate(items):
        if id_i in assigned:
            continue
        group = [id_i]
        assigned.add(id_i)
        for id_j, emb_j in items[i + 1 :]:
            if id_j not in assigned and _cosine(emb_i, emb_j) >= threshold:
                group.append(id_j)
                assigned.add(id_j)
        clusters.append(group)
    return clusters


def _days_idle(memory: dict[str, Any], now: datetime) -> float:
    ts = memory.get("last_used_at") or memory.get("created_at")
    if isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts)
        except ValueError:
            ts = None
    if not isinstance(ts, datetime):
        return 0.0
    return max(0.0, (now - ts).total_seconds() / 86400.0)


def _merge(store: PgVectorStore, members: list[dict[str, Any]]) -> None:
    templates = sorted(
        {t for m in members for t in (m.get("fingerprint") or {}).get("error_templates", [])}
    )
    services = sorted(
        {s for m in members for s in (m.get("fingerprint") or {}).get("services", [])}
    )
    title = min(members, key=lambda m: len(m["title"]))["title"]  # most general title
    content = " ".join(dict.fromkeys(m["content"] for m in members))[:2000]
    fingerprint = {
        "alert_rule": members[0].get("fingerprint", {}).get("alert_rule"),
        "services": services,
        "error_templates": templates[:5],
    }
    new_id = store.add(
        kind=members[0]["kind"],
        title=title,
        content=content,
        fingerprint=fingerprint,
        embedding=embed(memory_embed_text(title, content, templates)),
        source_incident_id=members[0].get("source_incident_id"),
        importance=max(float(m.get("importance", 1.0)) for m in members),
    )
    store.supersede([m["id"] for m in members], new_id)


def consolidate(*, store: PgVectorStore | None = None) -> dict[str, int]:
    store = store or PgVectorStore()
    now = datetime.now(UTC)
    memories = store.all(limit=500)

    decayed = 0
    for memory in memories:
        idle = _days_idle(memory, now)
        if idle >= 1.0:
            new_importance = max(
                IMPORTANCE_FLOOR, float(memory.get("importance", 1.0)) * DECAY**idle
            )
            store.set_importance(memory["id"], new_importance)
            decayed += 1

    by_id = {m["id"]: m for m in memories}
    merged = 0
    for kind in {m["kind"] for m in memories}:
        members = [m for m in memories if m["kind"] == kind]
        items = [
            (
                m["id"],
                embed(
                    memory_embed_text(
                        m["title"],
                        m["content"],
                        (m.get("fingerprint") or {}).get("error_templates", []),
                    )
                ),
            )
            for m in members
        ]
        for group in cluster(items):
            if len(group) >= 2:
                _merge(store, [by_id[i] for i in group])
                merged += 1
    return {"merged": merged, "decayed": decayed}
