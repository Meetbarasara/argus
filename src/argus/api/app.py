"""FastAPI application factory. Run via ``uvicorn argus.api.app:create_app --factory``
(the container runs ``alembic upgrade head`` first — see docker-compose)."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from argus.api.routers import alerts, approvals, health, incidents, stubs
from argus.errors import ArgusError, PolicyError
from argus.settings import get_settings


def create_app() -> FastAPI:
    app = FastAPI(title="Argus API", version="0.1.0")

    if get_settings().dev_mode:  # permissive CORS only for the Vite dev server (08 #25)
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )

    for r in (health.router, alerts.router, incidents.router, approvals.router, stubs.router):
        app.include_router(r, prefix="/api")

    @app.exception_handler(PolicyError)
    async def _policy_handler(_: Request, exc: PolicyError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(ArgusError)
    async def _argus_handler(_: Request, exc: ArgusError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    return app
