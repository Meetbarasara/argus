"""shopapi — storefront API. Talks to shopdb (Postgres) and shopredis (cache), and
calls paymentsvc on checkout. Its config is hot-reloaded (ADR-02), so a "deploy" that
rewrites the config file changes behavior live. Each fault scenario shows up here:

- S1 redis_down: when ``cache_enabled`` and shopredis is unreachable, /products raises a
  redis ConnectionError -> 5xx, and dep_up{redis} goes to 0.
- S2 payment_latency: paymentsvc chaos makes /pay exceed ``request_timeout_ms`` -> /checkout
  times out -> 502 + elevated checkout latency.
- S3 bad_deploy_env: a deploy points ``payment_url`` at an unreachable host -> /checkout
  ConnectError -> 502.
- S4 db_pool_exhaustion: a deploy shrinks ``db_pool_size`` -> under load the pool times out
  -> /products 5xx (PoolTimeout) + latency.
- S5 feature_flag_500: a deploy enables ``feature_flags.recs_v2`` -> /products raises -> 5xx.

Handlers are sync ``def`` so FastAPI runs them in its threadpool; that keeps the blocking
psycopg / redis / httpx calls off the event loop and makes DB-pool contention real.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any, cast

import httpx
import psycopg
import redis
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from psycopg_pool import ConnectionPool
from redis.backoff import NoBackoff
from redis.retry import Retry

from demoworld.common import settings
from demoworld.common.hotconfig import HotConfig
from demoworld.common.jsonlog import JsonLogger
from demoworld.common.stats import RollingStats
from demoworld.seed.defaults import PRODUCTS, ensure_config

SERVICE = "shopapi"

# Per-request DB hold on /products (the "live inventory check"). This is the lever that
# lets S4 exhaust a size-2 pool under load while a size-10 pool copes; tuned with loadgen
# concurrency when the world gate runs. It is a fixed cost, never fault-injected.
DB_WORK_SECONDS = 0.15
POOL_ACQUIRE_TIMEOUT = 0.75


def _ensure_schema(dsn: str) -> None:
    last: Exception | None = None
    for _ in range(15):
        try:
            with psycopg.connect(dsn, autocommit=True, connect_timeout=3) as conn:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS products "
                    "(id int PRIMARY KEY, name text NOT NULL, price numeric NOT NULL)"
                )
                conn.cursor().executemany(
                    "INSERT INTO products (id, name, price) VALUES (%s, %s, %s) "
                    "ON CONFLICT (id) DO NOTHING",
                    PRODUCTS,
                )
            return
        except Exception as exc:  # shopdb may still be warming up
            last = exc
            time.sleep(1)
    raise RuntimeError(f"shopdb schema init failed after retries: {last}")


def create_app(*, start_polling: bool = True, seed_schema: bool = True) -> FastAPI:
    cfg_path = settings.config_path(SERVICE)
    ensure_config(SERVICE, cfg_path)
    config = HotConfig(cfg_path)
    if start_polling:
        config.start(5.0)
    stats = RollingStats()
    log = JsonLogger(settings.logs_dir(), SERVICE)

    dsn = settings.shopdb_url()
    # No retries + short timeouts so a redis outage (S1) fails fast (~0.3s) instead of
    # stalling ~4s on connection retries — otherwise the poller's timeout skips the
    # snapshot and the outage never shows up in metrics.
    rds = redis.Redis.from_url(
        settings.shopredis_url(),
        socket_connect_timeout=0.3,
        socket_timeout=0.3,
        retry_on_timeout=False,
        retry=Retry(NoBackoff(), 0),
        decode_responses=True,
    )
    if seed_schema:
        _ensure_schema(dsn)

    pool_state: dict[str, Any] = {"pool": None, "size": None}
    pool_lock = threading.Lock()
    payment_state: dict[str, bool] = {"up": True}

    def get_pool() -> ConnectionPool:
        size = int(config.get("db_pool_size", 10))
        with pool_lock:
            if pool_state["pool"] is None or pool_state["size"] != size:
                old = pool_state["pool"]
                pool_state["pool"] = ConnectionPool(
                    conninfo=dsn,
                    min_size=1,
                    max_size=size,
                    timeout=POOL_ACQUIRE_TIMEOUT,
                    kwargs={"autocommit": True},
                    open=True,
                )
                pool_state["size"] = size
                if old is not None:
                    old.close()
            return pool_state["pool"]

    def record_ok(t0: float) -> None:
        stats.record(latency_ms=(time.perf_counter() - t0) * 1000, is_error=False)

    def record_error(t0: float, path: str, status: int, exc: Exception) -> JSONResponse:
        latency = (time.perf_counter() - t0) * 1000
        stats.record(latency_ms=latency, is_error=True)
        err_type = type(exc).__name__
        log.write(
            "ERROR",
            f"{path} failed: {exc}",
            path=path,
            status=status,
            err_type=err_type,
            latency_ms=round(latency),
        )
        return JSONResponse(status_code=status, content={"error": str(exc), "err_type": err_type})

    def load_products(cfg: dict[str, Any]) -> list[dict[str, Any]]:
        # Live inventory check — always hits the DB pool (this is what S4 exhausts).
        pool = get_pool()
        with pool.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT pg_sleep(%s)", (DB_WORK_SECONDS,))
            cur.execute("SELECT count(*) FROM products")
            _ = cur.fetchone()
        # Catalog body — served from cache when enabled (redis is on the hot path -> S1).
        if cfg.get("cache_enabled", True):
            cached = cast("str | None", rds.get("products:v1"))
            if cached is not None:
                return list(json.loads(cached))
        pool = get_pool()
        with pool.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT id, name, price FROM products ORDER BY id")
            rows = [{"id": r[0], "name": r[1], "price": float(r[2])} for r in cur.fetchall()]
        if cfg.get("cache_enabled", True):
            rds.setex("products:v1", 30, json.dumps(rows))
        return rows

    app = FastAPI(title=SERVICE)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/products")
    def products() -> Any:
        t0 = time.perf_counter()
        cfg = config.current
        try:
            if cfg.get("feature_flags", {}).get("recs_v2"):
                raise RuntimeError("recs_v2 recommender failed to load")  # S5
            rows = load_products(cfg)
            record_ok(t0)
            return {"products": rows, "count": len(rows)}
        except Exception as exc:
            return record_error(t0, "/products", 500, exc)

    @app.post("/checkout")
    def checkout() -> Any:
        t0 = time.perf_counter()
        cfg = config.current
        payment_url = str(cfg.get("payment_url", ""))
        timeout_s = float(cfg.get("request_timeout_ms", 2000)) / 1000.0
        try:
            with httpx.Client(timeout=timeout_s) as client:
                resp = client.post(f"{payment_url}/pay")
                resp.raise_for_status()
            payment_state["up"] = True
            record_ok(t0)
            return {"status": "ok"}
        except Exception as exc:
            payment_state["up"] = False
            return record_error(t0, "/checkout", 502, exc)

    @app.get("/internal/stats")
    def internal_stats() -> dict[str, Any]:
        snap = stats.snapshot()
        snap.update(
            {
                "service": SERVICE,
                "deps": {
                    "redis": _probe_redis(rds),
                    "payment": "up" if payment_state["up"] else "down",
                    "db": _probe_db(dsn),
                },
                "db_pool": _pool_stats(pool_state, config),
                "config_version": config.version,
            }
        )
        return snap

    return app


def _probe_redis(rds: redis.Redis) -> str:
    try:
        rds.ping()
        return "up"
    except Exception:
        return "down"


def _probe_db(dsn: str) -> str:
    try:
        with psycopg.connect(dsn, connect_timeout=1) as conn:
            conn.execute("SELECT 1")
        return "up"
    except Exception:
        return "down"


def _pool_stats(pool_state: dict[str, Any], config: HotConfig) -> dict[str, int]:
    size = int(config.get("db_pool_size", 10))
    pool = pool_state.get("pool")
    if pool is None:
        return {"in_use": 0, "size": size}
    stats = pool.get_stats()
    in_use = int(stats.get("pool_size", 0)) - int(stats.get("pool_available", 0))
    return {"in_use": max(in_use, 0), "size": size}
