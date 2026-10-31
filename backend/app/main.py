"""ReliefMesh FastAPI application entrypoint.

Run with: `uvicorn app.main:app --reload` (from the `backend` directory).
Swagger UI is served at http://localhost:8000/docs
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Startup/teardown hooks: init DB, optionally seed the demo scenario."""
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    logger = logging.getLogger("reliefmesh")
    logger.info("Starting %s v%s (%s)", settings.app_name, settings.app_version, settings.environment)
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
            try:
                from app.services.live_data_service import sync_live_disaster_data

                with SessionLocal() as db:
                    live_res = sync_live_disaster_data(db)
                    logger.info(
                        "Live disaster data synced for Tamil Nadu: %d stations, %d incidents",
                        len(live_res.get("stations", [])),
                        live_res.get("incidents_synced", 0),
                    )
            except Exception as e:
                logger.warning("Initial live disaster data sync failed (continuing): %s", e)
    yield
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

# CORS for local frontend development (Vite/React defaults).
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
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
