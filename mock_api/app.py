"""FastAPI app serving the synthetic property data as Qube, FixFlo and Engage APIs."""

from __future__ import annotations

import logging
import random
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from mock_api.config import Settings
from mock_api.data import DataStore
from mock_api.routers import engage, fixflo, mri_services, qube

log = logging.getLogger("mock_api")

# Paths that are never rate limited.
_OPEN_PATHS = ("/health", "/docs", "/openapi.json", "/redoc")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    store = DataStore(settings.data_dir)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if settings.preload:
            names = [n for n in store.table_names() if n != "dim_calendar"]
            log.info("preloading %d tables from %s", len(names), settings.data_dir)
            store.preload(names)
            log.info("mock API ready")
        yield

    app = FastAPI(
        title="Property Manager Insights mock source APIs",
        description="Local stand-in for MRI Qube PM, FixFlo v2 and MRI Engage CRM.",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.store = store
    rng = random.Random(settings.chaos_seed)

    @app.middleware("http")
    async def rate_limit(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Randomly reject requests with 429 + Retry-After when chaos is switched on.

        Runs before auth and routing, the way a vendor gateway throttles, so a client
        has to cope with it on any endpoint.
        """
        if (
            settings.chaos
            and not request.url.path.startswith(_OPEN_PATHS)
            and rng.random() < settings.chaos_rate
        ):
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests"},
                headers={"Retry-After": str(settings.retry_after_seconds)},
            )
        return await call_next(request)

    @app.get("/health", tags=["Mock"])
    def health() -> dict[str, object]:
        return {"status": "ok", "chaos": settings.chaos, "chaos_rate": settings.chaos_rate}

    app.include_router(qube.router)
    app.include_router(mri_services.router)
    app.include_router(fixflo.router)
    app.include_router(engage.router)
    return app
