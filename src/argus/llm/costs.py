"""Token usage extraction + list-price cost (03 §3 prices.yaml, 08 #15). Costs are shown
even on free tiers so the dashboard has a real dollar figure to report."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import structlog
import yaml

log = structlog.get_logger(__name__)

PRICES_YAML = "config/prices.yaml"


def load_prices(path: str = PRICES_YAML) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def extract_usage(response: Any, prompt_text: str, output_text: str) -> tuple[int, int, bool]:
    """Return (tokens_in, tokens_out, estimated). Falls back to len//4 when the provider
    omits usage metadata (08 #15)."""
    usage = getattr(response, "usage_metadata", None)
    if isinstance(usage, dict) and usage.get("input_tokens") is not None:
        return int(usage["input_tokens"]), int(usage.get("output_tokens", 0)), False
    return max(len(prompt_text) // 4, 1), max(len(output_text) // 4, 1), True


def compute_cost(
    provider: str, model: str, tokens_in: int, tokens_out: int, prices: dict[str, Any]
) -> Decimal:
    entry = prices.get(provider, {}).get(model)
    if not entry:
        log.warning("costs.unknown_model", provider=provider, model=model)
        return Decimal("0")
    cost_in = Decimal(str(entry["in_per_mtok"])) * Decimal(tokens_in) / Decimal(1_000_000)
    cost_out = Decimal(str(entry["out_per_mtok"])) * Decimal(tokens_out) / Decimal(1_000_000)
    return (cost_in + cost_out).quantize(Decimal("0.000001"))
