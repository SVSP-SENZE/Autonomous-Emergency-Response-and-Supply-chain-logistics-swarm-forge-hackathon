"""Seed service: deterministic demo scenario + idempotent database seeding.

The demo dataset (Thanjavur district flood simulation) is defined in
`seed_data.py`. Seeding is idempotent: every step looks records up by a
natural key (name / code / title) and only creates what is missing, so
running the seed again never duplicates data.

`reset_demo_data()` deletes only demo-tagged rows (`is_demo=True`) and
re-seeds the initial scenario, preserving operator-created data.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.models import (
    Incident,
    Inventory,
    ReliefCentre,
    ReliefCentreInventory,
    ReliefOrder,
    ReliefOrderItem,
    RoadNode,
    RoadSegment,
    SimulationEvent,
    Vehicle,
    Warehouse,
)
from app.services.seed_data import (
    BLOCKED_SEGMENT_KEY,
    INCIDENTS,
    INVENTORY,
    RELIEF_CENTRE_INVENTORY,
    RELIEF_CENTRES,
    RELIEF_ORDERS,
    ROAD_NODES,
    ROAD_SEGMENTS,
    SIMULATION_EVENTS,
    VEHICLES,
    WAREHOUSES,
)

logger = logging.getLogger("reliefmesh.seed")


# --------------------------------------------------------------------------- #
# Seeding
# --------------------------------------------------------------------------- #


def seed_demo(db: Session) -> dict[str, int]:
    """Idempotently ensure the full demo scenario exists; commit and return counts."""
    _seed_demo_data(db)
    db.commit()
    counts = get_scenario_counts(db)
    logger.info("Demo scenario seeded: %s", counts)
    return counts


def reset_demo_data(db: Session) -> dict[str, int]:
    """Restore the initial seeded scenario.

    Deletes only rows tagged `is_demo=True` (warehouse-managed demo data,
    simulation events and simulation-created incidents) and re-seeds. All
    deletions and re-seeding happen in one transaction: on failure the
    database state is rolled back untouched.
    """
    try:
        _delete_demo_data(db)
        _seed_demo_data(db)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Simulation reset failed; database state restored")
        raise
    counts = get_scenario_counts(db)
    logger.info("Demo scenario reset to initial state: %s", counts)
    return counts


def get_scenario_counts(db: Session) -> dict[str, int]:
    """Record counts for the demo scenario (`is_demo=True`)."""
    demo_warehouse_ids = select(Warehouse.id).where(Warehouse.is_demo.is_(True))
    counts: dict[str, int] = {
        "warehouses": _count(db, Warehouse),
        "relief_centres": _count(db, ReliefCentre),
        "vehicles": _count(db, Vehicle),
        "incidents": _count(db, Incident),
        "road_nodes": _count(db, RoadNode),
        "road_segments": _count(db, RoadSegment),
        "relief_orders": _count(db, ReliefOrder),
        "simulation_events": _count(db, SimulationEvent),
        "relief_centre_inventory_items": db.scalar(
            select(func.count())
            .select_from(ReliefCentreInventory)
            .where(ReliefCentreInventory.relief_centre_id.in_(
                select(ReliefCentre.id).where(ReliefCentre.is_demo.is_(True))
            ))
        )
        or 0,
        "inventory_items": db.scalar(
            select(func.count())
            .select_from(Inventory)
            .where(Inventory.warehouse_id.in_(demo_warehouse_ids))
        )
        or 0,
    }
    return counts


def _count(db: Session, model: type) -> int:
    return db.scalar(
        select(func.count()).select_from(model).where(model.is_demo.is_(True))
    ) or 0


def _delete_demo_data(db: Session) -> None:
    """Delete every `is_demo=True` row in FK-safe order (uncommitted)."""
    demo_order_ids = select(ReliefOrder.id).where(ReliefOrder.is_demo.is_(True))
    db.execute(delete(ReliefOrderItem).where(ReliefOrderItem.relief_order_id.in_(demo_order_ids)))
    db.execute(delete(ReliefOrder).where(ReliefOrder.is_demo.is_(True)))
    db.execute(delete(SimulationEvent).where(SimulationEvent.is_demo.is_(True)))
    db.execute(delete(Incident).where(Incident.is_demo.is_(True)))
    db.execute(delete(Vehicle).where(Vehicle.is_demo.is_(True)))
    db.execute(delete(RoadSegment).where(RoadSegment.is_demo.is_(True)))
    db.execute(delete(RoadNode).where(RoadNode.is_demo.is_(True)))
    # Inventory inherits demo state from its warehouse; centre stock follows
    # the demo relief centres.
    demo_centre_ids = select(ReliefCentre.id).where(ReliefCentre.is_demo.is_(True))
    demo_warehouse_ids = select(Warehouse.id).where(Warehouse.is_demo.is_(True))
    db.execute(delete(Inventory).where(Inventory.warehouse_id.in_(demo_warehouse_ids)))
    db.execute(delete(ReliefCentreInventory).where(
        ReliefCentreInventory.relief_centre_id.in_(demo_centre_ids)
    ))
    db.execute(delete(Warehouse).where(Warehouse.is_demo.is_(True)))
    db.execute(delete(ReliefCentre).where(ReliefCentre.is_demo.is_(True)))
    db.flush()


def _seed_demo_data(db: Session) -> None:
    now = utcnow()

    warehouse_by_name = _seed_warehouses(db)
    centre_by_name = _seed_relief_centres(db)
    _seed_inventory(db, warehouse_by_name)
    _seed_relief_centre_inventory(db, centre_by_name)
    _seed_vehicles(db, warehouse_by_name)
    node_by_name = _seed_road_nodes(db, warehouse_by_name, centre_by_name)
    segment_by_node_pair = _seed_road_segments(db, node_by_name)
    incident_by_title = _seed_incidents(db, now)
    _seed_relief_orders(db, now, warehouse_by_name, centre_by_name)
    _seed_simulation_events(
        db, now, incident_by_title, centre_by_name, segment_by_node_pair
    )
    db.flush()


def _seed_warehouses(db: Session) -> dict[str, Warehouse]:
    warehouses: dict[str, Warehouse] = {}
    for spec in WAREHOUSES:
        existing = db.scalar(select(Warehouse).where(Warehouse.name == spec["name"]))
        if existing is None:
            # Created fresh (including *unknown* attribute warnings avoided by
            # constructing explicitly below).
            existing = Warehouse(
                name=spec["name"],
                location_name=spec["location_name"],
                latitude=spec["latitude"],
                longitude=spec["longitude"],
                operational_status=spec["operational_status"],
                storage_capacity=spec["storage_capacity"],
                is_demo=True,
            )
            db.add(existing)
            db.flush()
        warehouses[spec["name"]] = existing
    return warehouses


def _seed_relief_centres(db: Session) -> dict[str, ReliefCentre]:
    centres: dict[str, ReliefCentre] = {}
    for spec in RELIEF_CENTRES:
        existing = db.scalar(select(ReliefCentre).where(ReliefCentre.name == spec["name"]))
        if existing is None:
            existing = ReliefCentre(**spec, is_demo=True)
            db.add(existing)
            db.flush()
        centres[spec["name"]] = existing
    return centres


def _seed_inventory(db: Session, warehouse_by_name: dict[str, Warehouse]) -> None:
    for warehouse_name, supplies in INVENTORY.items():
        warehouse = warehouse_by_name[warehouse_name]
        for supply in supplies:
            existing = db.scalar(
                select(Inventory).where(
                    Inventory.warehouse_id == warehouse.id,
                    Inventory.supply_type == supply["supply_type"],
                )
            )
            if existing is None:
                db.add(Inventory(warehouse_id=warehouse.id, **supply))


def _seed_relief_centre_inventory(
    db: Session, centre_by_name: dict[str, ReliefCentre]
) -> None:
    """Idempotently seed stock held at each relief centre."""
    for centre_name, supplies in RELIEF_CENTRE_INVENTORY.items():
        centre = centre_by_name[centre_name]
        for supply in supplies:
            existing = db.scalar(
                select(ReliefCentreInventory).where(
                    ReliefCentreInventory.relief_centre_id == centre.id,
                    ReliefCentreInventory.supply_type == supply["supply_type"],
                )
            )
            if existing is None:
                db.add(
                    ReliefCentreInventory(
                        relief_centre_id=centre.id,
                        supply_type=supply["supply_type"],
                        quantity=supply["quantity"],
                        unit=supply["unit"],
                    )
                )


def _seed_vehicles(db: Session, warehouse_by_name: dict[str, Warehouse]) -> None:
    for spec in VEHICLES:
        existing = db.scalar(select(Vehicle).where(Vehicle.vehicle_code == spec["vehicle_code"]))
        if existing is None:
            warehouse_name = spec["warehouse"]
            db.add(
                Vehicle(
                    vehicle_code=spec["vehicle_code"],
                    vehicle_type=spec["vehicle_type"],
                    capacity=spec["capacity"],
                    # The demo fleet's capacity was always denominated in kg;
                    # Phase 4 makes it explicit for the fleet engine.
                    capacity_kg=spec["capacity"],
                    current_location=spec["current_location"],
                    current_latitude=spec["current_latitude"],
                    current_longitude=spec["current_longitude"],
                    status=spec["status"],
                    warehouse_id=(
                        warehouse_by_name[warehouse_name].id if warehouse_name else None
                    ),
                    is_demo=True,
                )
            )
        elif existing.capacity_kg is None:
            # Backfill pre-Phase-4 demo rows (documented kg interpretation).
            existing.capacity_kg = existing.capacity


def _seed_road_nodes(
    db: Session,
    warehouse_by_name: dict[str, Warehouse],
    centre_by_name: dict[str, ReliefCentre],
) -> dict[str, RoadNode]:
    nodes: dict[str, RoadNode] = {}
    for spec in ROAD_NODES:
        existing = db.scalar(select(RoadNode).where(RoadNode.node_name == spec["node_name"]))
        if existing is None:
            linked_entity_id: int | None = None
            linked = spec["linked"]
            if linked is not None:
                entity_kind, entity_name = linked
                if entity_kind == "warehouse":
                    linked_entity_id = warehouse_by_name[entity_name].id
                elif entity_kind == "relief_centre":
                    linked_entity_id = centre_by_name[entity_name].id
            existing = RoadNode(
                node_name=spec["node_name"],
                node_type=spec["node_type"],
                latitude=spec["latitude"],
                longitude=spec["longitude"],
                linked_entity_id=linked_entity_id,
                is_demo=True,
            )
            db.add(existing)
            db.flush()
        nodes[spec["node_name"]] = existing
    return nodes


def _seed_road_segments(
    db: Session, node_by_name: dict[str, RoadNode]
) -> dict[tuple[str, str], RoadSegment]:
    segments: dict[tuple[str, str], RoadSegment] = {}
    for spec in ROAD_SEGMENTS:
        from_node = node_by_name[spec["from_node"]]
        to_node = node_by_name[spec["to_node"]]
        key = (spec["from_node"], spec["to_node"])
        existing = db.scalar(
            select(RoadSegment).where(
                RoadSegment.from_node_id == from_node.id,
                RoadSegment.to_node_id == to_node.id,
            )
        )
        if existing is None:
            existing = RoadSegment(
                from_node_id=from_node.id,
                to_node_id=to_node.id,
                distance_km=spec["distance_km"],
                estimated_travel_time_minutes=spec["estimated_travel_time_minutes"],
                risk_factor=spec["risk_factor"],
                is_blocked=spec["is_blocked"],
                blockage_reason=spec["blockage_reason"],
                is_demo=True,
            )
            db.add(existing)
            db.flush()
        segments[key] = existing
    return segments


def _seed_incidents(db: Session, now: Any) -> dict[str, Incident]:
    incidents: dict[str, Incident] = {}
    for spec in INCIDENTS:
        existing = db.scalar(
            select(Incident).where(
                Incident.title == spec["title"], Incident.is_demo.is_(True)
            )
        )
        if existing is None:
            existing = Incident(
                incident_type=spec["incident_type"],
                title=spec["title"],
                description=spec["description"],
                source=spec["source"],
                severity=spec["severity"],
                status=spec["status"],
                location_name=spec["location_name"],
                latitude=spec["latitude"],
                longitude=spec["longitude"],
                affected_population=spec["affected_population"],
                metadata_json=dict(spec["metadata"]),
                is_demo=True,
                created_at=now - timedelta(hours=spec["hours_ago"]),
            )
            db.add(existing)
            db.flush()
        incidents[spec["title"]] = existing
    return incidents


def _seed_relief_orders(
    db: Session,
    now: Any,
    warehouse_by_name: dict[str, Warehouse],
    centre_by_name: dict[str, ReliefCentre],
) -> None:
    from app.core.dispatch_config import dispatch_settings

    for spec in RELIEF_ORDERS:
        existing = db.scalar(
            select(ReliefOrder).where(ReliefOrder.order_code == spec["order_code"])
        )
        if existing is not None:
            continue
        vehicle_id: int | None = None
        if spec["vehicle"] is not None:
            vehicle_id = (
                db.scalar(select(Vehicle.id).where(Vehicle.vehicle_code == spec["vehicle"]))
            )
        item_specs = list(spec["items"])
        total_cargo = sum(
            item["quantity"] * dispatch_settings.weight_for(item["supply_type"].value)
            for item in item_specs
        )
        order = ReliefOrder(
            order_code=spec["order_code"],
            warehouse_id=warehouse_by_name[spec["warehouse"]].id,
            relief_centre_id=centre_by_name[spec["relief_centre"]].id,
            vehicle_id=vehicle_id,
            status=spec["status"],
            priority=spec["priority"],
            estimated_travel_time_minutes=spec["estimated_travel_time_minutes"],
            total_cargo_weight_kg=round(total_cargo, 2),
            route_metadata=dict(spec["route_metadata"]),
            is_demo=True,
            created_at=now - timedelta(hours=spec["hours_ago"]),
        )
        db.add(order)
        db.flush()
        for item_spec in item_specs:
            db.add(
                ReliefOrderItem(
                    relief_order_id=order.id,
                    supply_type=item_spec["supply_type"],
                    quantity=item_spec["quantity"],
                    unit=item_spec["unit"],
                    estimated_weight_kg=round(
                        item_spec["quantity"]
                        * dispatch_settings.weight_for(item_spec["supply_type"].value),
                        2,
                    ),
                )
            )


def _seed_simulation_events(
    db: Session,
    now: Any,
    incident_by_title: dict[str, Incident],
    centre_by_name: dict[str, ReliefCentre],
    segment_by_node_pair: dict[tuple[str, str], RoadSegment],
) -> None:
    for spec in SIMULATION_EVENTS:
        existing = db.scalar(
            select(SimulationEvent).where(
                SimulationEvent.title == spec["title"], SimulationEvent.is_demo.is_(True)
            )
        )
        if existing is not None:
            continue
        entity_type: str | None = None
        entity_id: int | None = None
        target = spec["target"]
        if target is not None:
            entity_kind, entity_key = target
            if entity_kind == "incident":
                entity = incident_by_title[entity_key]
                entity_type, entity_id = "incident", entity.id
            elif entity_kind == "relief_centre":
                entity = centre_by_name[entity_key]
                entity_type, entity_id = "relief_centre", entity.id
            elif entity_kind == "road_segment":
                from_name, to_name = BLOCKED_SEGMENT_KEY
                if "|" in entity_key:
                    from_name, to_name = entity_key.split("|", 1)
                entity = segment_by_node_pair[(from_name, to_name)]
                entity_type, entity_id = "road_segment", entity.id
            else:  # pragma: no cover - guarded by seed data review
                raise ValueError(f"Unknown simulation event target kind: {entity_kind}")
        db.add(
            SimulationEvent(
                event_type=spec["event_type"],
                title=spec["title"],
                description=spec["description"],
                location_name=spec["location_name"],
                latitude=spec["latitude"],
                longitude=spec["longitude"],
                affected_entity_type=entity_type,
                affected_entity_id=entity_id,
                severity=spec["severity"],
                event_data=dict(spec["event_data"]),
                is_demo=True,
                created_at=now - timedelta(hours=spec["hours_ago"]),
            )
        )


