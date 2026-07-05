"""loadgen — steady mixed traffic against shopapi so the world produces live telemetry.

70% GET /products, 30% POST /checkout by default. Concurrency and think-time are env
tunable (LOADGEN_CONCURRENCY / LOADGEN_THINK_MS) — concurrency is the lever that lets a
shrunk DB pool (S4) exhaust under load. Request failures during faults are expected and
ignored; the generator just keeps going."""

from __future__ import annotations

import os
import random
import threading
import time
from pathlib import Path

import httpx

HEARTBEAT = Path("/tmp/heartbeat")  # noqa: S108 - container-local liveness marker


def _worker(base_url: str, products_weight: float, think_s: float, stop: threading.Event) -> None:
    with httpx.Client(timeout=5.0) as client:
        while not stop.is_set():
            try:
                if random.random() < products_weight:  # noqa: S311 - not security-sensitive
                    client.get(f"{base_url}/products")
                else:
                    client.post(f"{base_url}/checkout")
            except Exception:
                pass  # faults cause failures on purpose — keep generating load
            HEARTBEAT.write_text(str(time.time()))
            time.sleep(think_s)


def main() -> None:
    base_url = os.environ.get("SHOPAPI_URL", "http://shopapi:8000")
    concurrency = int(os.environ.get("LOADGEN_CONCURRENCY", "6"))
    products_weight = float(os.environ.get("LOADGEN_PRODUCTS_WEIGHT", "0.7"))
    think_s = float(os.environ.get("LOADGEN_THINK_MS", "400")) / 1000.0

    stop = threading.Event()
    for _ in range(concurrency):
        threading.Thread(
            target=_worker, args=(base_url, products_weight, think_s, stop), daemon=True
        ).start()
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        stop.set()


if __name__ == "__main__":
    main()
