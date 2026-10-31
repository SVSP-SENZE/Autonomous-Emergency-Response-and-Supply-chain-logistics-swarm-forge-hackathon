"""Situation-awareness tool handlers (read-only)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.tools.common import operational_flag
from app.models import ReliefCentre
from app.models.enums import IncidentStatus, Priority
from app.services.dashboard_service import get_dashboard_summary
from app.services.incident_service import list_incidents


def _incident_view(incident) -> dict:
    return {
        "id": incident.id,
        "type": incident.incident_type.value,
        "title": incident.title,
        "location": incident.location_name,
        "severity": incident.severity.value,
        "status": incident.status.value,
        "affected_population": incident.affected_population,
        "description": incident.description[:300],
        "reported_at": incident.created_at.isoformat(),
        "source": incident.source.value,
    }


def get_situation_overview(db: Session, _: None) -> dict:
    """Dashboard KPIs + active incidents + critical centres (read-only)."""
    dashboard = get_dashboard_summary(db)
    active_incidents = [
        incident
        for incident in list_incidents(db)
        if incident.status in (IncidentStatus.ACTIVE, IncidentStatus.INVESTIGATING, IncidentStatus.REPORTED)
    ]
    critical_centres = db.scalars(
        select(ReliefCentre).where(ReliefCentre.priority == Priority.CRITICAL).order_by(
            ReliefCentre.affected_population.desc()
        )
    ).all()
    critical = [
        {
            "id": c.id,
            "name": c.name,
            "population": c.affected_population,
            "operational_status": c.operational_status.value,
            "note": operational_flag(c.operational_status),
        }
        for c in critical_centres
    ]
    return {
        "summary": {
            "affected_population": dashboard.summary.affected_population,
            "active_disasters": dashboard.summary.active_disasters,
            "relief_centres": dashboard.summary.relief_centres,
            "critical_centres": dashboard.summary.critical_centres,
            "warehouses": dashboard.summary.warehouses,
            "available_vehicles": dashboard.summary.available_vehicles,
            "vehicles_in_transit": dashboard.summary.vehicles_in_transit,
            "blocked_roads": dashboard.summary.blocked_roads,
        },
        "active_incident_count": len(active_incidents),
        "inventory_totals": [
            {
                "supply_type": item.supply_type.value,
                "total_quantity": item.quantity,
                "unit": item.unit,
            }
            for item in dashboard.inventory
        ],
        "orders_by_status": dashboard.orders_by_status,
        "active_incidents": [_incident_view(incident) for incident in active_incidents],
        "critical_relief_centres": critical,
    }


def list_active_incidents(db: Session, args) -> dict:
    """Active (non-resolved) incidents with optional severity/type filters."""
    from app.models.enums import IncidentStatus, IncidentType, Severity

    incidents = list_incidents(db)
    active = [
        incident
        for incident in incidents
        if incident.status != IncidentStatus.RESOLVED
        and (args.severity is None or incident.severity == Severity(args.severity))
        and (args.incident_type is None or incident.incident_type == IncidentType(args.incident_type))
    ]
    return {
        "count": len(active),
        "incidents": [_incident_view(incident) for incident in active],
    }
