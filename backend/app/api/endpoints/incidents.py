"""Incident endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.enums import IncidentSource, IncidentStatus, IncidentType, Severity
from app.schemas.common import ListResponse
from app.schemas.incident import IncidentCreate, IncidentRead, IncidentUpdate
from app.services.incident_service import (
    create_incident,
    get_incident,
    list_incidents,
    update_incident,
)

router = APIRouter(prefix="/incidents", tags=["incidents"])


@router.get(
    "",
    response_model=ListResponse[IncidentRead],
    summary="List incidents with optional filters",
)
def list_incident_items(
    severity: Severity | None = Query(default=None),
    status_filter: IncidentStatus | None = Query(default=None, alias="status"),
    incident_type: IncidentType | None = Query(default=None),
    source: IncidentSource | None = Query(default=None),
    db: Session = Depends(get_db),
) -> ListResponse[IncidentRead]:
    """List incidents, optionally filtered by severity / status / type / source."""
    incidents = list_incidents(
        db,
        severity=severity,
        status=status_filter,
        incident_type=incident_type,
        source=source,
    )
    items = [IncidentRead.model_validate(incident) for incident in incidents]
    return ListResponse(items=items, total=len(items))


@router.get(
    "/{incident_id}",
    response_model=IncidentRead,
    summary="Get one incident by id",
)
def get_incident_item(
    incident_id: int, db: Session = Depends(get_db)
) -> IncidentRead:
    """Fetch a single incident."""
    return IncidentRead.model_validate(get_incident(db, incident_id))


@router.post(
    "",
    response_model=IncidentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create an incident (operator / citizen report)",
)
def create_incident_item(
    payload: IncidentCreate, db: Session = Depends(get_db)
) -> IncidentRead:
    """Create a new incident record."""
    return IncidentRead.model_validate(create_incident(db, payload))


@router.patch(
    "/{incident_id}",
    response_model=IncidentRead,
    summary="Update incident status / severity / description",
)
def update_incident_item(
    incident_id: int, payload: IncidentUpdate, db: Session = Depends(get_db)
) -> IncidentRead:
    """Apply a partial update to an incident."""
    return IncidentRead.model_validate(update_incident(db, incident_id, payload))
