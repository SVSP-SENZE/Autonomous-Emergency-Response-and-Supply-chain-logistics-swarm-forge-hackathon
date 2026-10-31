"""Allocation planning tool handlers (PLANNING category; Phase-2 engine)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.ai.tools.common import compact_allocation_centre
from app.services.allocation_service import compute_allocation_plan, get_latest_allocation_plan

_PLANNING_NOTE = (
    "Proposed plan only: computed by the deterministic Phase-2 allocator and "
    "persisted as an auditable planning snapshot. No inventory has been "
    "reserved or deducted; dispatch requires explicit operator approval."
)


def compute_resource_allocation(db: Session, args) -> dict:
    """Run the real multi-warehouse allocator (persists a PlanningRun)."""
    from app.schemas.planning import AllocationComputeRequest

    plan = compute_allocation_plan(db, AllocationComputeRequest(horizon_hours=args.horizon_hours))
    return {
        "planning_run_id": plan.planning_run_id,
        "horizon_hours": plan.horizon_hours,
        "fulfilment_pct": plan.summary.fulfilment_percentage,
        "summary": {
            "required_by_supply": plan.summary.required_by_supply,
            "allocated_by_supply": plan.summary.allocated_by_supply,
            "unfulfilled_by_supply": plan.summary.unfulfilled_by_supply,
            "fulfilment_percentage": plan.summary.fulfilment_percentage,
            "centres_served": plan.summary.centres_served,
            "centres_with_unmet_demand": plan.summary.centres_with_unmet_demand,
        },
        "centres": [compact_allocation_centre(centre) for centre in plan.centres],
        "excluded_centres": [
            {"relief_centre": c.name, "reason": c.reason} for c in plan.excluded_centres
        ],
        "remaining_warehouse_stock": [
            {
                "warehouse": util.warehouse_name,
                "remaining_by_supply": util.remaining_by_supply,
            }
            for util in plan.summary.warehouse_utilisation
        ],
        "note": _PLANNING_NOTE,
    }


def latest_allocation_plan(db: Session, _: None) -> dict:
    """Fetch the newest persisted plan snapshot inspection-safe."""
    plan = get_latest_allocation_plan(db)
    if plan is None:
        return {
            "exists": False,
            "message": "No allocation plan has been computed yet.",
            "hint": "Ask to compute one via compute_resource_allocation.",
        }
    return {
        "exists": True,
        "planning_run_id": plan.planning_run_id,
        "horizon_hours": plan.horizon_hours,
        "summary": {
            "allocated_by_supply": plan.summary.allocated_by_supply,
            "unfulfilled_by_supply": plan.summary.unfulfilled_by_supply,
            "fulfilment_percentage": plan.summary.fulfilment_percentage,
        },
        "centres": [compact_allocation_centre(centre) for centre in plan.centres],
        "note": _PLANNING_NOTE,
    }
