"""Relief centre endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.models import ReliefCentre
from app.models.enums import OperationalStatus, Priority
from app.schemas.common import ListResponse
from app.schemas.relief_centre import (
    ReliefCentreDetail,
    ReliefCentreInventoryLine,
    ReliefCentreSummary,
)

router = APIRouter(prefix="/relief-centres", tags=["relief-centres"])


@router.get(
    "",
    response_model=ListResponse[ReliefCentreSummary],
    summary="List relief centres with optional filters",
)
def list_relief_centre_items(
    priority: Priority | None = Query(default=None),
    operational_status: OperationalStatus | None = Query(default=None),
    water_shortage: bool | None = Query(default=None),
    db: Session = Depends(get_db),
) -> ListResponse[ReliefCentreSummary]:
    """List relief centres, optionally filtered by priority / status."""
    stmt = select(ReliefCentre)
    if priority is not None:
        stmt = stmt.where(ReliefCentre.priority == priority)
    if operational_status is not None:
        stmt = stmt.where(ReliefCentre.operational_status == operational_status)
    if water_shortage is not None:
        stmt = stmt.where(ReliefCentre.water_shortage.is_(water_shortage))
    centres = db.scalars(stmt.order_by(ReliefCentre.id)).all()
    items = [ReliefCentreSummary.model_validate(centre) for centre in centres]
    return ListResponse(items=items, total=len(items))


@router.get(
    "/{centre_id}",
    response_model=ReliefCentreDetail,
    summary="Get one relief centre (population, location + stock detail)",
)
def get_relief_centre_item(centre_id: int, db: Session = Depends(get_db)) -> ReliefCentreDetail:
    """Fetch a single relief centre including its held supply stock."""
    centre = db.get(ReliefCentre, centre_id)
    if centre is None:
        raise NotFoundError(f"Relief centre {centre_id} not found")
    detail = ReliefCentreDetail.model_validate(centre)
    # supply_type is a StrEnum column; expose its value for the API.
    detail.inventory = sorted(
        (
            ReliefCentreInventoryLine(
                supply_type=row.supply_type.value,
                quantity=row.quantity,
                unit=row.unit,
                updated_at=row.updated_at,
            )
            for row in centre.inventory_of_centre
        ),
        key=lambda row: row.supply_type,
    )
    return detail
