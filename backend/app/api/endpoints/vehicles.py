"""Vehicle endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.models import Vehicle
from app.models.enums import VehicleStatus, VehicleType
from app.schemas.common import ListResponse
from app.schemas.vehicle import VehicleDetail, VehicleSummary

router = APIRouter(prefix="/vehicles", tags=["vehicles"])


@router.get(
    "",
    response_model=ListResponse[VehicleSummary],
    summary="List vehicles with optional filters",
)
def list_vehicle_items(
    vehicle_status: VehicleStatus | None = Query(default=None, alias="status"),
    vehicle_type: VehicleType | None = Query(default=None, alias="type"),
    db: Session = Depends(get_db),
) -> ListResponse[VehicleSummary]:
    """List vehicles, optionally filtered by status / type."""
    stmt = select(Vehicle)
    if vehicle_status is not None:
        stmt = stmt.where(Vehicle.status == vehicle_status)
    if vehicle_type is not None:
        stmt = stmt.where(Vehicle.vehicle_type == vehicle_type)
    vehicles = db.scalars(stmt.order_by(Vehicle.id)).all()
    items = [VehicleSummary.model_validate(vehicle) for vehicle in vehicles]
    return ListResponse(items=items, total=len(items))


@router.get(
    "/{vehicle_id}",
    response_model=VehicleDetail,
    summary="Get one vehicle",
)
def get_vehicle_item(vehicle_id: int, db: Session = Depends(get_db)) -> VehicleDetail:
    """Fetch a single vehicle."""
    vehicle = db.get(Vehicle, vehicle_id)
    if vehicle is None:
        raise NotFoundError(f"Vehicle {vehicle_id} not found")
    return VehicleDetail.model_validate(vehicle)
