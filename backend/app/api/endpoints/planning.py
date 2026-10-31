"""Planning endpoints (Phase 2): demand, allocation, routing, recalculation."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.models import PlanningRun
from app.models.enums import PlanningType, Priority
from app.schemas.common import ListResponse
from app.schemas.planning import (
    AllocationComputeRequest,
    PlanningRunDetailRead,
    PlanningRunSummaryRead,
    RecalculateRouteRequest,
    RouteBetweenEntitiesRequest,
    RouteComputeRequest,
)
from app.services.demand_service import estimate_demand, validate_horizon
from app.services.routing_service import (
    compute_route_and_persist,
    find_route,
    find_route_between_entities,
    recalculate_route,
)

router = APIRouter(prefix="/planning", tags=["planning"])


# --------------------------------------------------------------------------- #
# Demand estimation
# --------------------------------------------------------------------------- #


@router.get(
    "/demand",
    response_model=None,  # type: ignore[assignment]
    response_model_exclude_none=False,
    summary="Demand assessment for relief centres (configurable horizon)",
)
def get_demand_assessment(
    horizon_hours: int | None = Query(default=None),
    relief_centre_id: int | None = Query(default=None, ge=1),
    priority: Priority | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """Demand estimation (read-only; no planning run persisted)."""
    validate_horizon(horizon_hours)
    return estimate_demand(
        db,
        horizon_hours=horizon_hours,
        relief_centre_id=relief_centre_id,
        priority=priority,
    )


@router.post(
    "/demand/estimate",
    response_model=None,  # type: ignore[assignment]
    status_code=status.HTTP_201_CREATED,
    summary="Explicitly compute and persist a demand assessment snapshot",
)
def post_demand_estimate(
    horizon_hours: int | None = Query(default=None),
    relief_centre_id: int | None = Query(default=None, ge=1),
    priority: Priority | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """Demand estimation with a persisted (auditable) planning run."""
    validate_horizon(horizon_hours)
    return estimate_demand(
        db,
        horizon_hours=horizon_hours,
        relief_centre_id=relief_centre_id,
        priority=priority,
        persist=True,
    )


# --------------------------------------------------------------------------- #
# Allocation planning
# --------------------------------------------------------------------------- #


@router.post(
    "/allocation/compute",
    response_model=None,  # type: ignore[assignment]
    status_code=status.HTTP_201_CREATED,
    summary="Compute a multi-warehouse allocation plan (persisted snapshot)",
)
def post_allocation_compute(
    payload: AllocationComputeRequest | None = None,
    db: Session = Depends(get_db),
):
    """Compute (never mutate stock) and persist a full allocation plan."""
    from app.services.allocation_service import compute_allocation_plan

    return compute_allocation_plan(db, payload)


@router.get(
    "/allocation/latest",
    response_model=None,  # type: ignore[assignment]
    summary="Most recently computed allocation plan (persisted snapshot)",
)
def get_allocation_latest(db: Session = Depends(get_db)):
    """Return the latest persisted allocation plan, or 404 before any run."""
    from app.services.allocation_service import get_latest_allocation_plan

    plan = get_latest_allocation_plan(db)
    if plan is None:
        from app.core.exceptions import NotFoundError

        raise NotFoundError(
            "No allocation plan has been computed yet",
            details={"hint": "POST /api/v1/planning/allocation/compute"},
        )
    return plan


# --------------------------------------------------------------------------- #
# Routing
# --------------------------------------------------------------------------- #


@router.get(
    "/routes",
    response_model=None,  # type: ignore[assignment]
    summary="Optimal route between two road nodes (read-only, not persisted)",
)
def get_route(
    origin_node_id: int = Query(..., ge=1),
    destination_node_id: int = Query(..., ge=1),
    db: Session = Depends(get_db),
):
    """Compute the current optimal route without persisting a planning run."""
    return find_route(db, origin_node_id, destination_node_id)


@router.post(
    "/routes/compute",
    response_model=None,  # type: ignore[assignment]
    status_code=status.HTTP_201_CREATED,
    summary="Compute a route and persist it as the audit baseline",
)
def post_route_compute(
    payload: RouteComputeRequest,
    db: Session = Depends(get_db),
):
    """Compute and persist a route (baseline for later recalculation)."""
    route, run = compute_route_and_persist(db, payload.origin_node_id, payload.destination_node_id)
    response = route.model_dump(mode="json")
    response["planning_run_id"] = run.id
    return response


@router.post(
    "/routes/between-entities",
    response_model=None,  # type: ignore[assignment]
    summary="Route between warehouse/centre/junction entities (not persisted)",
)
def post_route_between_entities(
    payload: RouteBetweenEntitiesRequest,
    db: Session = Depends(get_db),
):
    """Resolve entity road nodes and compute the route between them."""
    return find_route_between_entities(db, payload)


@router.post(
    "/routes/recalculate",
    response_model=None,  # type: ignore[assignment]
    status_code=status.HTTP_201_CREATED,
    summary="Recalculate a route after disruption and compare with history",
)
def post_route_recalculate(
    payload: RecalculateRouteRequest,
    db: Session = Depends(get_db),
):
    """Current route vs. the last persisted route for the same pair."""
    return recalculate_route(db, payload.origin_node_id, payload.destination_node_id)


# --------------------------------------------------------------------------- #
# Planning-run history (Phase 5: audit + plan history pages; read-only)
# --------------------------------------------------------------------------- #


@router.get(
    "/runs",
    response_model=ListResponse[PlanningRunSummaryRead],
    summary="List persisted planning runs, newest first",
)
def list_planning_runs(
    planning_type: PlanningType | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> ListResponse[PlanningRunSummaryRead]:
    """Audit history of demand/allocation/route planning runs."""
    query = select(PlanningRun).order_by(PlanningRun.id.desc())
    if planning_type is not None:
        query = query.where(PlanningRun.planning_type == planning_type)
    runs = db.scalars(query.limit(limit)).all()
    return ListResponse(
        items=[PlanningRunSummaryRead.model_validate(run) for run in runs],
        total=len(runs),
    )


@router.get(
    "/runs/{run_id}",
    response_model=PlanningRunDetailRead,
    summary="One persisted planning run, including its full computation snapshot",
)
def get_planning_run_detail(
    run_id: int,
    db: Session = Depends(get_db),
) -> PlanningRunDetailRead:
    """Historical snapshots are immutable; this returns them verbatim."""
    run = db.get(PlanningRun, run_id)
    if run is None:
        raise NotFoundError(f"Planning run {run_id} not found")
    return PlanningRunDetailRead.model_validate(run)
