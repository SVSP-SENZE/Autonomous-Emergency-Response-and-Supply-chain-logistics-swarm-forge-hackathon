"""Schemas for the frontend map overview endpoint."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models.enums import (
    IncidentSource,
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

LiveLayerState = Literal["ok", "stale", "unavailable"]


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
    # Provenance: lets the frontend hide seeded demo markers and style live ones.
    source: IncidentSource = IncidentSource.SIMULATION
    is_demo: bool = True
    updated_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


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
    is_demo: bool = True


class MapWarehouse(BaseModel):
    """Warehouse marker."""

    id: int
    name: str
    location_name: str
    latitude: float
    longitude: float
    operational_status: OperationalStatus
    is_demo: bool = True


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
    is_demo: bool = True


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


class MapLiveLayerStatus(BaseModel):
    """Per-source freshness for one live layer (sourced from live_data_service)."""

    source: str
    status: LiveLayerState
    last_updated: datetime | None = None
    detail: str | None = None


class MapWeatherStation(BaseModel):
    """Open-Meteo current-conditions marker for one monitored delta station."""

    name: str
    district: str
    latitude: float
    longitude: float
    temperature_c: float | None = None
    precipitation_mm: float | None = None
    daily_precipitation_mm: float | None = None
    wind_speed_kmh: float | None = None
    wind_gusts_kmh: float | None = None
    weather_code: int | None = None
    river: str | None = None
    severity: Severity | None = None
    assessment: str | None = None
    updated_at: datetime | None = None
    source: str = "Open-Meteo"


class MapRiverGauge(BaseModel):
    """Open-Meteo Flood API river discharge at a monitored gauge location."""

    name: str
    river: str | None = None
    latitude: float
    longitude: float
    river_discharge_m3s: float | None = None
    daily_precipitation_mm: float | None = None
    severity: Severity | None = None
    assessment: str | None = None
    updated_at: datetime | None = None
    source: str = "Open-Meteo Flood API"


class MapDisasterEvent(BaseModel):
    """External disaster event/alert (NASA EONET or GDACS)."""

    external_id: str | None = None
    title: str
    category: str | None = None
    alert_level: str | None = None
    severity: Severity | None = None
    severity_text: str | None = None
    latitude: float
    longitude: float
    source: str  # "NASA EONET" | "GDACS"
    link: str | None = None
    occurred_at: datetime | None = None
    updated_at: datetime | None = None


class MapFacility(BaseModel):
    """Genuine hospital / medical facility from OSM Nominatim."""

    name: str
    display_name: str | None = None
    town: str | None = None
    latitude: float
    longitude: float
    osm_id: str | None = None
    osm_type: str | None = None
    category: str = "hospital"
    source: str = "OSM Nominatim"
    updated_at: datetime | None = None


class MapLiveLayers(BaseModel):
    """Live external-data overlay layers for the disaster map.

    Empty lists + "unavailable" statuses are the graceful degradation when an
    external API is down or has never synced — the frontend renders an
    explicit unavailable note instead of falling back to demo markers.
    """

    weather_stations: list[MapWeatherStation] = Field(default_factory=list)
    river_gauges: list[MapRiverGauge] = Field(default_factory=list)
    disaster_events: list[MapDisasterEvent] = Field(default_factory=list)
    facilities: list[MapFacility] = Field(default_factory=list)
    statuses: list[MapLiveLayerStatus] = Field(default_factory=list)


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
    live_layers: MapLiveLayers = Field(default_factory=MapLiveLayers)


__all__ = [
    "MapOverviewResponse",
    "MapCenter",
    "MapLiveLayers",
    "MapWeatherStation",
    "MapRiverGauge",
    "MapDisasterEvent",
    "MapFacility",
]
