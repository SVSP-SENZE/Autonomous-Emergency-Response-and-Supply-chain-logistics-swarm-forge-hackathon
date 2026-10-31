"""Schemas for the frontend map overview endpoint."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import (
    IncidentStatus,
    IncidentType,
    NodeType,
    OperationalStatus,
    Priority,
    Severity,
    VehicleStatus,
    VehicleType,
)
from app.schemas.common import DataMode, DEFAULT_DATA_MODE


class MapIncident(BaseModel):
    """Active incident marker."""

    id: int
    incident_type: IncidentType
    title: str
    severity: Severity
    status: IncidentStatus
    location_name: str
    latitude: float
    longitude: float
    affected_population: int


class MapReliefCentre(BaseModel):
    """Relief centre marker."""

    id: int
    name: str
    district: str
    latitude: float
    longitude: float
    affected_population: int
    priority: Priority
    operational_status: OperationalStatus
    water_shortage: bool


class MapWarehouse(BaseModel):
    """Warehouse marker."""

    id: int
    name: str
    location_name: str
    latitude: float
    longitude: float
    operational_status: OperationalStatus


class MapVehicle(BaseModel):
    """Vehicle marker."""

    id: int
    vehicle_code: str
    vehicle_type: VehicleType
    status: VehicleStatus
    capacity: int
    current_latitude: float | None = None
    current_longitude: float | None = None
    current_location: str


class MapRoadNode(BaseModel):
    """Road network node marker."""

    id: int
    node_name: str
    node_type: NodeType
    latitude: float
    longitude: float
    linked_entity_id: int | None = None


class MapRoadSegment(BaseModel):
    """Road segment between two nodes."""

    id: int
    from_node_id: int
    to_node_id: int
    from_node_name: str
    to_node_name: str
    distance_km: float
    estimated_travel_time_minutes: int
    risk_factor: float
    is_blocked: bool
    blockage_reason: str | None = None


class MapCenter(BaseModel):
    """Suggested map viewport centre."""

    latitude: float
    longitude: float
    zoom: float = Field(default=9.0, ge=1, le=18)


class MapOverviewResponse(BaseModel):
    """`GET /map/overview` response: everything the disaster map needs."""

    data_mode: DataMode = DEFAULT_DATA_MODE
    generated_at: datetime
    center: MapCenter
    incidents: list[MapIncident] = Field(default_factory=list)
    relief_centres: list[MapReliefCentre] = Field(default_factory=list)
    warehouses: list[MapWarehouse] = Field(default_factory=list)
    vehicles: list[MapVehicle] = Field(default_factory=list)
    road_nodes: list[MapRoadNode] = Field(default_factory=list)
    road_segments: list[MapRoadSegment] = Field(default_factory=list)
    blocked_roads: list[MapRoadSegment] = Field(default_factory=list)


__all__ = ["MapOverviewResponse", "MapCenter"]
