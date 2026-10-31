"""Map overview endpoint (single request that powers the disaster map)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.map import MapOverviewResponse
from app.services.map_service import get_map_overview

router = APIRouter(prefix="/map", tags=["map"])


@router.get(
    "/overview",
    response_model=MapOverviewResponse,
    summary="Full disaster map payload (incidents, centres, warehouses, vehicles, road network)",
)
def map_overview(db: Session = Depends(get_db)) -> MapOverviewResponse:
    """Everything the frontend map needs, in one predictable response."""
    return get_map_overview(db)
