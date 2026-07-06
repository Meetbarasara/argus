"""Deterministic incident fingerprint + the text we embed (03 §1, 04 §4).

The fingerprint is computed in code (never by the LLM): {alert_rule, services[],
error_templates[]}, reusing the M04 template normalizer so "the same fault" fingerprints
identically across runs. The embed-text builders put a memory and an alert into the same
semantic space so cosine recall can match a fresh incident to a past lesson."""

from __future__ import annotations

from collections import Counter
from typing import Any

from argus.tools.worldstate import normalize_template


def error_templates(log_lines: list[dict[str, Any]], top: int = 5) -> list[str]:
    """Top normalized ERROR templates from log lines (deterministic, sorted by frequency)."""
    counts: Counter[str] = Counter(
        normalize_template(str(ln.get("msg", ""))) for ln in log_lines if ln.get("level") == "ERROR"
    )
    return [tmpl for tmpl, _ in counts.most_common(top)]


def fingerprint(*, alert_rule: str, services: list[str], templates: list[str]) -> dict[str, Any]:
    return {
        "alert_rule": alert_rule,
        "services": sorted({s for s in services if s}),
        "error_templates": sorted(set(templates))[:5],
    }


def memory_embed_text(title: str, content: str, templates: list[str]) -> str:
    tail = (" | templates: " + " ".join(templates)) if templates else ""
    return f"{title}. {content}{tail}"


def alert_embed_text(alert: dict[str, Any], templates: list[str]) -> str:
    observed = alert.get("observed", {})
    tail = (" | templates: " + " ".join(templates)) if templates else ""
    return (
        f"{alert.get('rule')} on {alert.get('service')}: {alert.get('summary') or observed}{tail}"
    )
