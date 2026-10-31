"""Dashboard service: KPI aggregates calculated from live database records."""

from __future__ import annotations

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.models import (
    Incident,
    Inventory,
    ReliefCentre,
    ReliefOrder,
    RoadSegment,
    Vehicle,
    Warehouse,
)
from app.models.enums import IncidentStatus, OrderStatus, Severity, SupplyType, VehicleStatus
from app.schemas.dashboard import DashboardKPIs, DashboardResponse, InventoryAggregate


def get_dashboard_summary(db: Session) -> DashboardResponse:
    """Compute every dashboard figure directly from the database.

    All demo data lives in the database - nothing here is fabricated, and the
    whole scenario is explicitly flagged as SIMULATED.
    """
    summary = _compute_kpis(db)
    inventory = _compute_inventory_totals(db)
    orders_by_status = _compute_orders_by_status(db)
    return DashboardResponse(
        data_mode="SIMULATED",
        summary=summary,
        inventory=inventory,
        orders_by_status=orders_by_status,
        generated_at=utcnow(),
    )


def _compute_kpis(db: Session) -> DashboardKPIs:
    affected_population = (
        db.scalar(select(func.coalesce(func.sum(ReliefCentre.affected_population), 0))) or 0
    )
    return DashboardKPIs(
        affected_population=int(affected_population),
        active_disasters=_count(db, Incident.status == IncidentStatus.ACTIVE),
        relief_centres=_count_all(db, ReliefCentre),
        critical_centres=_count(db, ReliefCentre.priority == Severity.CRITICAL.value),
        warehouses=_count_all(db, Warehouse),
        total_vehicles=_count_all(db, Vehicle),
        available_vehicles=_count(db, Vehicle.status == VehicleStatus.AVAILABLE),
        vehicles_in_transit=_count(db, Vehicle.status == VehicleStatus.IN_TRANSIT),
        blocked_roads=_count(db, RoadSegment.is_blocked.is_(True)),
    )


def _compute_inventory_totals(db: Session) -> list[InventoryAggregate]:
    rows = db.execute(
        select(
            Inventory.supply_type.label("supply_type"),
            func.min(Inventory.unit).label("unit"),
            func.coalesce(func.sum(Inventory.quantity), 0).label("quantity"),
            func.coalesce(func.sum(Inventory.reserved_quantity), 0).label("reserved"),
        )
        .group_by(Inventory.supply_type)
    ).all()
    aggregates: dict[SupplyType, InventoryAggregate] = {}
    for row in rows:
        aggregates[SupplyType(row.supply_type)] = InventoryAggregate(
            supply_type=SupplyType(row.supply_type),
            unit=str(row.unit),
            quantity=int(row.quantity),
            reserved_quantity=int(row.reserved),
            available_quantity=int(row.quantity) - int(row.reserved),
        )
    # Stable, enum-declared ordering for consistent frontend rendering.
    return [aggregates[supply] for supply in SupplyType if supply in aggregates]


def _compute_orders_by_status(db: Session) -> dict[str, int]:
    counts: dict[str, int] = {status.value: 0 for status in OrderStatus}
    rows = db.execute(
        select(ReliefOrder.status, func.count())
        .group_by(ReliefOrder.status)
    ).all()
    for status, count in rows:
        counts[OrderStatus(status).value] = int(count)
    return counts


def _count_all(db: Session, model: type) -> int:
    return int(db.scalar(select(func.count()).select_from(model)) or 0)


def _count(db: Session, condition: object) -> int:
    stmt: Select = select(func.count()).where(condition)
    return int(db.scalar(stmt) or 0)
