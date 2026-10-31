"""API schemas for vehicles."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import VehicleStatus, VehicleType


class VehicleSummary(BaseModel):
    """Compact vehicle marker/report."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    vehicle_code: str
    vehicle_type: VehicleType
    capacity: int
    status: VehicleStatus
    current_latitude: float | None = None
    current_longitude: float | None = None
    current_location: str


class VehicleDetail(VehicleSummary):
    """Vehicle detail including optional warehouse attachment."""

    warehouse_id: int | None = None
    is_demo: bool
    created_at: datetime
    updated_at: datetime


__all__ = ["VehicleDetail", "VehicleSummary"]
