"""Incident service: listing, filtering, creation and updates."""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestError, NotFoundError
from app.models import Incident
from app.models.enums import IncidentSource, IncidentStatus, IncidentType, Severity
from app.schemas.incident import IncidentCreate, IncidentUpdate


def list_incidents(
    db: Session,
    *,
    severity: Severity | None = None,
    status: IncidentStatus | None = None,
    incident_type: IncidentType | None = None,
    source: IncidentSource | None = None,
) -> Iterable[Incident]:
    """List incidents with optional filters, newest first."""
    stmt: Select[tuple[Incident]] = select(Incident)
    if severity is not None:
        stmt = stmt.where(Incident.severity == severity)
    if status is not None:
        stmt = stmt.where(Incident.status == status)
    if incident_type is not None:
        stmt = stmt.where(Incident.incident_type == incident_type)
    if source is not None:
        stmt = stmt.where(Incident.source == source)
    stmt = stmt.order_by(Incident.created_at.desc(), Incident.id.desc())
    return db.scalars(stmt).all()


def get_incident(db: Session, incident_id: int) -> Incident:
    """Fetch one incident or raise a 404-style error."""
    incident = db.get(Incident, incident_id)
    if incident is None:
        raise NotFoundError(f"Incident {incident_id} not found")
    return incident


def create_incident(db: Session, payload: IncidentCreate) -> Incident:
    """Create an operator-submitted incident (not part of the demo dataset)."""
    incident = Incident(
        incident_type=payload.incident_type,
        title=payload.title,
        description=payload.description,
        source=payload.source,
        severity=payload.severity,
        status=payload.status,
        location_name=payload.location_name,
        latitude=payload.latitude,
        longitude=payload.longitude,
        affected_population=payload.affected_population,
        metadata_json=dict(payload.metadata),
        is_demo=False,
    )
    db.add(incident)
    db.commit()
    db.refresh(incident)
    return incident


def update_incident(db: Session, incident_id: int, payload: IncidentUpdate) -> Incident:
    """Apply limited updates (status / severity / description) to an incident."""
    incident = get_incident(db, incident_id)
    changes: dict[str, object] = payload.model_dump(exclude_unset=True, exclude_none=True)
    if not changes:
        raise BadRequestError(
            "No updatable fields provided. Allowed fields: status, severity, description.",
            details={"allowed_fields": ["status", "severity", "description"]},
        )
    for field, value in changes.items():
        setattr(incident, field, value)
    db.commit()
    db.refresh(incident)
    return incident
