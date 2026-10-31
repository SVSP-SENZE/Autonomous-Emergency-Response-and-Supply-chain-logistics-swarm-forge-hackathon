"""API schemas for warehouses and inventory."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import OperationalStatus, SupplyType


class InventoryItemRead(BaseModel):
    """One inventory row, including computed available quantity."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    supply_type: SupplyType
    quantity: int
    reserved_quantity: int
    available_quantity: int
    unit: str
    warehouse_id: int
    updated_at: datetime


class WarehouseSummary(BaseModel):
    """Compact warehouse marker/report."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    location_name: str
    latitude: float
    longitude: float
    operational_status: OperationalStatus
    storage_capacity: int


class WarehouseRead(WarehouseSummary):
    """Warehouse detail including inventory lines and available quantities."""


class WarehouseDetail(WarehouseRead):
    inventory: list[InventoryItemRead] = Field(default_factory=list)


__all__ = ["InventoryItemRead", "WarehouseRead", "WarehouseDetail", "WarehouseSummary"]
