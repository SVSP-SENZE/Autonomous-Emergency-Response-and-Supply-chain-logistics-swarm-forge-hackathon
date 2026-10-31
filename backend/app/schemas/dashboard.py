"""Schemas for dashboard KPI aggregates."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import SupplyType
from app.schemas.common import DataMode, DEFAULT_DATA_MODE


class DashboardKPIs(BaseModel):
    """Key figures calculated live from database records."""

    affected_population: int = Field(ge=0)
    active_disasters: int = Field(ge=0)
    relief_centres: int = Field(ge=0)
    critical_centres: int = Field(ge=0)
    warehouses: int = Field(ge=0)
    total_vehicles: int = Field(ge=0)
    available_vehicles: int = Field(ge=0)
    vehicles_in_transit: int = Field(ge=0)
    blocked_roads: int = Field(ge=0)


class InventoryAggregate(BaseModel):
    """Inventory totals grouped by supply type (across warehouses)."""

    supply_type: SupplyType
    unit: str
    quantity: int = Field(ge=0)
    reserved_quantity: int = Field(ge=0)
    available_quantity: int = Field(ge=0)


class DashboardResponse(BaseModel):
    """`GET /dashboard/summary` response."""

    data_mode: DataMode = DEFAULT_DATA_MODE
    summary: DashboardKPIs
    inventory: list[InventoryAggregate] = Field(default_factory=list)
    orders_by_status: dict[str, int] = Field(default_factory=dict)
    generated_at: datetime


__all__ = ["DashboardKPIs", "DashboardResponse", "InventoryAggregate"]
