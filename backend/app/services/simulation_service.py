"""Simulation service: reset the demo scenario and apply simulated events.

Each event handler validates its target, mutates the database and records a
`SimulationEvent` row — all inside a single transaction, so a failure never
leaves the database partially updated.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.exceptions import BadRequestError, NotFoundError
from app.models import (
    Incident,
    ReliefCentre,
    ReliefOrder,
    RoadSegment,
    SimulationEvent,
    Vehicle,
    Warehouse,
)
from app.services import fleet_service
from app.models.enums import (
    IncidentSource,
    IncidentStatus,
    IncidentType,
    OperationalStatus,
    OrderStatus,
    Priority,
    Severity,
    SimulationEventType,
    VehicleStatus,
)
from app.schemas.simulation import (
    SimulationEventCreate,
    SimulationEventRead,
    SimulationEventResult,
    SimulationResetResponse,
)
from app.services.seed_service import reset_demo_data

logger = logging.getLogger("reliefmesh.simulation")

PRIORITY_RANK: dict[Priority, int] = {
    Priority.LOW: 0,
    Priority.MEDIUM: 1,
    Priority.HIGH: 2,
    Priority.CRITICAL: 3,
}

SEVERITY_RANK: dict[Severity, int] = {
    Severity.LOW: 0,
    Severity.MEDIUM: 1,
    Severity.HIGH: 2,
    Severity.CRITICAL: 3,
}

SEVERITY_BY_RANK: dict[int, Severity] = {rank: severity for severity, rank in SEVERITY_RANK.items()}

DEFAULT_SEVERITY_BY_EVENT: dict[SimulationEventType, Severity] = {
    SimulationEventType.BRIDGE_COLLAPSE: Severity.HIGH,
    SimulationEventType.ROAD_BLOCKED: Severity.MEDIUM,
    SimulationEventType.WAREHOUSE_UNAVAILABLE: Severity.HIGH,
    SimulationEventType.RELIEF_CENTRE_WATER_SHORTAGE: Severity.HIGH,
    SimulationEventType.NEW_FLOOD_REPORT: Severity.HIGH,
    SimulationEventType.RAINFALL_ESCALATION: Severity.HIGH,
    SimulationEventType.VEHICLE_BREAKDOWN: Severity.MEDIUM,
}


def list_simulation_events(db: Session, limit: int = 100) -> list[SimulationEvent]:
    """Recent simulation events in chronological (oldest-first) order."""
    stmt = select(SimulationEvent).order_by(
        SimulationEvent.created_at.asc(), SimulationEvent.id.asc()
    ).limit(limit)
    return list(db.scalars(stmt).all())


def reset_simulation(db: Session) -> SimulationResetResponse:
    """Restore the initial seeded demo scenario (safe: demo rows only)."""
    counts = reset_demo_data(db)
    return SimulationResetResponse(
        data_mode="SIMULATED",
        message="Simulation reset to the initial seeded scenario.",
        counts=counts,
        reset_at=utcnow(),
    )


def apply_simulation_event(db: Session, payload: SimulationEventCreate) -> SimulationEventResult:
    """Validate and apply one simulated event, then return what changed."""
    try:
        handler = _HANDLERS.get(payload.event_type)
        if handler is None:
            raise BadRequestError(
                f"Unsupported event type: {payload.event_type}",
                details={"event_type": payload.event_type.value},
            )

        event_data: dict[str, Any] = dict(payload.event_data)
        event_data["simulated"] = True

        context = _EventContext(
            db=db,
            payload=payload,
            event_data=event_data,
            changes=[],
            affected_entity_type=None,
            affected_entity_id=None,
            location_name=payload.location_name,
            latitude=payload.latitude,
            longitude=payload.longitude,
            severity=payload.severity or DEFAULT_SEVERITY_BY_EVENT[payload.event_type],
            title=payload.title,
            description=payload.description,
        )
        handler(context)

        event = SimulationEvent(
            event_type=payload.event_type,
            title=context.title or payload.event_type.value.replace("_", " ").capitalize(),
            description=context.description or "Simulated event (demo data).",
            location_name=context.location_name,
            latitude=context.latitude,
            longitude=context.longitude,
            affected_entity_type=context.affected_entity_type,
            affected_entity_id=context.affected_entity_id,
            severity=context.severity,
            event_data=context.event_data,
            is_demo=True,
        )
        db.add(event)
        db.commit()
        db.refresh(event)
        logger.info(
            "Simulation event %s applied (id=%s): %s",
            payload.event_type.value,
            event.id,
            "; ".join(context.changes) or "no state change",
        )
        return SimulationEventResult(
            data_mode="SIMULATED",
            message=(
                f"Event '{payload.event_type.value}' applied. "
                + ("; ".join(context.changes) if context.changes else "No state change.")
            ),
            changes=context.changes,
            event=SimulationEventRead.model_validate(event),
        )
    except Exception:
        db.rollback()
        raise


class _EventContext:
    """Mutable state shared by event handlers while building the response."""

    def __init__(
        self,
        db: Session,
        payload: SimulationEventCreate,
        event_data: dict[str, Any],
        changes: list[str],
        affected_entity_type: str | None,
        affected_entity_id: int | None,
        location_name: str | None,
        latitude: float | None,
        longitude: float | None,
        severity: Severity,
        title: str | None,
        description: str | None,
    ) -> None:
        self.db = db
        self.payload = payload
        self.event_data = event_data
        self.changes = changes
        self.affected_entity_type = affected_entity_type
        self.affected_entity_id = affected_entity_id
        self.location_name = location_name
        self.latitude = latitude
        self.longitude = longitude
        self.severity = severity
        self.title = title
        self.description = description


# --------------------------------------------------------------------------- #
# Target lookup helpers
# --------------------------------------------------------------------------- #


def _get_road_segment(db: Session, segment_id: int | None) -> RoadSegment:
    if segment_id is None:
        raise BadRequestError(
            "Event requires a road segment target: provide `road_segment_id`."
        )
    segment = db.get(RoadSegment, segment_id)
    if segment is None:
        raise NotFoundError(f"Road segment {segment_id} not found")
    return segment


def _get_warehouse(db: Session, warehouse_id: int | None) -> Warehouse:
    if warehouse_id is None:
        raise BadRequestError(
            "Event requires a warehouse target: provide `warehouse_id`."
        )
    warehouse = db.get(Warehouse, warehouse_id)
    if warehouse is None:
        raise NotFoundError(f"Warehouse {warehouse_id} not found")
    return warehouse


def _get_relief_centre(db: Session, centre_id: int | None) -> ReliefCentre:
    if centre_id is None:
        raise BadRequestError(
            "Event requires a relief centre target: provide `relief_centre_id`."
        )
    centre = db.get(ReliefCentre, centre_id)
    if centre is None:
        raise NotFoundError(f"Relief centre {centre_id} not found")
    return centre


def _get_vehicle(db: Session, vehicle_id: int | None) -> Vehicle:
    if vehicle_id is None:
        raise BadRequestError("Event requires a vehicle target: provide `vehicle_id`.")
    vehicle = db.get(Vehicle, vehicle_id)
    if vehicle is None:
        raise NotFoundError(f"Vehicle {vehicle_id} not found")
    return vehicle


def _get_incident(db: Session, incident_id: int) -> Incident:
    incident = db.get(Incident, incident_id)
    if incident is None:
        raise NotFoundError(f"Incident {incident_id} not found")
    return incident


def _next_severity(current: Severity, requested: Severity | None) -> tuple[Severity, bool]:
    """Escalate severity one level (or to the requested level if higher)."""
    current_rank = SEVERITY_RANK[current]
    if requested is not None and SEVERITY_RANK.get(requested, -1) > current_rank:
        return requested, True
    if current_rank < max(SEVERITY_RANK.values()):
        return SEVERITY_BY_RANK[current_rank + 1], True
    return current, False


def _escalate_priority(
    centre: ReliefCentre, requested: Priority | None
) -> tuple[Priority, Priority]:
    """Escalate a centre's priority; returns (previous, new).

    Never downgrades. Escalates one level unless a higher level is requested.
    """
    previous = centre.priority
    current_rank = PRIORITY_RANK[previous]
    if requested is not None:
        target_rank = PRIORITY_RANK[requested]
    else:
        # One step up the ladder, capped at critical.
        target_rank = min(current_rank + 1, max(PRIORITY_RANK.values()))
    new = previous if current_rank >= target_rank else next(
        priority for priority, rank in PRIORITY_RANK.items() if rank == target_rank
    )
    return previous, new


def _find_deliverable_order(db: Session, vehicle_id: int) -> list[ReliefOrder]:
    active_statuses = (
        OrderStatus.APPROVED,
        OrderStatus.DISPATCHED,
        OrderStatus.IN_TRANSIT,
    )
    return list(
        db.scalars(
            select(ReliefOrder).where(
                ReliefOrder.vehicle_id == vehicle_id,
                ReliefOrder.status.in_(active_statuses),
            )
        ).all()
    )


# --------------------------------------------------------------------------- #
# Event handlers
# --------------------------------------------------------------------------- #


def _handle_bridge_collapse(ctx: _EventContext) -> None:
    segment = _get_road_segment(ctx.db, ctx.payload.road_segment_id)
    if segment.is_blocked:
        raise BadRequestError(
            "Road segment is already blocked.",
            details={"road_segment_id": segment.id},
        )
    reason = (
        ctx.payload.blockage_reason
        or str(ctx.payload.event_data.get("reason") or "Bridge collapsed under flood load (simulated)")
    )
    segment.is_blocked = True
    segment.blockage_reason = reason
    ctx.changes.extend(
        [
            f"Road segment {segment.id} ({segment.from_node_id} -> {segment.to_node_id}) marked as blocked",
            f"Blockage reason recorded: {reason}",
        ]
    )
    ctx.event_data["blockage_reason"] = reason
    from_node_name = segment.from_node.node_name
    to_node_name = segment.to_node.node_name
    ctx.event_data["endpoints"] = {"from_node": from_node_name, "to_node": to_node_name}
    ctx.event_data["distance_km"] = segment.distance_km
    ctx.changes.extend(
        [
            f"Affected endpoints: {from_node_name} -> {to_node_name}",
        ]
    )
    ctx.affected_entity_type = "road_segment"
    ctx.affected_entity_id = segment.id
    if ctx.location_name is None:
        ctx.location_name = f"{from_node_name} to {to_node_name}"
    if ctx.title is None:
        ctx.title = "Bridge collapse reported on simulated road segment"
    if ctx.description is None:
        ctx.description = (
            f"Simulated bridge collapse: {from_node_name} -> {to_node_name} blocked. {reason}"
        )


def _handle_road_blocked(ctx: _EventContext) -> None:
    segment = _get_road_segment(ctx.db, ctx.payload.road_segment_id)
    if segment.is_blocked:
        raise BadRequestError(
            "Road segment is already blocked.",
            details={"road_segment_id": segment.id},
        )
    reason = (
        ctx.payload.blockage_reason
        or str(ctx.payload.event_data.get("reason") or "Road blocked by flood water (simulated)")
    )
    segment.is_blocked = True
    segment.blockage_reason = reason
    ctx.changes.extend(
        [
            f"Road segment {segment.id} ({segment.from_node_id} -> {segment.to_node_id}) marked as blocked",
            f"Blockage reason recorded: {reason}",
        ]
    )
    ctx.event_data["blockage_reason"] = reason
    from_node = segment.from_node.node_name
    to_node = segment.to_node.node_name
    ctx.event_data["endpoints"] = {"from_node": from_node, "to_node": to_node}
    ctx.event_data["distance_km"] = segment.distance_km
    ctx.changes.append(f"Affected endpoints: {from_node} -> {to_node}")
    ctx.affected_entity_type = "road_segment"
    ctx.affected_entity_id = segment.id
    if ctx.location_name is None:
        ctx.location_name = f"{from_node} to {to_node}"
    if ctx.title is None:
        ctx.title = "Road segment blocked in simulated road network"
    if ctx.description is None:
        ctx.description = f"Simulated road closure: {reason}"


def _handle_warehouse_unavailable(ctx: _EventContext) -> None:
    warehouse = _get_warehouse(ctx.db, ctx.payload.warehouse_id)
    if ctx.location_name is None:
        ctx.location_name = warehouse.location_name
    if ctx.latitude is None:
        ctx.latitude = warehouse.latitude
    if ctx.longitude is None:
        ctx.longitude = warehouse.longitude
    if warehouse.operational_status == OperationalStatus.UNAVAILABLE:
        ctx.changes.append(
            f"Warehouse '{warehouse.name}' is already unavailable; stock remains flagged unavailable for allocation"
        )
    else:
        warehouse.operational_status = OperationalStatus.UNAVAILABLE
        ctx.changes.append(f"Warehouse '{warehouse.name}' marked as unavailable")
    total_items = len(list(warehouse.inventory))
    total_units = sum(item.quantity for item in warehouse.inventory)
    # Existing inventory is NOT deleted; it is flagged unavailable for future allocation.
    ctx.changes.append(
        f"Existing inventory retained and flagged unavailable for allocation "
        f"({total_items} stock lines, {total_units} units in simulated totals)"
    )
    ctx.event_data["inventory_lines"] = total_items
    ctx.event_data["inventory_units"] = total_units
    ctx.affected_entity_type = "warehouse"
    ctx.affected_entity_id = warehouse.id
    if ctx.title is None:
        ctx.title = f"Warehouse unavailable: {warehouse.name}"
    if ctx.description is None:
        ctx.description = (
            f"Simulated event: warehouse '{warehouse.name}' is no longer operational; "
            "stock cannot be allocated until restored."
        )


def _handle_relief_centre_water_shortage(ctx: _EventContext) -> None:
    centre = _get_relief_centre(ctx.db, ctx.payload.relief_centre_id)
    if ctx.location_name is None:
        ctx.location_name = f"{centre.name}, {centre.district}"
    if ctx.latitude is None:
        ctx.latitude = centre.latitude
    if ctx.longitude is None:
        ctx.longitude = centre.longitude
    previous_priority, new_priority = _escalate_priority(
        centre,
        _priority(ctx.payload.severity) if ctx.payload.severity is not None else None,
    )
    centre.water_shortage = True
    centre.water_shortage_notes = (
        ctx.payload.description
        or ctx.payload.event_data.get("notes")
        or "Reported drinking water shortage (simulated)."
    )
    if centre.priority != new_priority:
        centre.priority = new_priority
    ctx.changes.append(f"Water shortage recorded at '{centre.name}'")
    if new_priority != previous_priority:
        ctx.changes.append(
            f"Priority escalated from {previous_priority.value} to {new_priority.value}"
        )
    ctx.event_data["previous_priority"] = previous_priority.value
    ctx.event_data["new_priority"] = centre.priority.value
    ctx.affected_entity_type = "relief_centre"
    ctx.affected_entity_id = centre.id
    if ctx.title is None:
        ctx.title = f"Water shortage at {centre.name}"
    if ctx.description is None:
        ctx.description = (
            f"Simulated shortage: '{centre.name}' flagged drinking water stock as insufficient."
        )


def _handle_new_flood_report(ctx: _EventContext) -> None:
    centre: ReliefCentre | None = None
    if ctx.payload.relief_centre_id is not None:
        centre = _get_relief_centre(ctx.db, ctx.payload.relief_centre_id)
    if ctx.location_name is None and centre is not None:
        ctx.location_name = centre.district
    if (ctx.latitude is None or ctx.longitude is None) and centre is not None:
        ctx.latitude = centre.latitude
        ctx.longitude = centre.longitude
    if ctx.location_name is None or ctx.latitude is None or ctx.longitude is None:
        raise BadRequestError(
            "new_flood_report requires `relief_centre_id` or a location "
            "(`location_name`, `latitude`, `longitude`)."
        )
    severity = ctx.payload.severity or Severity.HIGH
    incident = Incident(
        incident_type=IncidentType.FLOOD,
        title=ctx.title
        or f"Flood reported near {ctx.location_name} (simulated)",
        description=ctx.description or "Simulated citizen flood report.",
        source=IncidentSource.SIMULATION,
        severity=severity,
        status=IncidentStatus.REPORTED,
        location_name=ctx.location_name,
        latitude=ctx.latitude,
        longitude=ctx.longitude,
        affected_population=ctx.payload.affected_population
        or (centre.affected_population if centre else 0),
        metadata_json={
            "simulated": True,
            "reported_by": ctx.payload.event_data.get("reported_by", "citizen_demo"),
        },
        is_demo=True,
    )
    ctx.db.add(incident)
    ctx.db.flush()
    ctx.changes.append(f"Flood incident {incident.id} created ('{incident.title}')")
    ctx.affected_entity_type = "incident"
    ctx.affected_entity_id = incident.id
    ctx.event_data["incident_id"] = incident.id
    if ctx.title is None:
        ctx.title = "New flood report recorded"
    if centre is not None:
        previous_priority, new_priority = _escalate_priority(centre, _priority(severity))
        if new_priority != previous_priority:
            centre.priority = new_priority
            ctx.changes.append(
                f"Relief centre '{centre.name}' priority escalated from "
                f"{previous_priority.value} to {new_priority.value}"
            )
        ctx.event_data["relief_centre_id"] = centre.id
        ctx.event_data["relief_centre_priority"] = centre.priority.value


def _handle_rainfall_escalation(ctx: _EventContext) -> None:
    target_incident: Incident | None = None
    if ctx.payload.incident_id is not None:
        target_incident = _get_incident(ctx.db, ctx.payload.incident_id)
    elif ctx.payload.relief_centre_id is not None:
        centre = _get_relief_centre(ctx.db, ctx.payload.relief_centre_id)
        target_incident = ctx.db.scalar(
            select(Incident)
            .where(
                Incident.incident_type == IncidentType.FLOOD,
                Incident.status == IncidentStatus.ACTIVE,
                Incident.location_name == centre.district,
            )
            .order_by(Incident.created_at.desc(), Incident.id.desc())
        )
        if target_incident is None:
            raise BadRequestError(
                "No active flood incident found for relief centre "
                f"{centre.id} ('{centre.name}'); provide `incident_id` instead."
            )
    else:
        raise BadRequestError(
            "rainfall_escalation requires `incident_id` or `relief_centre_id`."
        )

    new_severity, escalated = _next_severity(target_incident.severity, ctx.payload.severity)
    previous_severity = target_incident.severity
    if escalated:
        target_incident.severity = new_severity
        ctx.changes.append(
            f"Incident {target_incident.id} ('{target_incident.title}') severity raised "
            f"from {previous_severity.value} to {new_severity.value}"
        )
    else:
        ctx.changes.append(
            f"Incident {target_incident.id} severity remains {new_severity.value} (already at or above requested level)"
        )

    rainfall_mm = ctx.payload.event_data.get("rainfall_mm_24h")
    new_incident = Incident(
        incident_type=IncidentType.FLOOD,
        title=ctx.title
        or f"Rainfall escalation near {target_incident.location_name} (simulated)",
        description=ctx.description or "Simulated rainfall escalation over an affected area.",
        source=IncidentSource.SIMULATION,
        severity=new_severity,
        status=IncidentStatus.ACTIVE,
        location_name=target_incident.location_name,
        latitude=target_incident.latitude,
        longitude=target_incident.longitude,
        affected_population=target_incident.affected_population,
        metadata_json={
            "simulated": True,
            "parent_incident_id": target_incident.id,
            "rainfall_mm_24h": float(rainfall_mm) if rainfall_mm is not None else None,
        },
        is_demo=True,
    )
    ctx.db.add(new_incident)
    ctx.db.flush()
    ctx.changes.append(f"Updated weather incident {new_incident.id} recorded")
    ctx.affected_entity_type = "incident"
    ctx.affected_entity_id = new_incident.id
    ctx.event_data["target_incident_id"] = target_incident.id
    ctx.event_data["new_incident_id"] = new_incident.id
    ctx.event_data["previous_severity"] = previous_severity.value
    ctx.event_data["new_severity"] = new_severity.value
    if ctx.location_name is None:
        ctx.location_name = target_incident.location_name
    if ctx.latitude is None:
        ctx.latitude = target_incident.latitude
    if ctx.longitude is None:
        ctx.longitude = target_incident.longitude
    if ctx.title is None:
        ctx.title = f"Rainfall escalation: {target_incident.title}"


def _handle_vehicle_breakdown(ctx: _EventContext) -> None:
    vehicle = _get_vehicle(ctx.db, ctx.payload.vehicle_id)
    previous_status = vehicle.status
    vehicle.status = VehicleStatus.MAINTENANCE
    ctx.changes.append(
        f"Vehicle '{vehicle.vehicle_code}' status changed from {previous_status.value} to maintenance"
    )
    affected_orders = _find_deliverable_order(ctx.db, vehicle.id)
    if affected_orders:
        order_codes = ", ".join(order.order_code for order in affected_orders)
        ctx.changes.append(
            f"Undelivered relief orders still reference this vehicle and may need "
            f"reassignment: {order_codes}"
        )
        ctx.event_data["affected_orders"] = [order.order_code for order in affected_orders]
        # Phase 4 integration (SCENARIO D): the dispatch engine reacts inside
        # the same transaction — awaiting/approved orders get reassigned or
        # flagged, in-transit orders are marked delayed. No commit here; the
        # simulation service commits once at the end.
        fleet_service.handle_vehicle_breakdown(ctx.db, vehicle, ctx.changes)
    ctx.affected_entity_type = "vehicle"
    ctx.affected_entity_id = vehicle.id
    if ctx.location_name is None:
        ctx.location_name = vehicle.current_location
    if ctx.latitude is None:
        ctx.latitude = vehicle.current_latitude
    if ctx.longitude is None:
        ctx.longitude = vehicle.current_longitude
    if ctx.title is None:
        ctx.title = f"Vehicle breakdown: {vehicle.vehicle_code}"
    if ctx.description is None:
        ctx.description = (
            f"Simulated breakdown: vehicle '{vehicle.vehicle_code}' taken out of service "
            "for maintenance and is unavailable for dispatch."
        )


def _priority(severity: Severity) -> Priority:
    """Map a severity to the matching priority level."""
    return Priority(severity.value)


_HANDLERS: dict[SimulationEventType, Any] = {
    SimulationEventType.BRIDGE_COLLAPSE: _handle_bridge_collapse,
    SimulationEventType.ROAD_BLOCKED: _handle_road_blocked,
    SimulationEventType.WAREHOUSE_UNAVAILABLE: _handle_warehouse_unavailable,
    SimulationEventType.RELIEF_CENTRE_WATER_SHORTAGE: _handle_relief_centre_water_shortage,
    SimulationEventType.NEW_FLOOD_REPORT: _handle_new_flood_report,
    SimulationEventType.RAINFALL_ESCALATION: _handle_rainfall_escalation,
    SimulationEventType.VEHICLE_BREAKDOWN: _handle_vehicle_breakdown,
}
