"""API schemas for relief centres."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import OperationalStatus, Priority


class ReliefCentreSummary(BaseModel):
    """Compact relief centre marker/report."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    district: str
    latitude: float
    longitude: float
    affected_population: int
    priority: Priority
    operational_status: OperationalStatus
    water_shortage: bool


class ReliefCentreInventoryLine(BaseModel):
    """One supply-type stock row held at a relief centre."""

    model_config = ConfigDict(from_attributes=True)

    supply_type: str
    quantity: float
    unit: str
    updated_at: datetime


class ReliefCentreDetail(ReliefCentreSummary):
    """Relief centre detail: adds descriptive/location context + stock."""

    water_shortage_notes: str | None = None
    is_demo: bool
    created_at: datetime
    updated_at: datetime
    inventory: list[ReliefCentreInventoryLine] = Field(default_factory=list)


__all__ = ["ReliefCentreDetail", "ReliefCentreInventoryLine", "ReliefCentreSummary"]
