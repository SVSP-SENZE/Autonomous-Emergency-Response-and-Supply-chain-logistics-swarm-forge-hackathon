"""API schemas for relief orders."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.enums import OrderStatus, Priority, SupplyType


class ReliefOrderItemRead(BaseModel):
    """One supply line of a relief order."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    supply_type: SupplyType
    quantity: int
    unit: str


class ReliefOrderRead(BaseModel):
    """Relief order with item lines and route metadata."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    order_code: str
    warehouse_id: int
    relief_centre_id: int
    vehicle_id: int | None = None
    status: OrderStatus
    priority: Priority
    estimated_travel_time_minutes: int
    route_metadata: dict[str, Any]
    items: list[ReliefOrderItemRead] = []
    is_demo: bool
    created_at: datetime
    updated_at: datetime


__all__ = ["ReliefOrderItemRead", "ReliefOrderRead"]
