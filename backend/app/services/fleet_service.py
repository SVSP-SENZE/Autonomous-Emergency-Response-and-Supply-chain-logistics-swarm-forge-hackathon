"""Phase 4 fleet engine: deterministic vehicle assignment + overview.

Selection algorithm (deterministic, documented):

1. Candidates are vehicles with status `available`, not under maintenance,
   not already assigned, and with `effective_capacity_kg >= cargo_weight_kg`.
2. Ranking: lowest capacity wastage (`capacity_kg - cargo_weight_kg`) first,
   then lowest vehicle id as a stable tie-breaker. Estimated route time is
   identical for every vehicle on the same order route, so it does not change
   the ranking.

Assignment never modifies stock — approval reserved it, dispatch deducts it.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.models import DispatchEvent, ReliefOrder, Vehicle
from app.models.enums import DispatchEventType, OrderStatus, VehicleStatus
from app.schemas.dispatch import (
    AssignmentCandidate,
    AssignVehicleResponse,
    FleetOverviewResponse,
    FleetVehicleOverview,
)
from app.services.dispatch_service import _add_event, _vehicle_for_order

logger = logging.getLogger("reliefmesh.fleet")

_ASSIGNABLE_STATUSES = {
    OrderStatus.DRAFT,
    OrderStatus.AWAITING_APPROVAL,
    OrderStatus.APPROVED,
}


def _candidate_vehicles(db: Session, cargo_weight_kg: float) -> list[Vehicle]:
    """Operational vehicles (status `available`) that can carry the cargo."""
    vehicles = db.scalars(select(Vehicle).order_by(Vehicle.id)).all()
    return [
        vehicle
        for vehicle in vehicles
        if vehicle.status == VehicleStatus.AVAILABLE
        and vehicle.effective_capacity_kg >= cargo_weight_kg
    ]


def _rank(candidates: list[Vehicle], cargo_weight_kg: float) -> list[Vehicle]:
    return sorted(
        candidates,
        key=lambda vehicle: (
            vehicle.effective_capacity_kg - cargo_weight_kg,  # least wastage
            vehicle.id,
        ),
    )


def _guard_assignable_order(order) -> None:
    if order.status not in _ASSIGNABLE_STATUSES:
        raise ConflictError(
            f"Order {order.order_code} is {order.status.value}; vehicles can only "
            "be (re)assigned while the order is still at the warehouse."
        )


def assign_vehicle(db: Session, order_id: int, vehicle_id: int | None = None):
    """Assign (or auto-select) a vehicle for a dispatch order.

    `vehicle_id=None` triggers the deterministic auto-selection algorithm.
    Reassignment (e.g. after a vehicle breakdown) is supported for orders that
    are still at the warehouse; the previous vehicle is released.
    """
    from app.services.dispatch_service import _get_order

    order = _get_order(db, order_id)
    _guard_assignable_order(order)

    cargo_weight_kg = float(order.total_cargo_weight_kg or 0.0)
    previous_vehicle = _vehicle_for_order(db, order)
    candidates = _candidate_vehicles(db, cargo_weight_kg)

    if vehicle_id is not None:
        vehicle = db.get(Vehicle, vehicle_id)
        if vehicle is None:
            raise NotFoundError(f"Vehicle {vehicle_id} not found")
        if vehicle.status != VehicleStatus.AVAILABLE:
            raise ConflictError(
                f"Vehicle '{vehicle.vehicle_code}' is {vehicle.status.value}, "
                "not available."
            )
        if cargo_weight_kg > vehicle.effective_capacity_kg:
            raise ConflictError(
                f"Cargo oversized: {cargo_weight_kg} kg exceeds "
                f"'{vehicle.vehicle_code}' capacity "
                f"{vehicle.effective_capacity_kg} kg.",
                details={
                    "cargo_weight_kg": cargo_weight_kg,
                    "vehicle_capacity_kg": vehicle.effective_capacity_kg,
                },
            )
        auto_selected = False
    else:
        ranked = _rank(candidates, cargo_weight_kg)
        if not ranked:
            raise ConflictError(
                "No available vehicle can carry this order.",
                details={
                    "cargo_weight_kg": cargo_weight_kg,
                    "candidates_considered": [
                        {
                            "vehicle_id": candidate.id,
                            "vehicle_code": candidate.vehicle_code,
                            "capacity_kg": candidate.effective_capacity_kg,
                        }
                        for candidate in sorted(
                            db.scalars(
                                select(Vehicle).where(
                                    Vehicle.status == VehicleStatus.AVAILABLE
                                )
                            ).all(),
                            key=lambda v: v.id,
                        )
                    ],
                },
            )
        vehicle = ranked[0]
        auto_selected = True
        vehicle_id = vehicle.id

    # Guard against assignment conflicts (vehicle taken between reads).
    if vehicle.status != VehicleStatus.AVAILABLE:
        raise ConflictError(
            f"Vehicle '{vehicle.vehicle_code}' was just taken by another order."
        )

    previous_vehicle_id = previous_vehicle.id if previous_vehicle else None
    if previous_vehicle is not None and previous_vehicle.id != vehicle.id:
        if previous_vehicle.status == VehicleStatus.ASSIGNED:
            previous_vehicle.status = VehicleStatus.AVAILABLE

    vehicle.status = VehicleStatus.ASSIGNED
    order.vehicle_id = vehicle.id

    event_type = (
        DispatchEventType.VEHICLE_ASSIGNED
        if previous_vehicle_id is None or previous_vehicle_id == vehicle.id
        else DispatchEventType.VEHICLE_REASSIGNED
    )
    _add_event(
        db,
        order.id,
        event_type,
        previous_status=order.status,
        new_status=order.status,
        description=(
            f"Vehicle '{vehicle.vehicle_code}' "
            f"({'auto-selected' if auto_selected else 'manually assigned'}) "
            f"for {cargo_weight_kg} kg of cargo."
            + (
                f" Replaces '{previous_vehicle.vehicle_code}'."
                if previous_vehicle and previous_vehicle.id != vehicle.id
                else ""
            )
        ),
        event_metadata={
            "vehicle_id": vehicle.id,
            "previous_vehicle_id": previous_vehicle_id,
            "auto_selected": auto_selected,
            "cargo_weight_kg": cargo_weight_kg,
        },
    )
    db.commit()
    logger.info(
        "Order %s: vehicle %s (%s)", order.order_code, vehicle.vehicle_code,
        "auto" if auto_selected else "manual",
    )
    return AssignVehicleResponse(
        order_id=order.id,
        order_code=order.order_code,
        assigned=True,
        auto_selected=auto_selected,
        vehicle=vehicle,
        previous_vehicle_id=previous_vehicle_id,
        cargo_weight_kg=cargo_weight_kg,
    )


def release_vehicle(db: Session, vehicle_id: int, *, order_id: int | None = None) -> None:
    """Return a vehicle to `available` (used by cancellation/delivery flows)."""
    vehicle = db.get(Vehicle, vehicle_id)
    if vehicle is None:
        raise NotFoundError(f"Vehicle {vehicle_id} not found")
    if vehicle.status in (
        VehicleStatus.ASSIGNED, VehicleStatus.DELAYED, VehicleStatus.IN_TRANSIT
    ):
        vehicle.status = VehicleStatus.AVAILABLE
        if order_id is not None:
            _add_event(
                db,
                order_id,
                DispatchEventType.VEHICLE_ASSIGNED,
                description=f"Vehicle '{vehicle.vehicle_code}' released back to available.",
                event_metadata={"vehicle_id": vehicle.id},
            )


def fleet_overview(db: Session) -> FleetOverviewResponse:
    """Real database-derived fleet state."""
    vehicles = list(db.scalars(select(Vehicle).order_by(Vehicle.id)).all())

    # Active order mapping (single query, then group in memory).
    active_statuses = [
        OrderStatus.AWAITING_APPROVAL,
        OrderStatus.APPROVED,
        OrderStatus.DISPATCHED,
        OrderStatus.IN_TRANSIT,
        OrderStatus.DELAYED,
    ]
    active_orders = {
        order.vehicle_id: order
        for order in db.scalars(
            select(ReliefOrder).where(
                ReliefOrder.vehicle_id.is_not(None),
                ReliefOrder.status.in_(active_statuses),
            ).order_by(ReliefOrder.id.desc())
        ).all()
    }

    counts = {status: 0 for status in VehicleStatus}
    for vehicle in vehicles:
        counts[vehicle.status] += 1

    available_capacity = sum(
        vehicle.effective_capacity_kg
        for vehicle in vehicles
        if vehicle.status == VehicleStatus.AVAILABLE
    )

    overview_vehicles = []
    for vehicle in vehicles:
        active = active_orders.get(vehicle.id)
        overview_vehicles.append(
            FleetVehicleOverview(
                id=vehicle.id,
                vehicle_code=vehicle.vehicle_code,
                vehicle_type=vehicle.vehicle_type,
                capacity=vehicle.capacity,
                capacity_kg=vehicle.capacity_kg,
                status=vehicle.status,
                current_location=vehicle.current_location,
                active_order_code=active.order_code if active else None,
                active_order_id=active.id if active else None,
            )
        )

    return FleetOverviewResponse(
        total_vehicles=len(vehicles),
        available=counts[VehicleStatus.AVAILABLE],
        assigned=counts[VehicleStatus.ASSIGNED],
        in_transit=counts[VehicleStatus.IN_TRANSIT],
        under_maintenance=counts[VehicleStatus.MAINTENANCE],
        delayed=counts[VehicleStatus.DELAYED],
        total_capacity_kg_available=round(float(available_capacity), 2),
        vehicles=overview_vehicles,
    )


def handle_vehicle_breakdown(db: Session, vehicle: Vehicle, changes: list[str]) -> None:
    """Simulation hook (SCENARIO D): flag + reassign affected orders.

    Runs INSIDE the simulation service transaction — this function must NOT
    commit. Rules:

    - awaiting_approval orders: assignment is cleared (broken vehicle unusable).
    - approved orders: reservations are preserved; an alternative available
      vehicle is auto-assigned when one fits; otherwise operator intervention
      is flagged.
    - dispatched/in-transit orders: flagged `delayed` (cargo is already on the
      road; reassignment is an operator decision).
    """
    affected = list(
        db.scalars(
            select(ReliefOrder).where(
                ReliefOrder.vehicle_id == vehicle.id,
                ReliefOrder.status.in_(
                    [
                        OrderStatus.AWAITING_APPROVAL,
                        OrderStatus.APPROVED,
                        OrderStatus.DISPATCHED,
                        OrderStatus.IN_TRANSIT,
                        OrderStatus.DELAYED,
                    ]
                ),
            )
        ).all()
    )
    if not affected:
        return

    for order in affected:
        if order.status == OrderStatus.AWAITING_APPROVAL:
            order.vehicle_id = None
            _add_event(
                db,
                order.id,
                DispatchEventType.VEHICLE_DELAYED,
                previous_status=order.status,
                new_status=order.status,
                description=(
                    f"Vehicle '{vehicle.vehicle_code}' broke down; assignment "
                    "cleared. Reassign a vehicle before approval."
                ),
                event_metadata={"broken_vehicle_id": vehicle.id},
            )
            changes.append(
                f"Order {order.order_code}: vehicle assignment cleared "
                "(breakdown); awaiting reassignment"
            )
        elif order.status == OrderStatus.APPROVED:
            # Preserve reservations; try an alternative vehicle.
            cargo = float(order.total_cargo_weight_kg or 0.0)
            candidates = [
                candidate
                for candidate in _candidate_vehicles(db, cargo)
                if candidate.id != vehicle.id
            ]
            ranked = _rank(candidates, cargo)
            if ranked:
                replacement = ranked[0]
                replacement.status = VehicleStatus.ASSIGNED
                order.vehicle_id = replacement.id
                _add_event(
                    db,
                    order.id,
                    DispatchEventType.VEHICLE_REASSIGNED,
                    previous_status=order.status,
                    new_status=order.status,
                    description=(
                        f"Vehicle '{vehicle.vehicle_code}' broke down; order "
                        f"reassigned to '{replacement.vehicle_code}' (reservations "
                        "preserved)."
                    ),
                    event_metadata={
                        "broken_vehicle_id": vehicle.id,
                        "replacement_vehicle_id": replacement.id,
                        "reservations_preserved": True,
                    },
                )
                changes.append(
                    f"Order {order.order_code}: reassigned to "
                    f"'{replacement.vehicle_code}' (reservations preserved)"
                )
            else:
                _add_event(
                    db,
                    order.id,
                    DispatchEventType.VEHICLE_DELAYED,
                    previous_status=order.status,
                    new_status=order.status,
                    description=(
                        f"Vehicle '{vehicle.vehicle_code}' broke down; no "
                        "alternative vehicle fits. Reservations preserved; "
                        "operator intervention required."
                    ),
                    event_metadata={"broken_vehicle_id": vehicle.id},
                )
                changes.append(
                    f"Order {order.order_code}: no alternative vehicle; "
                    "operator intervention flagged (reservations preserved)"
                )
        else:
            # Already on the road: flag delayed, no silent reassignment.
            order.status = OrderStatus.DELAYED
            _add_event(
                db,
                order.id,
                DispatchEventType.VEHICLE_DELAYED,
                previous_status=order.status,
                new_status=OrderStatus.DELAYED,
                description=(
                    f"Vehicle '{vehicle.vehicle_code}' broke down in transit; "
                    "order flagged delayed. Operator intervention required."
                ),
                event_metadata={"broken_vehicle_id": vehicle.id},
            )
            changes.append(
                f"Order {order.order_code}: flagged delayed (vehicle breakdown in transit)"
            )

    logger.info("Vehicle breakdown handled for %s (%s orders)", vehicle.vehicle_code, len(affected))
