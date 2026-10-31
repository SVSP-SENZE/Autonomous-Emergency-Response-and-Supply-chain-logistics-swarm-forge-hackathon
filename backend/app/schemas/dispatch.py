"""Phase-4 dispatch API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import InventoryMovementType, OrderStatus, Priority, SupplyType, VehicleStatus, VehicleType

SIMULATED = "SIMULATED"


class DispatchOrderItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    supply_type: SupplyType
    quantity: float
    unit: str
    estimated_weight_kg: float


class DispatchVehicleBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    vehicle_code: str
    vehicle_type: VehicleType
    capacity: int
    capacity_kg: int | None = None
    status: VehicleStatus
    current_location: str
    current_latitude: float | None = None
    current_longitude: float | None = None


class DispatchOrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_code: str
    status: OrderStatus
    priority: Priority
    warehouse_id: int
    relief_centre_id: int
    vehicle_id: int | None = None
    planning_run_id: int | None = None
    total_cargo_weight_kg: float
    estimated_travel_time_minutes: int
    actual_travel_time_minutes: int | None = None
    route_progress_minutes: float = 0.0
    progress_percent: float = 0.0
    approved_at: datetime | None = None
    dispatched_at: datetime | None = None
    delivered_at: datetime | None = None
    items: list[DispatchOrderItemRead] = []
    is_demo: bool = True
    created_at: datetime
    updated_at: datetime


class DispatchOrderDetail(BaseModel):
    """Complete order view incl. route, vehicle and lifecycle events."""

    data_mode: Literal["SIMULATED"] = SIMULATED
    order: DispatchOrderRead
    warehouse_name: str
    relief_centre_name: str
    vehicle: DispatchVehicleBrief | None = None
    route: dict[str, Any] = Field(default_factory=dict)
    events: list["DispatchEventRead"] = Field(default_factory=list)
    inventory_movements: list["DispatchMovementRead"] = Field(default_factory=list)


class DispatchEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    relief_order_id: int
    event_type: str
    previous_status: str | None = None
    new_status: str | None = None
    description: str | None = None
    event_metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class DispatchMovementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    relief_order_id: int
    supply_type: SupplyType
    quantity: float
    movement_type: InventoryMovementType
    created_at: datetime


# --------------------------------------------------------------------------- #
# Generation (Phase C)
# --------------------------------------------------------------------------- #


class GeneratedOrderBrief(BaseModel):
    order_id: int
    order_code: str
    warehouse_id: int
    warehouse_name: str
    relief_centre_id: int
    relief_centre_name: str
    items: dict[str, float]
    cargo_weight_kg: float
    route_reachable: bool = True
    estimated_travel_time_minutes: int


class SkippedShipment(BaseModel):
    warehouse_id: int
    warehouse_name: str
    relief_centre_id: int
    relief_centre_name: str
    reason: str


class GenerateOrdersResponse(BaseModel):
    data_mode: Literal["SIMULATED"] = SIMULATED
    planning_run_id: int
    generated: list[GeneratedOrderBrief] = Field(default_factory=list)
    existing: list[GeneratedOrderBrief] = Field(default_factory=list)
    skipped: list[SkippedShipment] = Field(default_factory=list)
    message: str


# --------------------------------------------------------------------------- #
# Vehicle assignment (Phase D)
# --------------------------------------------------------------------------- #


class AssignVehicleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vehicle_id: int | None = None


class AssignmentCandidate(BaseModel):
    vehicle_id: int
    vehicle_code: str
    vehicle_type: VehicleType
    capacity_kg: int
    cargo_weight_kg: float


class AssignVehicleResponse(BaseModel):
    data_mode: Literal["SIMULATED"] = SIMULATED
    order_id: int
    order_code: str
    assigned: bool
    auto_selected: bool = False
    vehicle: DispatchVehicleBrief | None = None
    previous_vehicle_id: int | None = None
    cargo_weight_kg: float
    reason: str | None = None
    candidates_considered: list[AssignmentCandidate] = Field(default_factory=list)


class FleetVehicleOverview(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    vehicle_code: str
    vehicle_type: VehicleType
    capacity: int
    capacity_kg: int | None = None
    status: VehicleStatus
    current_location: str
    active_order_code: str | None = None
    active_order_id: int | None = None


class FleetOverviewResponse(BaseModel):
    data_mode: Literal["SIMULATED"] = SIMULATED
    total_vehicles: int
    available: int
    assigned: int
    in_transit: int
    under_maintenance: int
    delayed: int
    total_capacity_kg_available: float
    vehicles: list[FleetVehicleOverview]


# --------------------------------------------------------------------------- #
# Tracking (Phase G)
# --------------------------------------------------------------------------- #


class TrackingSegmentRead(BaseModel):
    segment_id: int
    from_node_name: str
    to_node_name: str
    distance_km: float
    estimated_travel_time_minutes: int
    risk_factor: float
    traversed: bool


class TrackingResponse(BaseModel):
    data_mode: Literal["SIMULATED"] = SIMULATED
    order_id: int
    order_code: str
    status: OrderStatus
    vehicle_code: str | None
    origin: str
    destination: str
    total_distance_km: float
    estimated_travel_time_minutes: int
    progress_minutes: float
    progress_percent: float
    progress_km: float
    current_latitude: float | None
    current_longitude: float | None
    current_node_name: str | None
    remaining_travel_time_minutes: int
    delayed: bool
    last_updated_at: datetime
    segments: list[TrackingSegmentRead]


class AdvanceOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Minutes of simulated travel for this advance; defaults to the configured
    #: step. Always clamped so the vehicle cannot pass its destination.
    minutes: float | None = Field(default=None, gt=0)


class RouteConfirmationResponse(BaseModel):
    data_mode: Literal["SIMULATED"] = SIMULATED
    order_id: int
    order_code: str
    status: OrderStatus
    route_updated: bool
    route: dict[str, Any] = Field(default_factory=dict)
    message: str


# --------------------------------------------------------------------------- #
# Dashboard (Phase H)
# --------------------------------------------------------------------------- #


class DispatchSummaryResponse(BaseModel):
    data_mode: Literal["SIMULATED"] = SIMULATED
    total_orders: int
    awaiting_approval: int
    approved: int
    dispatched: int
    in_transit: int
    delayed: int
    delivered: int
    cancelled: int
    total_cargo_weight_dispatched_kg: float
    successful_deliveries: int
    delivery_completion_percent: float
    vehicles_assigned: int
    vehicles_available: int
    total_inventory_reserved: float


class DispatchEventListResponse(BaseModel):
    data_mode: Literal["SIMULATED"] = SIMULATED
    total: int
    events: list[DispatchEventRead]


class DispatchOrderListResponse(BaseModel):
    data_mode: Literal["SIMULATED"] = SIMULATED
    total: int
    orders: list[DispatchOrderRead]


DispatchOrderDetail.model_rebuild()
