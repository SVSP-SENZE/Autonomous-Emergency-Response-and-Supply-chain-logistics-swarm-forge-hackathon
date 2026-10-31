"""Demand estimation service: deterministic intake-requirement engine.

Calculation (per relief centre, per supply type):

    required = population * daily_rate * (planning_hours / 24)
    shortage = max(required - current_stock, 0)
    surplus  = max(current_stock - required, 0)
    shortage_% = shortage / required * 100        (0 if required == 0)

Kit quantities are rounded up to whole kits (math.ceil); water keeps numeric
precision (2 decimals). Rates, weights and classification thresholds come from
`app/core/planning_config.py` — the single configuration module.

The priority score is a deterministic weighted composite on a 0-100 scale:

    score = w_priority * centre_priority_component            (0-100 mapped)
          + w_shortage * max shortage % across supply types
          + w_population * normalised affected population
          + w_supply_risk * mean unmet-coverage risk across supply types

Classification: >=85 Critical, 65-84 High, 40-64 Medium, <40 Low.
"""

from __future__ import annotations

import logging
import math

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.clock import utcnow
from app.core.planning_config import (
    ALLOWED_HORIZONS,
    DEFAULT_HORIZON,
    PRIORITY_CLASSIFICATION_THRESHOLDS,
    PRIORITY_SCORE_MAP,
    SUPPLY_UNIT,
    planning_settings,
)
from app.core.exceptions import BadRequestError, NotFoundError
from app.models import PlanningRun, ReliefCentre
from app.models.enums import OperationalStatus, PlanningStatus, PlanningType, Priority, SupplyType
from app.schemas.planning import (
    DemandAssessmentResponse,
    DemandAssumptions,
    DemandCentreRead,
    DemandItem,
    DemandSummary,
)

logger = logging.getLogger("reliefmesh.planning.demand")


def validate_horizon(horizon_hours: int | None) -> int:
    """Validate the planning horizon (hours) against the allowed set."""
    horizon = DEFAULT_HORIZON if horizon_hours is None else horizon_hours
    if horizon not in ALLOWED_HORIZONS:
        raise BadRequestError(
            f"Unsupported planning horizon: {horizon}h. Allowed: {ALLOWED_HORIZONS}",
            details={"allowed_horizons": list(ALLOWED_HORIZONS)},
        )
    return horizon


def get_demand_assumptions() -> DemandAssumptions:
    """Expose the active assumptions for the given horizon (audit trail)."""
    planning_settings.validate_weights()
    return DemandAssumptions(
        planning_horizon_hours=DEFAULT_HORIZON,
        consumption_rates_per_person_per_day=planning_settings.consumption_rates,
        priority_component_weight=planning_settings.priority_component_weight,
        shortage_component_weight=planning_settings.shortage_component_weight,
        population_component_weight=planning_settings.population_component_weight,
        supply_risk_component_weight=planning_settings.supply_risk_component_weight,
    )


def _required_quantity(supply_type: SupplyType, population: int, horizon_hours: int) -> float:
    """Daily-rate formula. Kits: ceil to whole units; water: 2-decimal precision."""
    exact = population * planning_settings.consumption_rates[supply_type.value] * (
        horizon_hours / 24.0
    )
    if supply_type == SupplyType.WATER_LITRE:
        return round(exact, 2)
    return float(math.ceil(exact))


def estimate_demand(
    db: Session,
    horizon_hours: int | None = None,
    relief_centre_id: int | None = None,
    priority: Priority | None = None,
    persist: bool = False,
) -> DemandAssessmentResponse:
    """Compute the demand assessment for all (or one) relief centre(s).

    Deterministic: identical database state + horizon always yields the same
    result. `persist` stores the response as a `PlanningRun` snapshot.
    """
    horizon = validate_horizon(horizon_hours)
    planning_settings.validate_weights()

    stmt = (
        select(ReliefCentre)
        .options(selectinload(ReliefCentre.inventory_of_centre))
    )
    if relief_centre_id is not None:
        stmt = stmt.where(ReliefCentre.id == relief_centre_id)
    if priority is not None:
        stmt = stmt.where(ReliefCentre.priority == priority)
    centres = db.scalars(stmt.order_by(ReliefCentre.id)).all()
    if relief_centre_id is not None and not centres:
        raise NotFoundError(f"Relief centre {relief_centre_id} not found")

    max_population = max(
        (centre.affected_population for centre in centres), default=0
    )
    population_denominator = max_population if max_population > 0 else 1

    centre_plans: list[DemandCentreRead] = []
    total_required: dict[str, float] = {}
    total_shortage: dict[str, float] = {}
    total_stock: dict[str, float] = {}

    for centre in centres:
        stock_by_supply: dict[SupplyType, float] = {
            item.supply_type: float(item.quantity) for item in centre.inventory_of_centre
        }
        items: list[DemandItem] = []
        coverage_risks: list[float] = []

        for supply_type in SupplyType:
            required = _required_quantity(supply_type, centre.affected_population, horizon)
            stock = stock_by_supply.get(supply_type, 0.0)
            shortage = max(required - stock, 0.0)
            surplus = max(stock - required, 0.0)
            shortage_pct = (shortage / required * 100.0) if required > 0 else 0.0
            # Coverage risk: share of requirement not covering existing stock.
            coverage = (stock / required) if required > 0 else 1.0
            coverage_risks.append(1.0 - min(coverage, 1.0))
            items.append(
                DemandItem(
                    supply_type=supply_type,
                    unit=SUPPLY_UNIT[supply_type.value],
                    required_quantity=required,
                    current_stock=stock,
                    shortage_quantity=round(shortage, 2),
                    surplus_quantity=round(surplus, 2),
                    shortage_percentage=round(shortage_pct, 2),
                )
            )
            total_required[supply_type.value] = (
                total_required.get(supply_type.value, 0.0) + required
            )
            total_shortage[supply_type.value] = (
                total_shortage.get(supply_type.value, 0.0) + shortage
            )
            total_stock[supply_type.value] = total_stock.get(supply_type.value, 0.0) + stock

        eligible = centre.operational_status == OperationalStatus.OPERATIONAL
        priority_component = PRIORITY_SCORE_MAP[centre.priority.value]
        max_shortage_pct = max((item.shortage_percentage for item in items), default=0.0)
        population_component = centre.affected_population / population_denominator * 100.0
        supply_risk_component = (
            sum(coverage_risks) / len(coverage_risks) * 100.0 if coverage_risks else 0.0
        )
        score = round(
            planning_settings.priority_component_weight * priority_component
            + planning_settings.shortage_component_weight * max_shortage_pct
            + planning_settings.population_component_weight * population_component
            + planning_settings.supply_risk_component_weight * supply_risk_component,
            1,
        )

        centre_plans.append(
            DemandCentreRead(
                relief_centre_id=centre.id,
                name=centre.name,
                district=centre.district,
                latitude=centre.latitude,
                longitude=centre.longitude,
                affected_population=centre.affected_population,
                centre_priority=centre.priority,
                operational_status=centre.operational_status,
                allocation_eligible=eligible,
                priority_score=score,
                priority_classification=_classify(score),
                items=items,
                max_shortage_percentage=round(max_shortage_pct, 2),
            )
        )

    # Global priority order: score desc, then id (deterministic tie-break).
    centre_plans.sort(key=lambda plan: (-plan.priority_score, plan.relief_centre_id))

    assumptions = DemandAssumptions(
        planning_horizon_hours=horizon,
        consumption_rates_per_person_per_day=planning_settings.consumption_rates,
        priority_component_weight=planning_settings.priority_component_weight,
        shortage_component_weight=planning_settings.shortage_component_weight,
        population_component_weight=planning_settings.population_component_weight,
        supply_risk_component_weight=planning_settings.supply_risk_component_weight,
    )
    response = DemandAssessmentResponse(
        data_mode="SIMULATED",
        generated_at=utcnow(),
        planning_run_id=None,
        horizon_hours=horizon,
        assumptions=assumptions,
        summary=DemandSummary(
            centres_assessed=len(centre_plans),
            centres_eligible=sum(1 for plan in centre_plans if plan.allocation_eligible),
            total_required_by_supply=dict(sorted(total_required.items())),
            total_shortage_by_supply=dict(sorted(total_shortage.items())),
            total_stock_at_centres_by_supply=dict(sorted(total_stock.items())),
        ),
        centres=centre_plans,
    )
    logger.info(
        "Demand assessment computed (horizon=%sh, centres=%s)", horizon, len(centre_plans)
    )

    if persist:
        run = PlanningRun(
            planning_type=PlanningType.DEMAND,
            status=PlanningStatus.COMPLETED,
            planning_horizon_hours=horizon,
            assumptions=assumptions.model_dump(mode="json"),
            summary=response.summary.model_dump(mode="json"),
        )
        db.add(run)
        db.flush()
        response.planning_run_id = run.id
        run.snapshot = response.model_dump(mode="json")
        db.commit()
        logger.info("Demand assessment persisted as planning run %s", run.id)
    return response


def _classify(score: float) -> str:
    """Map a 0-100 composite score to a priority classification."""
    if score >= PRIORITY_CLASSIFICATION_THRESHOLDS["critical"]:
        return "Critical"
    if score >= PRIORITY_CLASSIFICATION_THRESHOLDS["high"]:
        return "High"
    if score >= PRIORITY_CLASSIFICATION_THRESHOLDS["medium"]:
        return "Medium"
    return "Low"
