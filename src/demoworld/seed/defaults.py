"""Baseline service configs (03 §2) and shopdb seed data.

`ensure_config` lets each service self-bootstrap its config file on first start, so the
world comes up cleanly without an ordering dependency on the actuator's reset endpoint.
The actuator's reset also restores these same baselines.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Baseline config version, before any deploy. Deploy ids advance from d-0001.
BASELINE_VERSION = "d-0000"

SHOPAPI_DEFAULT: dict[str, Any] = {
    "version": BASELINE_VERSION,
    "payment_url": "http://paymentsvc:8000",
    "db_pool_size": 10,
    "cache_enabled": True,
    "feature_flags": {"recs_v2": False},
    "request_timeout_ms": 2000,
}

PAYMENTSVC_DEFAULT: dict[str, Any] = {
    "version": BASELINE_VERSION,
    "base_latency_ms": 40,
}

DEFAULTS: dict[str, dict[str, Any]] = {
    "shopapi": SHOPAPI_DEFAULT,
    "paymentsvc": PAYMENTSVC_DEFAULT,
}

# ~20 products seeded into shopdb by shopapi at startup.
PRODUCTS: list[tuple[int, str, float]] = [
    (1, "Aurora Desk Lamp", 39.99),
    (2, "Nimbus Wireless Mouse", 24.50),
    (3, "Tarmac Laptop Sleeve", 29.00),
    (4, "Halcyon Noise Earbuds", 79.99),
    (5, "Vertex Mechanical Keyboard", 119.00),
    (6, "Cobalt USB-C Hub", 34.95),
    (7, "Lumen Monitor Light Bar", 59.00),
    (8, "Drift Laptop Stand", 45.50),
    (9, "Pulse Webcam 1080p", 49.99),
    (10, "Meridian Desk Mat", 19.99),
    (11, "Cinder Cable Organizer", 12.50),
    (12, "Solace Wrist Rest", 17.00),
    (13, "Zephyr Portable SSD 1TB", 99.00),
    (14, "Arbor Bamboo Riser", 39.00),
    (15, "Flux Fast Charger 65W", 42.00),
    (16, "Onyx Bluetooth Speaker", 64.99),
    (17, "Willow Notebook A5", 8.99),
    (18, "Ember Mug Warmer", 27.50),
    (19, "Slate Phone Stand", 14.25),
    (20, "Quill Stylus Pen", 22.00),
]


def config_default(service: str) -> dict[str, Any]:
    """Return a fresh deep copy of a service's baseline config."""
    return json.loads(json.dumps(DEFAULTS[service]))


def ensure_config(service: str, path: str | Path) -> None:
    """Write the baseline config if the file is missing (self-bootstrap)."""
    p = Path(path)
    if p.exists():
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(config_default(service), indent=2) + "\n", encoding="utf-8")
