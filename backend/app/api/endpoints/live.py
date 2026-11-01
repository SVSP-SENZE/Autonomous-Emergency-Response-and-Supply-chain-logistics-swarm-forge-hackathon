"""Live data feed API endpoints for Tamil Nadu disaster response."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.live_data_service import get_live_status, sync_live_disaster_data

router = APIRouter(prefix="/live", tags=["live-data"])


class LiveStatusResponse(BaseModel):
    status: str
    last_sync_utc: str | None
    region: str = "Tamil Nadu - Cauvery Delta"
    stations_monitored: int
    nasa_eonet_events: list[dict[str, Any]]
    station_readings: list[dict[str, Any]]
    incidents_synced: int
    roads_updated: int
    data_mode: str = "LIVE"
    # GDACS alerts + OSM Nominatim hospital facilities (cached server-side).
    gdacs_alerts: list[dict[str, Any]] = []
    gdacs_fetched_at: str | None = None
    gdacs_status: str = "unavailable"
    hospitals: list[dict[str, Any]] = []
    hospitals_fetched_at: str | None = None
    hospitals_status: str = "unavailable"


def _to_response(cached: dict[str, Any]) -> LiveStatusResponse:
    stations = cached.get("stations", [])
    gdacs = cached.get("gdacs") or {}
    hospitals = cached.get("hospitals") or {}
    return LiveStatusResponse(
        status=cached.get("status", "active"),
        last_sync_utc=cached.get("last_sync_utc"),
        stations_monitored=len(stations),
        nasa_eonet_events=cached.get("nasa_events", []),
        station_readings=stations,
        incidents_synced=cached.get("incidents_synced", 0),
        roads_updated=cached.get("roads_updated", 0),
        gdacs_alerts=gdacs.get("alerts", []),
        gdacs_fetched_at=gdacs.get("fetched_at"),
        gdacs_status=gdacs.get("status", "unavailable"),
        hospitals=hospitals.get("items", []),
        hospitals_fetched_at=hospitals.get("fetched_at"),
        hospitals_status=hospitals.get("status", "unavailable"),
    )


@router.get(
    "/status",
    response_model=LiveStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Get status of live data feeds for Tamil Nadu",
)
def get_live_feed_status(db: Session = Depends(get_db)) -> LiveStatusResponse:
    """Return the cached live weather, flood discharge, NASA storm, GDACS alerts and hospital data."""
    cached = get_live_status()
    if cached.get("last_sync_utc") is None:
        cached = sync_live_disaster_data(db)
    return _to_response(cached)


@router.post(
    "/sync",
    response_model=LiveStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Force refresh live weather, flood, and disaster feeds",
)
def trigger_live_sync(db: Session = Depends(get_db)) -> LiveStatusResponse:
    """Fetch fresh data from Open-Meteo, Open-Meteo Flood, NASA EONET, GDACS and Nominatim."""
    res = sync_live_disaster_data(db)
    return _to_response(res)
