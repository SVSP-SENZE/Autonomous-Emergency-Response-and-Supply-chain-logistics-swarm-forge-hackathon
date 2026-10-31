"""Dashboard endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.dashboard import DashboardResponse
from app.services.dashboard_service import get_dashboard_summary

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get(
    "/summary",
    response_model=DashboardResponse,
    summary="Aggregated disaster-response KPIs (all values computed from the DB)",
)
def dashboard_summary(db: Session = Depends(get_db)) -> DashboardResponse:
    """One-shot dashboard payload: KPIs, inventory totals and orders by status."""
    return get_dashboard_summary(db)
