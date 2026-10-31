"""Schemas for simulation endpoints (reset + events)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import Severity, SimulationEventType
from app.schemas.common import DataMode, DEFAULT_DATA_MODE


class SimulationEventCreate(BaseModel):
    """Payload for `POST /simulation/events`.

    Which target ids are required depends on `event_type`:

    - `bridge_collapse`, `road_blocked`        -> `road_segment_id`
    - `warehouse_unavailable`                  -> `warehouse_id`
    - `relief_centre_water_shortage`           -> `relief_centre_id`
    - `new_flood_report`                       -> `relief_centre_id` OR location_name + coordinates
    - `rainfall_escalation`                    -> `incident_id` OR `relief_centre_id`
    - `vehicle_breakdown`                      -> `vehicle_id`
    """

    model_config = ConfigDict(extra="forbid", json_schema_extra=None)

    event_type: SimulationEventType
    title: str | None = Field(default=None, min_length=3, max_length=200)
    description: str | None = None
    severity: Severity | None = None
    location_name: str | None = Field(default=None, min_length=1, max_length=200)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    affected_population: int | None = Field(default=None, ge=0)
    blockage_reason: str | None = Field(default=None, min_length=3, max_length=500)

    # Target entity references (validated per event type by the service).
    road_segment_id: int | None = Field(default=None, ge=1)
    warehouse_id: int | None = Field(default=None, ge=1)
    relief_centre_id: int | None = Field(default=None, ge=1)
    vehicle_id: int | None = Field(default=None, ge=1)
    incident_id: int | None = Field(default=None, ge=1)

    # Free-form extras merged into the stored event's `event_data`.
    event_data: dict[str, Any] = Field(default_factory=dict)


class SimulationEventRead(BaseModel):
    """A persisted simulation event record."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    event_type: SimulationEventType
    title: str
    description: str
    location_name: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    affected_entity_type: str | None = None
    affected_entity_id: int | None = None
    severity: Severity
    event_data: dict[str, Any]
    is_demo: bool
    created_at: datetime


class SimulationEventResult(BaseModel):
    """`POST /simulation/events` response: what changed in the scenario."""

    data_mode: DataMode = DEFAULT_DATA_MODE
    message: str
    changes: list[str] = Field(default_factory=list)
    event: SimulationEventRead


class SimulationResetResponse(BaseModel):
    """`POST /simulation/reset` response."""

    data_mode: DataMode = DEFAULT_DATA_MODE
    message: str
    counts: dict[str, int] = Field(default_factory=dict)
    reset_at: datetime


__all__ = [
    "SimulationEventCreate",
    "SimulationEventRead",
    "SimulationEventResult",
    "SimulationResetResponse",
]
