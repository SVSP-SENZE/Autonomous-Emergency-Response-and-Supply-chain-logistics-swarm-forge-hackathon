"""AI tool helpers: name resolution, compact serialisation of ORM rows."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.exceptions import NotFoundError
from app.models import ReliefCentre, RoadNode, Warehouse
from app.models.enums import NodeType, OperationalStatus, SupplyType

_SUPPLY_ORDER = {supply.value: index for index, supply in enumerate(SupplyType)}


def resolve_relief_centre(db: Session, name: str) -> ReliefCentre:
    """Resolve a relief centre by (case-insensitive) name, substring fallback."""
    query = name.strip()
    if not query:
        raise NotFoundError("Empty relief centre name")
    centres = list(db.scalars(select(ReliefCentre)).all())
    for centre in centres:
        if centre.name.lower() == query.lower():
            return centre
    matches = [c for c in centres if query.lower() in c.name.lower()]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise NotFoundError(
            f"Ambiguous relief centre name: {name!r}",
            details={"matches": [c.name for c in matches]},
        )
    raise NotFoundError(
        f"No relief centre matches {name!r}",
        details={"known_centres": [c.name for c in centres]},
    )


def resolve_warehouse(db: Session, name: str) -> Warehouse:
    """Resolve a warehouse by (case-insensitive) name, substring fallback."""
    query = name.strip()
    if not query:
        raise NotFoundError("Empty warehouse name")
    warehouses = list(db.scalars(select(Warehouse)).all())
    for warehouse in warehouses:
        if warehouse.name.lower() == query.lower():
            return warehouse
    matches = [w for w in warehouses if query.lower() in w.name.lower()]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise NotFoundError(
            f"Ambiguous warehouse name: {name!r}",
            details={"matches": [w.name for w in matches]},
        )
    raise NotFoundError(
        f"No warehouse matches {name!r}",
        details={"known_warehouses": [w.name for w in warehouses]},
    )


def resolve_endpoint_node(db: Session, name: str) -> tuple[RoadNode, str]:
    """Resolve an origin/destination name to a road node.

    Tries warehouses, then relief centres, then road-node names (junctions).
    Returns (node, entity_description).
    """
    try:
        warehouse = resolve_warehouse(db, name)
    except NotFoundError:
        warehouse = None
    if warehouse is not None:
        node = db.scalar(
            select(RoadNode).where(
                RoadNode.node_type == NodeType.WAREHOUSE,
                RoadNode.linked_entity_id == warehouse.id,
            )
        )
        if node is not None:
            return node, f"warehouse '{warehouse.name}'"
    try:
        centre = resolve_relief_centre(db, name)
    except NotFoundError:
        centre = None
    if centre is not None:
        node = db.scalar(
            select(RoadNode).where(
                RoadNode.node_type == NodeType.RELIEF_CENTRE,
                RoadNode.linked_entity_id == centre.id,
            )
        )
        if node is not None:
            return node, f"relief centre '{centre.name}'"
    node = db.scalar(select(RoadNode).where(RoadNode.node_name.ilike(name.strip())))
    if node is not None:
        return node, f"road node '{node.node_name}'"
    raise NotFoundError(
        f"No warehouse, relief centre or road node matches {name!r}"
    )


def compact_centre(row) -> dict:
    """Compact per-centre demand view (token friendly, units preserved)."""
    items: dict[str, dict[str, float]] = {}
    for item in row.items:
        items[item.supply_type.value] = {
            "required": item.required_quantity,
            "current_stock": item.current_stock,
            "shortage": item.shortage_quantity,
            "unit": item.unit,
        }
    return {
        "relief_centre": row.name,
        "population": row.affected_population,
        "priority_score": row.priority_score,
        "classification": row.priority_classification,
        "allocation_eligible": row.allocation_eligible,
        "operational_status": row.operational_status.value,
        "items": items,
    }


def compact_allocation_centre(centre) -> dict:
    """Compact per-centre allocation plan view."""
    lines: list[dict] = []
    for line in centre.lines:
        lines.append(
            {
                "supply_type": line.supply_type.value,
                "shortage": line.shortage_quantity,
                "allocated": line.allocated_quantity,
                "unfulfilled": line.unfulfilled_quantity,
                "sources": [
                    {"warehouse": s.warehouse_name, "quantity": s.quantity}
                    for s in line.sources
                ],
            }
        )
    return {
        "relief_centre": centre.name,
        "priority_score": centre.priority_score,
        "lines": lines,
    }


def operational_flag(status: OperationalStatus) -> str | None:
    """Warning suffix for centres/warehouses that cannot be served/moved."""
    if status == OperationalStatus.UNAVAILABLE:
        return "NOT dispatchable (unavailable)"
    if status == OperationalStatus.DEGRADED:
        return "degraded operations"
    return None


def warehouses_with_inventory(db: Session):
    return db.scalars(
        select(Warehouse).options(selectinload(Warehouse.inventory)).order_by(Warehouse.id)
    ).all()
