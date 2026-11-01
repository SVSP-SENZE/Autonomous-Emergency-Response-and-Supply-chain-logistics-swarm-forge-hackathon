"""ReliefMesh FastAPI application entrypoint.

Run with: `uvicorn app.main:app --reload` (from the `backend` directory).
Swagger UI is served at http://localhost:8000/docs
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers


def _run_live_sync() -> None:
    """One live-data refresh cycle (Open-Meteo, EONET, GDACS, Nominatim → DB)."""
    from app.core.database import SessionLocal
    from app.services.live_data_service import sync_live_disaster_data

    with SessionLocal() as db:
        sync_live_disaster_data(db)


async def _live_refresh_loop() -> None:
    """Background refresher so the map keeps receiving fresh external data.

    Runs in a worker thread (httpx sync client + SQLite session); failures are
    logged and retried on the next tick — the map layers degrade to
    stale/unavailable meanwhile instead of showing demo data.
    """
    from app.services.live_data_service import LIVE_REFRESH_INTERVAL_SECONDS

    logger = logging.getLogger("reliefmesh.live")
    while True:
        await asyncio.sleep(LIVE_REFRESH_INTERVAL_SECONDS)
        try:
            await asyncio.to_thread(_run_live_sync)
            logger.info("Periodic live data refresh complete.")
        except Exception as e:
            logger.warning("Periodic live data refresh failed (continuing): %s", e)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Startup/teardown hooks: init DB, optionally seed the demo scenario."""
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    logger = logging.getLogger("reliefmesh")
    logger.info("Starting %s v%s (%s)", settings.app_name, settings.app_version, settings.environment)
    refresh_task: asyncio.Task | None = None
    if settings.auto_init_db:
        from app.core.database import SessionLocal, init_db

        init_db()
        if settings.auto_seed:
            from app.services.seed_service import seed_demo

            with SessionLocal() as db:
                counts = seed_demo(db)
                logger.info(
                    "Demo scenario ready (SIMULATED data): %s", counts
                )
        if getattr(settings, "enable_live_data", True):
            from app.services.live_data_service import sync_live_disaster_data

            try:
                with SessionLocal() as db:
                    live_res = sync_live_disaster_data(db)
                    logger.info(
                        "Live disaster data synced for Tamil Nadu: %d stations, %d incidents",
                        len(live_res.get("stations", [])),
                        live_res.get("incidents_synced", 0),
                    )
            except Exception as e:
                logger.warning("Initial live disaster data sync failed (continuing): %s", e)
            # Keep the live layers fresh (Open-Meteo / EONET / GDACS / Nominatim).
            refresh_task = asyncio.create_task(_live_refresh_loop())
    yield
    if refresh_task is not None:
        refresh_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await refresh_task
    logger.info("Shutting down %s", settings.app_name)


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "ReliefMesh — autonomous disaster response & logistics platform "
        "(Forge hackathon backend). **All demo data is SIMULATED.**"
    ),
    lifespan=lifespan,
)

# CORS for local frontend development (Vite/React defaults) and hosted demos.
cors_origins = settings.cors_origin_list
allow_credentials = not (len(cors_origins) == 1 and cors_origins[0] == "*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)

app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.get("/", include_in_schema=False)
def root() -> JSONResponse:
    """Redirect root to the Swagger docs."""
    return JSONResponse(
        {
            "app": settings.app_name,
            "version": settings.app_version,
            "data_mode": "SIMULATED",
            "api_prefix": settings.api_v1_prefix,
            "docs": "/docs",
            "health": f"{settings.api_v1_prefix}/health",
        }
    )
