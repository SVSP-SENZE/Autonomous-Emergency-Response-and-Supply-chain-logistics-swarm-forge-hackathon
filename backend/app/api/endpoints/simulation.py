"""Simulation endpoints: reset the scenario and apply simulated events."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.common import ListResponse
from app.schemas.simulation import (
    SimulationEventCreate,
    SimulationEventRead,
    SimulationEventResult,
    SimulationResetResponse,
)
from app.services.simulation_service import (
    apply_simulation_event,
    list_simulation_events,
    reset_simulation,
)

router = APIRouter(prefix="/simulation", tags=["simulation"])


@router.post(
    "/reset",
    response_model=SimulationResetResponse,
    summary="Reset the demo scenario to its initial seeded state",
)
def simulation_reset(db: Session = Depends(get_db)) -> SimulationResetResponse:
    """Restore the initial simulated scenario (demo rows only; operator data kept)."""
    return reset_simulation(db)


@router.get(
    "/events",
    response_model=ListResponse[SimulationEventRead],
    summary="Recent simulation events in chronological order",
)
def simulation_events(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> ListResponse[SimulationEventRead]:
    """List recorded simulation events, oldest first."""
    events = list_simulation_events(db, limit=limit)
    items = [SimulationEventRead.model_validate(event) for event in events]
    return ListResponse(items=items, total=len(items))


@router.post(
    "/events",
    response_model=SimulationEventResult,
    status_code=status.HTTP_201_CREATED,
    summary="Apply a simulated event (bridge collapse, road blocked, ...)",
)
def apply_simulation_event_item(
    payload: SimulationEventCreate, db: Session = Depends(get_db)
) -> SimulationEventResult:
    """Validate the event, apply its state change atomically, record it."""
    return apply_simulation_event(db, payload)
