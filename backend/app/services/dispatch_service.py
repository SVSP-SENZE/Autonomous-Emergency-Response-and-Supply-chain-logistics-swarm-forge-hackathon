"""Phase 4 dispatch engine: plans -> orders -> reservations -> deliveries.

State machine (validated at every transition):

    awaiting_approval -> approved -> dispatched -> in_transit -> delivered
                 \\-> cancelled            \\-> delayed (disruption)

Design rules:
- Order generation NEVER reserves or deducts stock.
- Approval reserves stock atomically (short write transaction).
- Dispatch deducts stock exactly once (status gate = idempotency guard).
- Delivery adds stock to the relief centre exactly once.
- Every transition appends a persistent DispatchEvent (never label-only).
- Movement progress is simulated deterministically along the stored route —
  no random positions, no physical vehicles.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.clock import utcnow
from app.core.dispatch_config import dispatch_settings
from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.models import (
    AllocationResult,
    DispatchEvent,
    Inventory,
    InventoryMovement,
    PlanningRun,
    ReliefCentre,
    ReliefCentreInventory,
    ReliefOrder,
    ReliefOrderItem,
    RoadNode,
    RoadSegment,
    Vehicle,
    Warehouse,
)
from app.models.enums import (
    DispatchEventType,
    InventoryMovementType,
    OperationalStatus,
    OrderStatus,
    VehicleStatus,
)
from app.schemas.dispatch import (
    DispatchEventListResponse,
    DispatchEventRead,
    DispatchMovementRead,
    DispatchOrderDetail,
    DispatchOrderListResponse,
    DispatchOrderRead,
    DispatchSummaryResponse,
    GeneratedOrderBrief,
    GenerateOrdersResponse,
    RouteConfirmationResponse,
    SkippedShipment,
    TrackingResponse,
    TrackingSegmentRead,
)
from app.schemas.planning import RouteRead
from app.services.routing_service import find_route, get_node_for_entity

logger = logging.getLogger("reliefmesh.dispatch")

_NON_GENERATION_STATUSES = {
    OrderStatus.APPROVED,
    OrderStatus.DISPATCHED,
    OrderStatus.IN_TRANSIT,
    OrderStatus.DELAYED,
    OrderStatus.DELIVERED,
}
_CANCELLABLE_INVENTORY_STATUSES = {OrderStatus.APPROVED}


# --------------------------------------------------------------------------- #
# Route / state helpers
# --------------------------------------------------------------------------- #


def build_route_snapshot(route: RouteRead) -> dict[str, Any]:
    """Build the persisted route snapshot for an order route_metadata.

    Includes ordered coordinates so the tracking simulation can interpolate
    positions without re-reading the road graph.
    """
    node_ids = list(route.route_nodes)
    return {
        "reachable": route.reachable,
        "origin_node_id": route.origin_node_id,
        "destination_node_id": route.destination_node_id,
        "route_nodes": node_ids,
        "route_node_names": list(route.route_node_names),
        "segments": [segment.model_dump(mode="json") for segment in route.segments],
        "total_distance_km": route.distance_km,
        "total_travel_time_minutes": route.estimated_travel_time_minutes,
        "route_risk": route.route_risk,
        "blocked_segments_avoided": route.blocked_segments_avoided,
        "computed_at": utcnow().isoformat(),
    }


def _route_segment_ids(metadata: dict[str, Any]) -> set[int]:
    return {
        int(segment["segment_id"])
        for segment in (metadata or {}).get("segments", [])
        if segment.get("segment_id") is not None
    }


def blocked_segments_in_route(db: Session, metadata: dict[str, Any]) -> list[RoadSegment]:
    """Segments of a stored route that the DB currently marks blocked."""
    segment_ids = _route_segment_ids(metadata)
    if not segment_ids:
        return []
    return list(
        db.scalars(
            select(RoadSegment).where(
                RoadSegment.id.in_(segment_ids), RoadSegment.is_blocked.is_(True)
            )
        ).all()
    )


def _route_totals(metadata: dict[str, Any]) -> tuple[float, float]:
    """(total distance km, total travel minutes) of a stored route."""
    return (
        float((metadata or {}).get("total_distance_km") or 0.0),
        float((metadata or {}).get("total_travel_time_minutes") or 0.0),
    )


def _coords_for_nodes(db: Session, node_ids: list[int]) -> dict[int, RoadNode]:
    if not node_ids:
        return {}
    nodes = db.scalars(select(RoadNode).where(RoadNode.id.in_(node_ids))).all()
    return {node.id: node for node in nodes}


def position_on_route(
    db: Session, metadata: dict[str, Any], progress_minutes: float
) -> tuple[float | None, float | None, str | None, float]:
    """Deterministic position on the stored route at `progress_minutes`.

    Returns (lat, lng, nearest-node-name, travelled_km). Interpolates between
    the segment endpoints using the time fraction inside the segment.
    """
    segments = list((metadata or {}).get("segments", []))
    coords: dict[int, RoadNode] = {}
    accumulated = 0.0
    travelled_km = 0.0
    lat: float | None = None
    lng: float | None = None
    node_name: str | None = None

    node_ids_needed = {
        node_id
        for segment in segments
        for node_id in (segment.get("from_node_id"), segment.get("to_node_id"))
        if node_id is not None
    }
    if node_ids_needed:
        coords = _coords_for_nodes(db, sorted(node_ids_needed))

    for segment in segments:
        seg_minutes = float(segment.get("estimated_travel_time_minutes") or 0.0)
        seg_km = float(segment.get("distance_km") or 0.0)
        seg_end = accumulated + seg_minutes
        from_node = coords.get(segment.get("from_node_id"))
        to_node = coords.get(segment.get("to_node_id"))
        node_name = from_node.node_name if from_node else node_name

        if lat is None and from_node is not None:
            lat, lng, node_name = from_node.latitude, from_node.longitude, from_node.node_name

        if progress_minutes <= seg_end or seg_minutes <= 0:
            fraction = 0.0 if seg_minutes <= 0 else max(
                0.0, min(1.0, (progress_minutes - accumulated) / seg_minutes)
            )
            if from_node is not None and to_node is not None:
                lat = from_node.latitude + (to_node.latitude - from_node.latitude) * fraction
                lng = from_node.longitude + (
                    to_node.longitude - from_node.longitude
                ) * fraction
                node_name = (
                    from_node.node_name
                    if fraction < 0.5
                    else to_node.node_name
                )
            travelled_km += seg_km * fraction
            return lat, lng, node_name, round(travelled_km, 2)

        accumulated = seg_end
        travelled_km += seg_km
        if to_node is not None:
            lat, lng, node_name = to_node.latitude, to_node.longitude, to_node.node_name

    # progress beyond the last segment: vehicle is at the destination.
    if segments:
        to_node = coords.get(segments[-1].get("to_node_id"))
        if to_node is not None:
            lat, lng, node_name = to_node.latitude, to_node.longitude, to_node.node_name
    return lat, lng, node_name, round(travelled_km, 2)


def _add_event(
    db: Session,
    order_id: int,
    event_type: DispatchEventType,
    *,
    previous_status: OrderStatus | None = None,
    new_status: OrderStatus | None = None,
    description: str | None = None,
    event_metadata: dict[str, Any] | None = None,
) -> None:
    db.add(
        DispatchEvent(
            relief_order_id=order_id,
            event_type=event_type.value,
            previous_status=previous_status.value if previous_status else None,
            new_status=new_status.value if new_status else None,
            description=(description or "")[:500],
            event_metadata=event_metadata or {},
        )
    )


def _add_movement(
    db: Session,
    order: ReliefOrder,
    supply_type,
    quantity: float,
    movement_type: InventoryMovementType,
    event_metadata: dict[str, Any] | None = None,
) -> None:
    db.add(
        InventoryMovement(
            warehouse_id=order.warehouse_id,
            relief_centre_id=order.relief_centre_id,
            relief_order_id=order.id,
            supply_type=supply_type,
            quantity=quantity,
            movement_type=movement_type,
            event_metadata=event_metadata or {},
        )
    )


def _get_order(db: Session, order_id: int) -> ReliefOrder:
    order = db.get(ReliefOrder, order_id)
    if order is None:
        raise NotFoundError(f"Dispatch order {order_id} not found")
    return order


def _order_items_int(order: ReliefOrder) -> dict[Any, int]:
    """Item quantities as whole units (ceil) — inventory is integer-stocked."""
    return {
        item.supply_type: int(math.ceil(item.quantity - 1e-9)) for item in order.items
    }


def _warehouse_inventory_map(db: Session, warehouse_id: int) -> dict[Any, Inventory]:
    rows = db.scalars(select(Inventory).where(Inventory.warehouse_id == warehouse_id)).all()
    return {row.supply_type: row for row in rows}


def _assert_operational(entity, kind: str) -> None:
    if entity.operational_status != OperationalStatus.OPERATIONAL:
        raise ConflictError(
            f"{kind} '{entity.name}' is {entity.operational_status.value}; "
            "operation rejected.",
            details={"entity": kind, "status": entity.operational_status.value},
        )


def _vehicle_for_order(db: Session, order: ReliefOrder) -> Vehicle | None:
    if order.vehicle_id is None:
        return None
    return db.get(Vehicle, order.vehicle_id)


# --------------------------------------------------------------------------- #
# Phase C: dispatch order generation
# --------------------------------------------------------------------------- #


def _orders_brief(orders: list[ReliefOrder]) -> list[GeneratedOrderBrief]:
    briefs = []
    for order in orders:
        briefs.append(
            GeneratedOrderBrief(
                order_id=order.id,
                order_code=order.order_code,
                warehouse_id=order.warehouse_id,
                warehouse_name=order.warehouse.name if order.warehouse else "",
                relief_centre_id=order.relief_centre_id,
                relief_centre_name=(
                    order.relief_centre.name if order.relief_centre else ""
                ),
                items={
                    item.supply_type.value: item.quantity for item in order.items
                },
                cargo_weight_kg=order.total_cargo_weight_kg,
                estimated_travel_time_minutes=order.estimated_travel_time_minutes,
            )
        )
    return briefs


def generate_orders_from_plan(
    db: Session,
    planning_run_id: int,
    *,
    regenerate: bool = False,
) -> GenerateOrdersResponse:
    """Create dispatch order drafts from a persisted allocation plan (idempotent).

    Groups allocation lines by (warehouse, relief centre), combines supply
    types into one order per pair, computes cargo weight and a fresh route.
    Unreachable destinations are skipped with an explicit reason. Nothing is
    reserved at this stage.
    """
    run = db.get(PlanningRun, planning_run_id)
    if run is None:
        raise NotFoundError(f"Planning run {planning_run_id} not found")
    if run.planning_type.value != "allocation":
        raise BadRequestError(
            f"Planning run {planning_run_id} is a "
            f"{run.planning_type.value} run; dispatch orders need an allocation run."
        )

    existing_orders = list(
        db.scalars(
            select(ReliefOrder)
            .where(ReliefOrder.planning_run_id == planning_run_id)
            .options(selectinload(ReliefOrder.items))
        ).all()
    )

    if existing_orders:
        blocking = [
            order for order in existing_orders if order.status in _NON_GENERATION_STATUSES
        ]
        if blocking and regenerate:
            raise ConflictError(
                "Regeneration refused: from this plan, orders have already been "
                "approved/dispatched; audit history must be preserved.",
                details={
                    "blocking_orders": [order.order_code for order in blocking],
                },
            )
        if not regenerate:
            # Idempotent re-invocation: same plan -> same orders, no duplicates.
            return GenerateOrdersResponse(
                planning_run_id=planning_run_id,
                existing=_orders_brief(existing_orders),
                message=(
                    "Dispatch orders already exist for this planning run; "
                    "returning them without duplicating."
                ),
            )
        # Explicit regeneration of untouched drafts only.
        for order in existing_orders:
            db.delete(order)
        db.flush()

    rows = db.scalars(
        select(AllocationResult).where(
            AllocationResult.planning_run_id == planning_run_id,
            AllocationResult.allocated_quantity > 0,
            AllocationResult.warehouse_id.is_not(None),
        )
    ).all()
    if not rows:
        raise BadRequestError(
            f"Planning run {planning_run_id} has no positive allocation lines to dispatch."
        )

    # Group supply types by (warehouse, centre) pair.
    grouped: dict[tuple[int, int], dict[Any, float]] = {}
    names: dict[tuple[int, int], tuple[str, str]] = {}
    for row in rows:
        key = (int(row.warehouse_id), int(row.relief_centre_id))
        grouped.setdefault(key, {})
        grouped[key][row.supply_type] = (
            grouped[key].get(row.supply_type, 0.0) + float(row.allocated_quantity)
        )
        warehouse_name = row.warehouse_name or ""
        centre_name = row.relief_centre_name or ""
        names[key] = (warehouse_name, centre_name)

    generated: list[GeneratedOrderBrief] = []
    skipped: list[SkippedShipment] = []

    for (warehouse_id, centre_id), supplies in sorted(grouped.items()):
        warehouse = db.get(Warehouse, warehouse_id)
        centre = db.get(ReliefCentre, centre_id)
        warehouse_name, centre_name = names[(warehouse_id, centre_id)]
        if warehouse is None or centre is None:
            skipped.append(
                SkippedShipment(
                    warehouse_id=warehouse_id,
                    warehouse_name=warehouse_name,
                    relief_centre_id=centre_id,
                    relief_centre_name=centre_name,
                    reason="Warehouse or relief centre no longer exists.",
                )
            )
            continue

        # Fresh route on the current network (blocked roads change reality).
        try:
            origin_node = get_node_for_entity(db, "warehouse", warehouse_id)
            destination_node = get_node_for_entity(db, "relief_centre", centre_id)
            route = find_route(db, origin_node.id, destination_node.id)
        except (NotFoundError, BadRequestError) as exc:
            skipped.append(
                SkippedShipment(
                    warehouse_id=warehouse_id,
                    warehouse_name=warehouse_name,
                    relief_centre_id=centre_id,
                    relief_centre_name=centre_name,
                    reason=f"No linked road node: {exc.message}",
                )
            )
            continue
        if not route.reachable:
            skipped.append(
                SkippedShipment(
                    warehouse_id=warehouse_id,
                    warehouse_name=warehouse_name,
                    relief_centre_id=centre_id,
                    relief_centre_name=centre_name,
                    reason=(
                        "Destination unreachable on the current road network; "
                        "no order generated."
                    ),
                )
            )
            continue

        snapshot = build_route_snapshot(route)
        items_int = {
            supply_type: int(math.ceil(quantity - 1e-9))
            for supply_type, quantity in supplies.items()
        }
        cargo_kg = round(
            sum(
                items_int[supply_type] * dispatch_settings.weight_for(supply_type.value)
                for supply_type in items_int
            ),
            2,
        )
        order = ReliefOrder(
            order_code=f"DISP-R{planning_run_id}W{warehouse_id}C{centre_id}",
            warehouse_id=warehouse_id,
            relief_centre_id=centre_id,
            planning_run_id=planning_run_id,
            status=OrderStatus.AWAITING_APPROVAL,
            priority=centre.priority,
            estimated_travel_time_minutes=int(route.estimated_travel_time_minutes),
            total_cargo_weight_kg=cargo_kg,
            route_metadata=snapshot,
            is_demo=True,
        )
        db.add(order)
        db.flush()
        for supply_type, quantity in items_int.items():
            db.add(
                ReliefOrderItem(
                    relief_order_id=order.id,
                    supply_type=supply_type,
                    quantity=quantity,
                    unit="litres" if supply_type.value == "water_litre" else "kits",
                    estimated_weight_kg=round(
                        quantity * dispatch_settings.weight_for(supply_type.value), 2
                    ),
                )
            )
        _add_event(
            db,
            order.id,
            DispatchEventType.ORDER_GENERATED,
            new_status=OrderStatus.AWAITING_APPROVAL,
            description=(
                f"Generated from allocation plan {planning_run_id}: "
                f"{warehouse_name} -> {centre_name}"
            ),
            event_metadata={
                "planning_run_id": planning_run_id,
                "cargo_weight_kg": cargo_kg,
                "items": {st.value: q for st, q in items_int.items()},
            },
        )
        generated.append(
            GeneratedOrderBrief(
                order_id=order.id,
                order_code=order.order_code,
                warehouse_id=warehouse_id,
                warehouse_name=warehouse_name,
                relief_centre_id=centre_id,
                relief_centre_name=centre_name,
                items={st.value: q for st, q in items_int.items()},
                cargo_weight_kg=cargo_kg,
                estimated_travel_time_minutes=int(route.estimated_travel_time_minutes),
            )
        )

    db.commit()
    logger.info(
        "Dispatch generation for run %s: %s created, %s skipped",
        planning_run_id, len(generated), len(skipped),
    )
    return GenerateOrdersResponse(
        planning_run_id=planning_run_id,
        generated=generated,
        skipped=skipped,
        message=(
            "Dispatch orders created (awaiting approval)."
            if generated
            else "No dispatch orders could be generated from this plan."
        ),
    )


# --------------------------------------------------------------------------- #
# Phase C: route confirmation (SCENARIO C: bridge collapse before approval)
# --------------------------------------------------------------------------- #


def _fresh_route_for_order(db: Session, order: ReliefOrder) -> RouteRead | None:
    try:
        origin_node = get_node_for_entity(db, "warehouse", order.warehouse_id)
        destination_node = get_node_for_entity(db, "relief_centre", order.relief_centre_id)
        route = find_route(db, origin_node.id, destination_node.id)
    except (NotFoundError, BadRequestError):
        return None
    return route if route.reachable else None


def _reroute_snapshot(db: Session, order: ReliefOrder) -> tuple[bool, str, dict | None]:
    """(route_updated, message, current-route-or-suggested) for stored routes."""
    blocked = blocked_segments_in_route(db, order.route_metadata)
    if not blocked:
        return False, "The stored route is still fully passable.", order.route_metadata
    fresh = _fresh_route_for_order(db, order)
    if fresh is None:
        return (
            False,
            "Stored route contains blocked segment(s) and no alternative route exists.",
            None,
        )
    suggested = build_route_snapshot(fresh)
    return (
        False,
        (
            "Stored route contains blocked segment(s) "
            f"({', '.join(str(s.id) for s in blocked)}). An alternative route exists "
            f"({fresh.estimated_travel_time_minutes} min); confirm it before approval."
        ),
        suggested,
    )


def confirm_updated_route(db: Session, order_id: int):
    """Replace the stored route with the currently computed safe one."""
    order = _get_order(db, order_id)
    if order.status not in (OrderStatus.AWAITING_APPROVAL, OrderStatus.DRAFT):
        raise ConflictError(
            f"Route confirmation is only available for planning-stage orders "
            f"(current status: {order.status.value})."
        )
    blocked = blocked_segments_in_route(db, order.route_metadata)
    fresh = _fresh_route_for_order(db, order)
    if fresh is None:
        raise ConflictError(
            "No safe route currently exists to the destination; approval disabled.",
        )
    snapshot = build_route_snapshot(fresh)
    previous_time = order.estimated_travel_time_minutes
    order.route_metadata = snapshot
    order.estimated_travel_time_minutes = int(fresh.estimated_travel_time_minutes)
    _add_event(
        db,
        order.id,
        DispatchEventType.ROUTE_RECALCULATED,
        previous_status=order.status,
        new_status=order.status,
        description=(
            f"Route updated after operator confirmation: {previous_time} -> "
            f"{fresh.estimated_travel_time_minutes} min (blocked: "
            f"{', '.join(str(s.id) for s in blocked) or 'n/a'})."
        ),
        event_metadata={"planning_run_id": order.planning_run_id},
    )
    db.commit()
    logger.info("Route confirmed for order %s", order.order_code)
    return RouteConfirmationResponse(
        order_id=order.id,
        order_code=order.order_code,
        status=order.status,
        route_updated=True,
        route=snapshot,
        message="Updated route confirmed and stored; the order can now be approved.",
    )


# --------------------------------------------------------------------------- #
# Phase E: approval + atomic inventory reservation
# --------------------------------------------------------------------------- #


def approve_order(db: Session, order_id: int):
    """Reserve stock and approve — atomic, all-or-nothing."""
    order = _get_order(db, order_id)
    if order.status in (OrderStatus.APPROVED, OrderStatus.DISPATCHED, OrderStatus.IN_TRANSIT):
        raise ConflictError(f"Order {order.order_code} is already {order.status.value}.")
    if order.status == OrderStatus.CANCELLED:
        raise ConflictError("A cancelled order cannot be approved.")
    if order.status == OrderStatus.DELIVERED:
        raise ConflictError("A delivered order cannot be approved.")
    if order.status != OrderStatus.AWAITING_APPROVAL:
        raise ConflictError(
            f"Only orders awaiting approval can be approved "
            f"(current status: {order.status.value})."
        )

    warehouse = order.warehouse
    centre = order.relief_centre
    if warehouse is None or centre is None:
        raise NotFoundError("Order references a missing warehouse or relief centre.")
    _assert_operational(warehouse, "Warehouse")
    _assert_operational(centre, "Relief centre")

    vehicle = _vehicle_for_order(db, order)
    if vehicle is None:
        raise ConflictError(
            "No vehicle is assigned to this order; use POST "
            f"/api/v1/dispatch/orders/{order.id}/assign-vehicle first."
        )
    if vehicle.status not in (VehicleStatus.ASSIGNED, VehicleStatus.AVAILABLE):
        raise ConflictError(
            f"Vehicle '{vehicle.vehicle_code}' is {vehicle.status.value}, not assignable."
        )

    if order.total_cargo_weight_kg > vehicle.effective_capacity_kg:
        raise ConflictError(
            f"Cargo weight {order.total_cargo_weight_kg} kg exceeds vehicle capacity "
            f"{vehicle.effective_capacity_kg} kg.",
            details={"cargo_weight_kg": order.total_cargo_weight_kg},
        )

    # Route validity: all stored segments must still be passable.
    blocked = blocked_segments_in_route(db, order.route_metadata)
    if blocked:
        route_updated, message, suggested = _reroute_snapshot(db, order)
        details: dict[str, Any] = {
            "blocked_segment_ids": [segment.id for segment in blocked],
        }
        if suggested is not None:
            details["suggested_route"] = suggested
            details["suggested_route_minutes"] = suggested.get("total_travel_time_minutes")
        raise ConflictError(message, details=details)

    # Inventory availability (all items before touching anything).
    inventory_map = _warehouse_inventory_map(db, order.warehouse_id)
    needed = _order_items_int(order)
    for supply_type, quantity in needed.items():
        row = inventory_map.get(supply_type)
        if row is None:
            raise ConflictError(
                f"Warehouse does not stock {supply_type.value}; cannot reserve."
            )
        if row.available_quantity < quantity:
            raise ConflictError(
                f"Insufficient stock: {supply_type.value} needs {quantity}, "
                f"available {row.available_quantity}."
            )

    # Atomic reservation (short transaction; invariant checked by DB too).
    for supply_type, quantity in needed.items():
        item_row = next(
            item for item in order.items if item.supply_type == supply_type
        )
        row = inventory_map[supply_type]
        row.reserved_quantity += quantity
        if row.reserved_quantity > row.quantity:  # pragma: no cover - DB guard
            raise ConflictError(
                f"Reservation would exceed stock for {supply_type.value}."
            )
        _add_movement(
            db,
            order,
            supply_type,
            item_row.quantity,
            InventoryMovementType.RESERVED,
            event_metadata={"reserved_quantity": quantity},
        )

    previous_status = order.status
    order.status = OrderStatus.APPROVED
    order.approved_at = utcnow()
    if vehicle.status != VehicleStatus.ASSIGNED:
        vehicle.status = VehicleStatus.ASSIGNED
    _add_event(
        db,
        order.id,
        DispatchEventType.ORDER_APPROVED,
        previous_status=previous_status,
        new_status=OrderStatus.APPROVED,
        description=(
            f"Approved: reserved {sum(needed.values())} unit(s) across "
            f"{len(needed)} supply type(s) at '{warehouse.name}'."
        ),
        event_metadata={
            "reserved": {st.value: q for st, q in needed.items()},
            "vehicle": vehicle.vehicle_code,
        },
    )
    _add_event(
        db,
        order.id,
        DispatchEventType.INVENTORY_RESERVED,
        new_status=OrderStatus.APPROVED,
        description="Inventory reserved for this order.",
        event_metadata={st.value: q for st, q in needed.items()},
    )
    db.commit()
    logger.info(
        "Order %s approved (reservations: %s)",
        order.order_code, {st.value: q for st, q in needed.items()},
    )
    return get_order_detail(db, order.id)


# --------------------------------------------------------------------------- #
# Phase F: dispatch execution (deduct once, idempotent)
# --------------------------------------------------------------------------- #


def dispatch_order(db: Session, order_id: int):
    """Deduct reserved stock and put the vehicle in transit — exactly once."""
    order = _get_order(db, order_id)
    if order.status == OrderStatus.DISPATCHED or order.status == OrderStatus.IN_TRANSIT:
        raise ConflictError(
            f"Order {order.order_code} was already dispatched; inventory is only "
            "deducted once per order."
        )
    if order.status != OrderStatus.APPROVED:
        raise ConflictError(
            f"Only approved orders can be dispatched (current status: {order.status.value})."
        )

    warehouse = order.warehouse
    if warehouse is None:
        raise NotFoundError("Order references a missing warehouse.")
    _assert_operational(warehouse, "Warehouse")

    vehicle = _vehicle_for_order(db, order)
    if vehicle is None:
        raise ConflictError(
            "Order lost its assigned vehicle before dispatch; reassignment required."
        )
    if vehicle.status not in (VehicleStatus.ASSIGNED, VehicleStatus.AVAILABLE):
        raise ConflictError(
            f"Vehicle '{vehicle.vehicle_code}' is {vehicle.status.value} and cannot be dispatched."
        )

    # Route validity at dispatch time (roads may have changed since approval).
    blocked = blocked_segments_in_route(db, order.route_metadata)
    if blocked:
        raise ConflictError(
            "Route is no longer passable; rescind or confirm an updated route first.",
            details={"blocked_segment_ids": [segment.id for segment in blocked]},
        )

    # Reservation must still exist for every item before deducting.
    inventory_map = _warehouse_inventory_map(db, order.warehouse_id)
    needed = _order_items_int(order)
    for supply_type, quantity in needed.items():
        row = inventory_map.get(supply_type)
        if row is None or row.reserved_quantity < quantity:
            raise ConflictError(
                f"Missing or insufficient reservation for {supply_type.value} "
                f"(needs {quantity})."
            )

    # Atomic deduction: quantity AND reserved_quantity drop together.
    for supply_type, quantity in needed.items():
        row = inventory_map[supply_type]
        row.quantity -= quantity
        row.reserved_quantity -= quantity
        _add_movement(
            db,
            order,
            supply_type,
            quantity,
            InventoryMovementType.DISPATCHED,
            event_metadata={"deducted": quantity},
        )

    previous_status = order.status
    order.status = OrderStatus.DISPATCHED
    order.dispatched_at = utcnow()
    vehicle.status = VehicleStatus.IN_TRANSIT
    _add_event(
        db,
        order.id,
        DispatchEventType.VEHICLE_DISPATCHED,
        previous_status=previous_status,
        new_status=OrderStatus.DISPATCHED,
        description=(
            f"Vehicle '{vehicle.vehicle_code}' dispatched from "
            f"'{warehouse.name}' with {order.total_cargo_weight_kg} kg of cargo."
        ),
        event_metadata={
            "deducted": {st.value: q for st, q in needed.items()},
            "vehicle": vehicle.vehicle_code,
        },
    )
    db.commit()
    logger.info("Order %s dispatched with vehicle %s", order.order_code, vehicle.vehicle_code)
    return get_order_detail(db, order.id)


# --------------------------------------------------------------------------- #
# Phase G: deterministic tracking simulation
# --------------------------------------------------------------------------- #


def _remaining_route_state(
    metadata: dict[str, Any], progress: float
) -> tuple[list[dict[str, Any]], float, int]:
    """Split a stored route into traversal state.

    Returns (fully-traversed prefix segments, retreat-adjusted progress,
    index of the first remaining segment). If the vehicle is inside a segment
    that must be abandoned, simulated progress retreats to that segment's
    start node (no teleporting).
    """
    segments = list((metadata or {}).get("segments", []))
    accumulated = 0.0
    prefix: list[dict[str, Any]] = []
    for index, segment in enumerate(segments):
        seg_minutes = float(segment.get("estimated_travel_time_minutes") or 0.0)
        seg_end = accumulated + seg_minutes
        if seg_end <= progress + 1e-9:
            prefix.append(segment)
            accumulated = seg_end
            continue
        # progress is inside this segment; retreat to its start when rerouting.
        return prefix, accumulated, index
    return prefix, accumulated, len(segments)


def advance_order(db: Session, order_id: int, minutes: float | None = None):
    """Advance simulated journey deterministically along the stored route."""
    order = _get_order(db, order_id)
    if order.status not in (
        OrderStatus.DISPATCHED, OrderStatus.IN_TRANSIT, OrderStatus.DELAYED
    ):
        raise ConflictError(
            f"Only dispatched/in-transit/delayed orders can advance "
            f"(current status: {order.status.value})."
        )
    vehicle = _vehicle_for_order(db, order)
    if vehicle is None:
        raise ConflictError("Order has no vehicle to move.")

    metadata = dict(order.route_metadata or {})
    segments = list(metadata.get("segments", []))
    total = float(metadata.get("total_travel_time_minutes") or 0.0) or float(
        order.estimated_travel_time_minutes
    )
    progress = float(order.route_progress_minutes or 0.0)

    if progress >= total - 1e-9 and total > 0:
        # Already at destination; nothing to advance (deterministic no-op).
        return build_tracking_response(db, order)

    step = minutes if minutes is not None else dispatch_settings.advance_step_minutes
    progress = min(progress + step, total)

    delay_reason: str | None = None
    rerouted = False

    # --- disruption handling: passable remaining route? -----------------------
    prefix, retreat_progress, first_remaining_index = _remaining_route_state(
        metadata, progress
    )
    remaining_segments = segments[first_remaining_index:]
    blocked_remaining = [
        segment
        for segment in remaining_segments
        if segment.get("segment_id") is not None
        and db.scalar(
            select(RoadSegment.is_blocked).where(
                RoadSegment.id == int(segment["segment_id"])
            )
        )
    ]
    if blocked_remaining:
        reroute_from = remaining_segments[0].get("from_node_id")
        destination_node = metadata.get("destination_node_id")
        progress = retreat_progress  # retreat to a real road node (no teleport)
        alternative = None
        if reroute_from is not None and destination_node is not None:
            try:
                alternative = find_route(db, int(reroute_from), int(destination_node))
            except (NotFoundError, BadRequestError):
                alternative = None
        if alternative is not None and alternative.reachable:
            new_snapshot = build_route_snapshot(alternative)
            # Prefix nodes + new route nodes (unique continuation).
            metadata["segments"] = prefix + [
                seg.model_dump(mode="json") for seg in alternative.segments
            ]
            metadata["route_nodes"] = _prefix_node_ids(prefix) + list(
                alternative.route_nodes
            )
            metadata["route_node_names"] = _prefix_node_names(prefix) + list(
                alternative.route_node_names
            )
            new_total = progress + float(alternative.estimated_travel_time_minutes)
            metadata["total_travel_time_minutes"] = new_total
            metadata["total_distance_km"] = round(
                float(metadata.get("total_distance_km") or 0.0) * 0
                + sum(float(s["distance_km"]) for s in prefix)
                + float(alternative.distance_km),
                2,
            )
            metadata["rerouted_at"] = utcnow().isoformat()
            order.route_metadata = metadata
            order.estimated_travel_time_minutes = int(new_total)
            rerouted = True
            planned_remaining = total - retreat_progress
            if new_total - progress > planned_remaining + dispatch_settings.delay_threshold_minutes:
                delay_reason = (
                    f"Rerouted after blockage; +{round(new_total - progress - planned_remaining, 1)} min"
                )
            _add_event(
                db,
                order.id,
                DispatchEventType.ROUTE_RECALCULATED,
                previous_status=order.status,
                description=(
                    f"Remaining route blocked "
                    f"({', '.join(str(s.get('segment_id')) for s in blocked_remaining)}); "
                    f"rerouted ({alternative.estimated_travel_time_minutes} min remaining)."
                ),
                event_metadata={"retreated_to_minute": retreat_progress},
            )
        else:
            delay_reason = "No alternative route exists; operator intervention required."
            _add_event(
                db,
                order.id,
                DispatchEventType.VEHICLE_DELAYED,
                previous_status=order.status,
                new_status=OrderStatus.DELAYED,
                description=delay_reason,
                event_metadata={
                    "blocked_segment_ids": [
                        s.get("segment_id") for s in blocked_remaining
                    ]
                },
            )

    order.route_progress_minutes = progress

    previous_status = order.status
    if order.status == OrderStatus.DISPATCHED and progress > 0:
        order.status = OrderStatus.IN_TRANSIT
    if delay_reason and order.status != OrderStatus.DELAYED:
        order.status = OrderStatus.DELAYED

    # Deterministic position update from the (possibly new) stored route.
    lat, lng, node_name, _travelled_km = position_on_route(db, metadata, progress)
    vehicle.current_latitude = lat
    vehicle.current_longitude = lng
    if node_name:
        vehicle.current_location = node_name

    _add_event(
        db,
        order.id,
        DispatchEventType.PROGRESS_ADVANCED,
        previous_status=previous_status,
        new_status=order.status,
        description=(
            f"Advanced {step:g} min of simulated travel to {progress:g}/{total:g} min "
            f"(at '{node_name}')."
            + (f" {delay_reason}" if delay_reason else "")
        ),
        event_metadata={
            "advanced_minutes": step,
            "progress_minutes": progress,
            "progress_percent": order.progress_percent,
            "rerouted": rerouted,
        },
    )
    db.commit()
    logger.info(
        "Order %s advanced to %s%% at '%s'", order.order_code,
        order.progress_percent, node_name,
    )
    return build_tracking_response(db, order)


def _prefix_node_ids(prefix: list[dict[str, Any]]) -> list[int]:
    ids: list[int] = []
    for segment in prefix:
        from_id = segment.get("from_node_id")
        if from_id is not None and from_id not in ids:
            ids.append(int(from_id))
    if prefix:
        to_id = prefix[-1].get("to_node_id")
        if to_id is not None:
            ids.append(int(to_id))
    return ids


def _prefix_node_names(prefix: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for segment in prefix:
        from_name = segment.get("from_node_name")
        if from_name and from_name not in names:
            names.append(from_name)
    if prefix:
        to_name = prefix[-1].get("to_node_name")
        if to_name:
            names.append(to_name)
    return names


def build_tracking_response(db: Session, order: ReliefOrder) -> TrackingResponse:
    """Read model for the tracking endpoint (always derived from stored state)."""
    metadata = order.route_metadata or {}
    vehicle = _vehicle_for_order(db, order)
    warehouse = order.warehouse
    centre = order.relief_centre
    _, _, _, travelled_km = position_on_route(
        db, metadata, float(order.route_progress_minutes or 0.0)
    )
    total_distance = float(metadata.get("total_distance_km") or 0.0)
    total_time = float(
        metadata.get("total_travel_time_minutes") or order.estimated_travel_time_minutes
    )
    progress = float(order.route_progress_minutes or 0.0)
    remaining = max(int(round(total_time - progress)), 0)

    segments_out: list[TrackingSegmentRead] = []
    accumulated = 0.0
    for segment in metadata.get("segments", []):
        seg_minutes = float(segment.get("estimated_travel_time_minutes") or 0.0)
        traversed = accumulated + seg_minutes <= progress + 1e-9
        accumulated += seg_minutes
        segments_out.append(
            TrackingSegmentRead(
                segment_id=int(segment.get("segment_id") or 0),
                from_node_name=segment.get("from_node_name") or "",
                to_node_name=segment.get("to_node_name") or "",
                distance_km=float(segment.get("distance_km") or 0.0),
                estimated_travel_time_minutes=int(seg_minutes),
                risk_factor=float(segment.get("risk_factor") or 0.0),
                traversed=traversed,
            )
        )

    lat, lng, node_name, _ = position_on_route(db, metadata, progress)
    return TrackingResponse(
        order_id=order.id,
        order_code=order.order_code,
        status=order.status,
        vehicle_code=vehicle.vehicle_code if vehicle else None,
        origin=warehouse.name if warehouse else "",
        destination=centre.name if centre else "",
        total_distance_km=total_distance,
        estimated_travel_time_minutes=int(total_time),
        progress_minutes=progress,
        progress_percent=order.progress_percent,
        progress_km=travelled_km,
        current_latitude=lat,
        current_longitude=lng,
        current_node_name=node_name,
        remaining_travel_time_minutes=remaining,
        delayed=order.status == OrderStatus.DELAYED,
        last_updated_at=order.updated_at,
        segments=segments_out,
    )


def get_order_tracking(db: Session, order_id: int) -> TrackingResponse:
    order = _get_order(db, order_id)
    return build_tracking_response(db, order)


# --------------------------------------------------------------------------- #
# Phase H: delivery completion + inventory reconciliation
# --------------------------------------------------------------------------- #


def deliver_order(db: Session, order_id: int):
    """Add delivered supplies to the relief centre and release the vehicle."""
    order = _get_order(db, order_id)
    if order.status == OrderStatus.DELIVERED:
        raise ConflictError(
            f"Order {order.order_code} was already delivered; supplies are added "
            "to the relief centre exactly once."
        )
    if order.status not in (
        OrderStatus.DISPATCHED, OrderStatus.IN_TRANSIT, OrderStatus.DELAYED
    ):
        raise ConflictError(
            f"Only dispatched/in-transit orders can be delivered "
            f"(current status: {order.status.value}); never mark an undispatched "
            "order as delivered."
        )

    centre = order.relief_centre
    if centre is None:
        raise NotFoundError("Order references a missing relief centre.")
    _assert_operational(centre, "Relief centre")

    total_time = float(
        (order.route_metadata or {}).get("total_travel_time_minutes")
        or order.estimated_travel_time_minutes
    )
    if float(order.route_progress_minutes or 0.0) < total_time - 1e-6:
        raise ConflictError(
            "Vehicle has not arrived yet; advance the simulated journey to 100% "
            "before completing delivery.",
            details={
                "progress_percent": order.progress_percent,
            },
        )

    # Reconciliation: add stock to the relief centre (idempotent via status gate).
    needed = _order_items_int(order)
    for supply_type, quantity in needed.items():
        row = db.scalar(
            select(ReliefCentreInventory).where(
                ReliefCentreInventory.relief_centre_id == order.relief_centre_id,
                ReliefCentreInventory.supply_type == supply_type,
            )
        )
        if row is None:
            row = ReliefCentreInventory(
                relief_centre_id=order.relief_centre_id,
                supply_type=supply_type,
                quantity=0.0,
                unit="litres" if supply_type.value == "water_litre" else "kits",
            )
            db.add(row)
            db.flush()
        row.quantity += float(quantity)
        _add_movement(
            db,
            order,
            supply_type,
            float(quantity),
            InventoryMovementType.DELIVERED,
            event_metadata={"added_to_centre": float(quantity)},
        )

    previous_status = order.status
    order.status = OrderStatus.DELIVERED
    order.delivered_at = utcnow()
    order.actual_travel_time_minutes = int(round(total_time))

    vehicle = _vehicle_for_order(db, order)
    if vehicle is not None:
        vehicle.status = VehicleStatus.AVAILABLE
        vehicle.current_latitude = centre.latitude
        vehicle.current_longitude = centre.longitude
        vehicle.current_location = centre.name

    _add_event(
        db,
        order.id,
        DispatchEventType.DELIVERY_COMPLETED,
        previous_status=previous_status,
        new_status=OrderStatus.DELIVERED,
        description=(
            f"Delivered to '{centre.name}' at {round(total_time)} min of simulated "
            f"travel; vehicle released."
        ),
        event_metadata={st.value: q for st, q in needed.items()},
    )
    db.commit()
    logger.info("Order %s delivered to %s", order.order_code, centre.name)
    return get_order_detail(db, order.id)


# --------------------------------------------------------------------------- #
# Phase I: cancellation rules
# --------------------------------------------------------------------------- #


def cancel_order(db: Session, order_id: int):
    """Cancel by lifecycle stage (idempotent for already-cancelled orders)."""
    order = _get_order(db, order_id)
    if order.status == OrderStatus.CANCELLED:
        # Idempotent repeated cancellation.
        return get_order_detail(db, order.id)
    if order.status == OrderStatus.DELIVERED:
        raise ConflictError("A delivered order cannot be cancelled.")
    if order.status in (
        OrderStatus.DISPATCHED, OrderStatus.IN_TRANSIT, OrderStatus.DELAYED
    ):
        raise ConflictError(
            f"Order {order.order_code} is on the road ({order.status.value}); "
            "ordinary cancellation is not permitted (a return-to-warehouse "
            "workflow would be required)."
        )

    previous_status = order.status
    released_vehicle: Vehicle | None = _vehicle_for_order(db, order)

    if order.status in _CANCELLABLE_INVENTORY_STATUSES:
        # Approved: release the reservations made at approval.
        inventory_map = _warehouse_inventory_map(db, order.warehouse_id)
        needed = _order_items_int(order)
        released: dict[str, int] = {}
        for supply_type, quantity in needed.items():
            row = inventory_map.get(supply_type)
            if row is not None and row.reserved_quantity > 0:
                amount = min(quantity, row.reserved_quantity)
                row.reserved_quantity -= amount
                released[supply_type.value] = amount
                _add_movement(
                    db,
                    order,
                    supply_type,
                    amount,
                    InventoryMovementType.RESERVATION_RELEASED,
                    event_metadata={"released": amount},
                )
        released_summary = released
    else:
        # Draft / awaiting approval: no inventory to touch.
        released_summary = {}

    if released_vehicle is not None and released_vehicle.status == VehicleStatus.ASSIGNED:
        released_vehicle.status = VehicleStatus.AVAILABLE

    order.status = OrderStatus.CANCELLED
    _add_event(
        db,
        order.id,
        DispatchEventType.ORDER_CANCELLED,
        previous_status=previous_status,
        new_status=OrderStatus.CANCELLED,
        description=(
            "Order cancelled by operator"
            + (
                f"; reservations released: {released_summary}"
                if released_summary
                else "; no inventory was reserved"
            )
            + (
                f"; vehicle '{released_vehicle.vehicle_code}' released"
                if released_vehicle
                else ""
            )
            + "."
        ),
        event_metadata={
            "released_reservations": released_summary,
            "vehicle_released": released_vehicle.vehicle_code if released_vehicle else None,
        },
    )
    db.commit()
    logger.info("Order %s cancelled (was %s)", order.order_code, previous_status.value)
    return get_order_detail(db, order.id)


# --------------------------------------------------------------------------- #
# Phase H: dashboard, listing, detail, events
# --------------------------------------------------------------------------- #


def list_orders(
    db: Session,
    *,
    status: OrderStatus | None = None,
    priority=None,
    warehouse_id: int | None = None,
    relief_centre_id: int | None = None,
    vehicle_id: int | None = None,
    limit: int = 100,
) -> DispatchOrderListResponse:
    stmt = select(ReliefOrder).order_by(ReliefOrder.id.desc()).limit(limit)
    if status is not None:
        stmt = stmt.where(ReliefOrder.status == status)
    if priority is not None:
        stmt = stmt.where(ReliefOrder.priority == priority)
    if warehouse_id is not None:
        stmt = stmt.where(ReliefOrder.warehouse_id == warehouse_id)
    if relief_centre_id is not None:
        stmt = stmt.where(ReliefOrder.relief_centre_id == relief_centre_id)
    if vehicle_id is not None:
        stmt = stmt.where(ReliefOrder.vehicle_id == vehicle_id)
    orders = list(db.scalars(stmt).all())
    return DispatchOrderListResponse(
        total=len(orders),
        orders=[DispatchOrderRead.model_validate(order) for order in orders],
    )


def _movements_for(db: Session, order_id: int) -> list[DispatchMovementRead]:
    rows = db.scalars(
        select(InventoryMovement)
        .where(InventoryMovement.relief_order_id == order_id)
        .order_by(InventoryMovement.id)
    ).all()
    return [DispatchMovementRead.model_validate(row) for row in rows]


def _events_for(db: Session, order_id: int) -> list[DispatchEventRead]:
    rows = db.scalars(
        select(DispatchEvent)
        .where(DispatchEvent.relief_order_id == order_id)
        .order_by(DispatchEvent.id)
    ).all()
    return [DispatchEventRead.model_validate(row) for row in rows]


def get_order_detail(db: Session, order_id: int) -> DispatchOrderDetail:
    order = _get_order(db, order_id)
    vehicle = _vehicle_for_order(db, order)
    return DispatchOrderDetail(
        order=DispatchOrderRead.model_validate(order),
        warehouse_name=order.warehouse.name if order.warehouse else "",
        relief_centre_name=order.relief_centre.name if order.relief_centre else "",
        vehicle=vehicle,
        route=order.route_metadata or {},
        events=_events_for(db, order.id),
        inventory_movements=_movements_for(db, order.id),
    )


def list_events(
    db: Session, *, order_id: int | None = None, limit: int = 100
) -> DispatchEventListResponse:
    stmt = select(DispatchEvent).order_by(DispatchEvent.id.desc()).limit(limit)
    if order_id is not None:
        stmt = stmt.where(DispatchEvent.relief_order_id == order_id)
    rows = list(db.scalars(stmt).all())
    return DispatchEventListResponse(
        total=len(rows), events=[DispatchEventRead.model_validate(row) for row in rows]
    )


def dispatch_summary(db: Session) -> DispatchSummaryResponse:
    counts: dict[OrderStatus, int] = {status: 0 for status in OrderStatus}
    for status, total in db.execute(
        select(ReliefOrder.status, func.count()).group_by(ReliefOrder.status)
    ).all():
        counts[OrderStatus(status.value if hasattr(status, "value") else status)] = total

    on_the_road_statuses = (
        OrderStatus.DISPATCHED, OrderStatus.IN_TRANSIT, OrderStatus.DELAYED
    )
    dispatched_cargo = db.scalar(
        select(func.coalesce(func.sum(ReliefOrder.total_cargo_weight_kg), 0.0)).where(
            ReliefOrder.status.in_([*on_the_road_statuses, OrderStatus.DELIVERED])
        )
    ) or 0.0

    active_base = sum(counts[s] for s in (*on_the_road_statuses, OrderStatus.DELIVERED))
    completion = (
        round(counts[OrderStatus.DELIVERED] / active_base * 100.0, 1)
        if active_base > 0
        else 0.0
    )

    vehicles_assigned = int(
        db.scalar(
            select(func.count()).select_from(Vehicle).where(
                Vehicle.status.in_([VehicleStatus.ASSIGNED, VehicleStatus.IN_TRANSIT])
            )
        ) or 0
    )
    vehicles_available = int(
        db.scalar(
            select(func.count()).select_from(Vehicle).where(
                Vehicle.status == VehicleStatus.AVAILABLE
            )
        ) or 0
    )
    total_reserved = float(
        db.scalar(select(func.coalesce(func.sum(Inventory.reserved_quantity), 0.0))) or 0.0
    )

    return DispatchSummaryResponse(
        total_orders=sum(counts.values()),
        awaiting_approval=counts[OrderStatus.AWAITING_APPROVAL],
        approved=counts[OrderStatus.APPROVED],
        dispatched=counts[OrderStatus.DISPATCHED],
        in_transit=counts[OrderStatus.IN_TRANSIT],
        delayed=counts[OrderStatus.DELAYED],
        delivered=counts[OrderStatus.DELIVERED],
        cancelled=counts[OrderStatus.CANCELLED],
        total_cargo_weight_dispatched_kg=round(float(dispatched_cargo), 2),
        successful_deliveries=counts[OrderStatus.DELIVERED],
        delivery_completion_percent=completion,
        vehicles_assigned=vehicles_assigned,
        vehicles_available=vehicles_available,
        total_inventory_reserved=total_reserved,
    )

