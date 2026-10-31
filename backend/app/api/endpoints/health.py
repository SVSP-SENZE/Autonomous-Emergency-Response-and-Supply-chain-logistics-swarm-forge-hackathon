"""Health check endpoint."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.config import settings
from app.core.database import get_db

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """`GET /health` response."""

    status: str
    database: str
    timestamp: datetime
    app_name: str
    version: str
    environment: str
    data_mode: Literal["SIMULATED"] = "SIMULATED"
    api_prefix: str = Field(default=settings.api_v1_prefix)


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Health check (application + database status)",
)
def health_check(db: Session = Depends(get_db)) -> HealthResponse:
    """Report application status and database connectivity."""
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        # Never leak DB connection details to clients; log at most.
        db_ok = False
    return HealthResponse(
        status="ok" if db_ok else "degraded",
        database="connected" if db_ok else "disconnected",
        timestamp=utcnow(),
        app_name=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
    )
