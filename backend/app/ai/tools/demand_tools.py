"""Demand/priority tool handlers (read-only; reuse the Phase 2 services)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.ai.tools.common import compact_centre, resolve_relief_centre
from app.services.demand_service import estimate_demand

_ALGORITHM_NOTE = (
    "Priority score = 0.40*centre_priority + 0.35*max_shortage_pct "
    "+ 0.15*population(normalised) + 0.10*stock-coverage risk; classification "
    "thresholds: >=85 Critical, 65-84 High, 40-64 Medium, <40 Low."
)


def get_demand_assessment(db: Session, args) -> dict:
    """Phase-2 demand estimation, optionally scoped to one centre."""
    centres: list = []
    if args.relief_centre_name:
        centre = resolve_relief_centre(db, args.relief_centre_name)
        assessment = estimate_demand(
            db, horizon_hours=args.horizon_hours, relief_centre_id=centre.id
        )
        centres = assessment.centres
    else:
        assessment = estimate_demand(db, horizon_hours=args.horizon_hours)
        centres = assessment.centres
    return {
        "horizon_hours": assessment.horizon_hours,
        "centres_assessed": len(centres),
        "centres": [compact_centre(row) for row in centres],
        "totals": {
            supply: value
            for supply, value in assessment.summary.total_shortage_by_supply.items()
        },
        "algorithm": _ALGORITHM_NOTE,
        "note": "Figures come from the SIMULATED scenario database.",
    }


def explain_relief_centre_priority(db: Session, args) -> dict:
    """Factual factors behind a centre's computed priority."""
    centre = resolve_relief_centre(db, args.relief_centre_name)
    assessment = estimate_demand(
        db, horizon_hours=24, relief_centre_id=centre.id
    )
    plan = assessment.centres[0]
    population_component = 100.0 if centre.affected_population > 0 else 0.0
    return {
        "relief_centre": plan.name,
        "district": plan.district,
        "population": plan.affected_population,
        "operational_status": plan.operational_status.value,
        "stored_priority": plan.centre_priority.value,
        "allocation_eligible": plan.allocation_eligible,
        "priority_score": plan.priority_score,
        "classification": plan.priority_classification,
        "factors": {
            "population_component_max_is_100": population_component,
            "algorithm": _ALGORITHM_NOTE,
            "shortages": {
                item.supply_type.value: {
                    "required": item.required_quantity,
                    "current_stock": item.current_stock,
                    "shortage": item.shortage_quantity,
                    "shortage_percentage": item.shortage_percentage,
                    "unit": item.unit,
                }
                for item in plan.items
            },
            "max_shortage_percentage": plan.max_shortage_percentage,
        },
        "note": (
            "Calculated by the deterministic Phase-2 engine on the SIMULATED "
            "database; no weighting outside the algorithm is applied."
        ),
    }
