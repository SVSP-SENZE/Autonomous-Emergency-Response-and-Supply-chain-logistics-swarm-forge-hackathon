"""Phase-2 schemas: demand estimation, allocation planning and routing."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.planning_config import ALLOWED_HORIZONS, DEFAULT_HORIZON
from app.models.enums import OperationalStatus, PlanningStatus, PlanningType, Priority, SupplyType
from app.schemas.common import DataMode, DEFAULT_DATA_MODE, ListResponse

EntityRouteType = Literal["warehouse", "relief_centre", "junction"]


# --------------------------------------------------------------------------- #
# Demand estimation
# --------------------------------------------------------------------------- #


class DemandAssumptions(BaseModel):
    """Documented assumptions used by the demand engine (demo values)."""

    planning_horizon_hours: int
    consumption_rates_per_person_per_day: dict[str, float]
    priority_component_weight: float
    shortage_component_weight: float
    population_component_weight: float
    supply_risk_component_weight: float
    note: str = (
        "Illustrative demonstration assumptions for the SIMULATED Thanjavur "
        "scenario; not official emergency standards."
    )


class DemandItem(BaseModel):
    """Per-supply-type demand breakdown for one relief centre."""

    supply_type: SupplyType
    unit: str
    required_quantity: float = Field(ge=0)
    current_stock: float = Field(ge=0)
    shortage_quantity: float = Field(ge=0)
    surplus_quantity: float = Field(ge=0)
    shortage_percentage: float = Field(ge=0, le=100)


class DemandCentreRead(BaseModel):
    """Demand assessment for one relief centre."""

    relief_centre_id: int
    name: str
    district: str
    latitude: float
    longitude: float
    affected_population: int
    centre_priority: Priority
    operational_status: OperationalStatus
    allocation_eligible: bool
    priority_score: float = Field(ge=0, le=100)
    priority_classification: str
    items: list[DemandItem]
    max_shortage_percentage: float = Field(ge=0, le=100)


class DemandSummary(BaseModel):
    """Aggregated demand across all assessed centres."""

    centres_assessed: int
    centres_eligible: int
    total_required_by_supply: dict[str, float]
    total_shortage_by_supply: dict[str, float]
    total_stock_at_centres_by_supply: dict[str, float]


class DemandAssessmentResponse(BaseModel):
    """`GET /planning/demand` and `POST /planning/demand/estimate` response."""

    data_mode: DataMode = DEFAULT_DATA_MODE
    generated_at: datetime
    planning_run_id: int | None = None
    horizon_hours: int
    assumptions: DemandAssumptions
    summary: DemandSummary
    centres: list[DemandCentreRead]


# --------------------------------------------------------------------------- #
# Routing
# --------------------------------------------------------------------------- #


class RouteSegmentRead(BaseModel):
    """One traversed road segment on a route."""

    segment_id: int
    from_node_id: int
    to_node_id: int
    from_node_name: str
    to_node_name: str
    distance_km: float
    estimated_travel_time_minutes: int
    risk_factor: float


class RouteRead(BaseModel):
    """Optimal route between two road nodes."""

    reachable: bool
    origin: str
    destination: str
    origin_node_id: int
    destination_node_id: int
    route_nodes: list[int] = Field(default_factory=list)
    route_node_names: list[str] = Field(default_factory=list)
    segments: list[RouteSegmentRead] = Field(default_factory=list)
    distance_km: float = 0.0
    estimated_travel_time_minutes: int = 0
    route_risk: float = 0.0
    blocked_segments_avoided: int = 0
    message: str = "Route computed successfully."
    # Real-network routing (OSMnx) additions. `status_code` is an explicit
    # machine-readable outcome; `NO_ROUTE_AVAILABLE` is returned when no
    # drivable road path exists for the EXACT requested destination.
    status_code: Literal["ROUTE_FOUND", "NO_ROUTE_AVAILABLE"] = "ROUTE_FOUND"
    # Full road geometry: [longitude, latitude] pairs along actual mapped roads.
    geometry_coords: list[list[float]] = Field(default_factory=list)
    geojson_linestring: dict[str, Any] | None = None
    # Ordered real road names along the route.
    road_names: list[str] = Field(default_factory=list)
    # Which network produced the route: `osm_real` or `simulated_graph`.
    network: str = "simulated_graph"


class RouteComputeRequest(BaseModel):
    """`POST /planning/routes/compute` request."""

    model_config = ConfigDict(extra="forbid")

    origin_node_id: int = Field(ge=1)
    destination_node_id: int = Field(ge=1)


class RouteBetweenEntitiesRequest(BaseModel):
    """`POST /planning/routes/between-entities` request."""

    model_config = ConfigDict(extra="forbid")

    origin_type: EntityRouteType
    origin_id: int = Field(ge=1)
    destination_type: EntityRouteType
    destination_id: int = Field(ge=1)


def _validate_horizon(value: int) -> int:
    if value not in ALLOWED_HORIZONS:
        raise ValueError(f"horizon_hours must be one of {ALLOWED_HORIZONS}")
    return value


class RecalculateRouteRequest(BaseModel):
    """`POST /planning/routes/recalculate` request."""

    model_config = ConfigDict(extra="forbid")

    origin_node_id: int = Field(ge=1)
    destination_node_id: int = Field(ge=1)


class RouteComparisonResponse(BaseModel):
    """Route before vs. after a disruption (`POST /planning/routes/recalculate`)."""

    data_mode: DataMode = DEFAULT_DATA_MODE
    generated_at: datetime
    planning_run_id: int | None = None
    historical_route_available: bool
    current_route: RouteRead
    previous_route: RouteRead | None = None
    delay_minutes: int | None = None
    distance_delta_km: float | None = None
    blocked_segments: list[RouteSegmentRead] = Field(default_factory=list)
    alternative_route_available: bool
    explanation: str


# --------------------------------------------------------------------------- #
# Allocation planning
# --------------------------------------------------------------------------- #


class AllocationSourceRead(BaseModel):
    """One warehouse contribution on one allocation line."""

    warehouse_id: int
    warehouse_name: str
    quantity: float = Field(ge=0)
    route_distance_km: float
    route_travel_time_minutes: int
    route_risk: float
    route_cost: float


class AllocationComputeRequest(BaseModel):
    """`POST /planning/allocation/compute` request."""

    model_config = ConfigDict(extra="forbid")

    horizon_hours: int = DEFAULT_HORIZON

    @model_validator(mode="after")
    def _check_horizon(self) -> "AllocationComputeRequest":
        _validate_horizon(self.horizon_hours)
        return self


class AllocationLineRead(BaseModel):
    """Allocation outcome for one (centre, supply type) pair."""

    supply_type: SupplyType
    required_quantity: float = Field(ge=0)
    current_stock: float = Field(ge=0)
    shortage_quantity: float = Field(ge=0)
    allocated_quantity: float = Field(ge=0)
    unfulfilled_quantity: float = Field(ge=0)
    fulfilment_percentage: float = Field(ge=0, le=100)
    sources: list[AllocationSourceRead] = Field(default_factory=list)


class AllocationCentreRead(BaseModel):
    """Per-centre allocation plan (all supply types)."""

    relief_centre_id: int
    name: str
    district: str
    affected_population: int
    centre_priority: Priority
    priority_score: float
    operational_status: OperationalStatus
    lines: list[AllocationLineRead]


class ExcludedCentreRead(BaseModel):
    """A centre deliberately excluded from allocation, with the reason."""

    relief_centre_id: int
    name: str
    operational_status: OperationalStatus
    reason: str


class WarehouseUtilisationRead(BaseModel):
    """How much of each warehouse's stock the plan consumed."""

    warehouse_id: int
    warehouse_name: str
    initial_available_by_supply: dict[str, float]
    allocated_by_supply: dict[str, float]
    remaining_by_supply: dict[str, float]


class AllocationSummary(BaseModel):
    """Whole-plan statistics computed from the real ledger."""

    required_by_supply: dict[str, float]
    allocated_by_supply: dict[str, float]
    unfulfilled_by_supply: dict[str, float]
    fulfilment_percentage: float
    centres_planned: int
    centres_served: int
    centres_with_unmet_demand: int
    warehouse_utilisation: list[WarehouseUtilisationRead]
    remaining_by_supply: dict[str, float]


class AllocationPlanResponse(BaseModel):
    """`POST /planning/allocation/compute` and `GET /planning/allocation/latest`."""

    data_mode: DataMode = DEFAULT_DATA_MODE
    generated_at: datetime
    planning_run_id: int | None = None
    horizon_hours: int
    assumptions: DemandAssumptions
    summary: AllocationSummary
    centres: list[AllocationCentreRead]
    excluded_centres: list[ExcludedCentreRead] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Planning run history (Phase 5: audit page / plan history)
# ---------------------------------------------------------------------------


class PlanningRunSummaryRead(BaseModel):
    """Compact `PlanningRun` row for history listings."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    planning_type: PlanningType
    status: PlanningStatus
    planning_horizon_hours: int | None = None
    created_at: datetime


class PlanningRunDetailRead(PlanningRunSummaryRead):
    """Full planning run incl. the persisted computation snapshot."""

    summary: dict[str, Any] = Field(default_factory=dict)
    snapshot: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "AllocationCentreRead",
    "AllocationComputeRequest",
    "AllocationLineRead",
    "AllocationPlanResponse",
    "AllocationSourceRead",
    "AllocationSummary",
    "AllocationCentreRead",
    "DemandAssessmentResponse",
    "DemandAssumptions",
    "DemandCentreRead",
    "DemandItem",
    "DemandSummary",
    "ExcludedCentreRead",
    "PlanningRunDetailRead",
    "PlanningRunSummaryRead",
    "RecalculateRouteRequest",
    "RouteBetweenEntitiesRequest",
    "RouteComparisonResponse",
    "RouteComputeRequest",
    "RouteRead",
    "RouteSegmentRead",
    "WarehouseUtilisationRead",
]
