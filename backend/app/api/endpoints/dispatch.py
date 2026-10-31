"""Phase-4 dispatch & fleet execution endpoints.

Every state transition is validated server-side against the database — never
trust any client-supplied inventory quantity, status or progress value.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.enums import OrderStatus, Priority
from app.schemas.dispatch import (
    AdvanceOrderRequest,
    AssignVehicleRequest,
    AssignVehicleResponse,
    DispatchEventListResponse,
    DispatchOrderDetail,
    DispatchOrderListResponse,
    DispatchSummaryResponse,
    FleetOverviewResponse,
    GenerateOrdersResponse,
    RouteConfirmationResponse,
    TrackingResponse,
)
from app.services import dispatch_service, fleet_service

router = APIRouter(prefix="/dispatch", tags=["dispatch"])


# --------------------------------------------------------------------------- #
# Generation (Feature A)
# --------------------------------------------------------------------------- #


@router.post(
    "/planning-runs/{planning_run_id}/generate",
    response_model=GenerateOrdersResponse,
    status_code=201,
    summary="Generate draft dispatch orders from a persisted allocation plan",
)
def generate_orders_endpoint(
    planning_run_id: int,
    regenerate: bool = Query(
        default=False,
        description="Replace untouched draft/awaiting orders (refused once any "
        "order of the run has been approved/dispatched).",
    ),
    db: Session = Depends(get_db),
) -> GenerateOrdersResponse:
    """Idempotent: repeats return the existing orders without duplicating."""
    return dispatch_service.generate_orders_from_plan(
        db, planning_run_id, regenerate=regenerate
    )


# --------------------------------------------------------------------------- #
# Dashboard / fleet (Features B + H)
# --------------------------------------------------------------------------- #


@router.get(
    "/fleet/overview",
    response_model=FleetOverviewResponse,
    summary="Fleet state: counts, capacities and active orders",
)
def fleet_overview_endpoint(db: Session = Depends(get_db)) -> FleetOverviewResponse:
    return fleet_service.fleet_overview(db)


@router.get(
    "/summary",
    response_model=DispatchSummaryResponse,
    summary="Dispatch dashboard metrics (all database-derived)",
)
def dispatch_summary_endpoint(db: Session = Depends(get_db)) -> DispatchSummaryResponse:
    return dispatch_service.dispatch_summary(db)


@router.get(
    "/events",
    response_model=DispatchEventListResponse,
    summary="Recent dispatch lifecycle events (append-only history)",
)
def dispatch_events_endpoint(
    order_id: int | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> DispatchEventListResponse:
    return dispatch_service.list_events(db, order_id=order_id, limit=limit)


# --------------------------------------------------------------------------- #
# Order listing / detail
# --------------------------------------------------------------------------- #


@router.get(
    "/orders",
    response_model=DispatchOrderListResponse,
    summary="List dispatch orders with optional filters",
)
def list_orders_endpoint(
    status: OrderStatus | None = Query(default=None),
    priority: Priority | None = Query(default=None),
    warehouse_id: int | None = Query(default=None, ge=1),
    relief_centre_id: int | None = Query(default=None, ge=1),
    vehicle_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> DispatchOrderListResponse:
    return dispatch_service.list_orders(
        db,
        status=status,
        priority=priority,
        warehouse_id=warehouse_id,
        relief_centre_id=relief_centre_id,
        vehicle_id=vehicle_id,
        limit=limit,
    )


@router.get(
    "/orders/{order_id}",
    response_model=DispatchOrderDetail,
    summary="Complete dispatch order detail: cargo, vehicle, route, events, movements",
)
def get_order_endpoint(order_id: int, db: Session = Depends(get_db)) -> DispatchOrderDetail:
    return dispatch_service.get_order_detail(db, order_id)


# --------------------------------------------------------------------------- #
# Lifecycle transitions
# --------------------------------------------------------------------------- #


@router.post(
    "/orders/{order_id}/assign-vehicle",
    response_model=AssignVehicleResponse,
    summary="Assign a vehicle (manual id, or auto-select when id omitted)",
)
def assign_vehicle_endpoint(
    order_id: int,
    request: AssignVehicleRequest | None = None,
    db: Session = Depends(get_db),
) -> AssignVehicleResponse:
    vehicle_id = request.vehicle_id if request is not None else None
    return fleet_service.assign_vehicle(db, order_id, vehicle_id)


@router.post(
    "/orders/{order_id}/approve",
    response_model=DispatchOrderDetail,
    summary="Operator approval: atomically reserve inventory (all-or-nothing)",
)
def approve_order_endpoint(order_id: int, db: Session = Depends(get_db)) -> DispatchOrderDetail:
    return dispatch_service.approve_order(db, order_id)


@router.post(
    "/orders/{order_id}/dispatch",
    response_model=DispatchOrderDetail,
    summary="Operator dispatch: deduct reserved stock exactly once, vehicle departs",
)
def dispatch_order_endpoint(order_id: int, db: Session = Depends(get_db)) -> DispatchOrderDetail:
    return dispatch_service.dispatch_order(db, order_id)


@router.post(
    "/orders/{order_id}/advance",
    response_model=TrackingResponse,
    summary="Simulate vehicle movement along the stored route (deterministic)",
)
def advance_order_endpoint(
    order_id: int,
    request: AdvanceOrderRequest | None = None,
    db: Session = Depends(get_db),
) -> TrackingResponse:
    minutes = request.minutes if request is not None else None
    return dispatch_service.advance_order(db, order_id, minutes)


@router.get(
    "/orders/{order_id}/tracking",
    response_model=TrackingResponse,
    summary="Simulated tracking state (progress, position, remaining ETA)",
)
def tracking_endpoint(order_id: int, db: Session = Depends(get_db)) -> TrackingResponse:
    return dispatch_service.get_order_tracking(db, order_id)


@router.post(
    "/orders/{order_id}/deliver",
    response_model=DispatchOrderDetail,
    summary="Complete delivery: add stock to the relief centre, release vehicle",
)
def deliver_order_endpoint(order_id: int, db: Session = Depends(get_db)) -> DispatchOrderDetail:
    return dispatch_service.deliver_order(db, order_id)


@router.post(
    "/orders/{order_id}/cancel",
    response_model=DispatchOrderDetail,
    summary="Cancel by lifecycle stage (releases reservations/vehicle where permitted)",
)
def cancel_order_endpoint(order_id: int, db: Session = Depends(get_db)) -> DispatchOrderDetail:
    return dispatch_service.cancel_order(db, order_id)


@router.post(
    "/orders/{order_id}/confirm-route",
    response_model=RouteConfirmationResponse,
    summary="Confirm a recalculated safe route (required after a blockage invalidates it)",
)
def confirm_route_endpoint(
    order_id: int, db: Session = Depends(get_db)
) -> RouteConfirmationResponse:
    return dispatch_service.confirm_updated_route(db, order_id)
