"""Multi-warehouse resource allocation engine (deterministic greedy planner).

Algorithm (per planning horizon):

1. Compute per-centre demand shortages via `demand_service.estimate_demand`.
2. Process centres in deterministic priority order (score desc, population
   desc, id asc). No LLM is involved anywhere.
3. Non-operational centres are never allocated to (returned as excluded).
4. Operational warehouses only; `available = quantity - reserved_quantity`
   is respected via an in-memory remaining-stock ledger so multiple centres
   cannot consume the same stock within one run.
5. Candidate warehouses must have a reachable warehouse-to-centre route
   (NetworkX road graph built once per run and shared).
6. Warehouse ranking cost (documented, configurable):

       allocation_cost = route_travel_time_minutes
                       + mean_route_risk * risk_penalty_minutes

   Deterministic tie-breakers: more remaining stock first, then warehouse id.
7. Stock is taken from the lowest-cost warehouse first, continuing with the
   next until the shortage is fulfilled or inventory is exhausted.
8. Fulfilled/unfulfilled demand, per-supply sources, overall statistics and
   utilisation are returned and persisted as a PlanningRun + AllocationResult
   rows. This service NEVER mutates physical inventory.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.clock import utcnow
from app.core.planning_config import planning_settings
from app.models import AllocationResult, PlanningRun, RoadNode, Warehouse
from app.models.enums import (
    NodeType,
    OperationalStatus,
    PlanningStatus,
    PlanningType,
    SupplyType,
)
from app.schemas.planning import (
    AllocationCentreRead,
    AllocationComputeRequest,
    AllocationLineRead,
    AllocationPlanResponse,
    AllocationSourceRead,
    AllocationSummary,
    ExcludedCentreRead,
    WarehouseUtilisationRead,
)
from app.services.demand_service import estimate_demand, get_demand_assumptions, validate_horizon
from app.services.routing_service import RoadGraph, _route_on_graph

logger = logging.getLogger("reliefmesh.planning.allocation")


def compute_allocation_plan(
    db: Session, request: AllocationComputeRequest | None = None
) -> AllocationPlanResponse:
    """Compute a complete allocation plan and persist it (single transaction)."""
    horizon = validate_horizon(request.horizon_hours if request else None)
    planning_settings.validate_weights()

    demand = estimate_demand(db, horizon_hours=horizon)

    warehouses = db.scalars(
        select(Warehouse).options(selectinload(Warehouse.inventory)).order_by(Warehouse.id)
    ).all()
    warehouse_by_id = {warehouse.id: warehouse for warehouse in warehouses}
    road_graph = RoadGraph(db)
    warehouse_node_ids = _linked_node_ids(db, NodeType.WAREHOUSE)
    centre_node_ids = _linked_node_ids(db, NodeType.RELIEF_CENTRE)

    # In-memory remaining-stock ledger: (warehouse_id, supply_type) -> available.
    ledger: dict[tuple[int, SupplyType], float] = {}
    initial_available: dict[int, dict[str, float]] = {}
    for warehouse in warehouses:
        if warehouse.operational_status != OperationalStatus.OPERATIONAL:
            continue
        for item in warehouse.inventory:
            available = max(item.available_quantity, 0)
            ledger[(warehouse.id, item.supply_type)] = float(available)
            initial_available.setdefault(warehouse.id, {})[item.supply_type.value] = float(
                available
            )

    excluded: list[ExcludedCentreRead] = []
    eligible_plans = []
    for plan in demand.centres:
        if plan.operational_status != OperationalStatus.OPERATIONAL:
            excluded.append(
                ExcludedCentreRead(
                    relief_centre_id=plan.relief_centre_id,
                    name=plan.name,
                    operational_status=plan.operational_status,
                    reason=(
                        f"Centre is {plan.operational_status.value}; not eligible for "
                        "normal allocation"
                    ),
                )
            )
            continue
        if plan.relief_centre_id not in centre_node_ids:
            excluded.append(
                ExcludedCentreRead(
                    relief_centre_id=plan.relief_centre_id,
                    name=plan.name,
                    operational_status=plan.operational_status,
                    reason="Centre has no linked road node; no route can be planned",
                )
            )
            continue
        eligible_plans.append(plan)

    allocated_total: dict[str, float] = {}
    total_required: dict[str, float] = {}
    centres_served: set[int] = set()
    centres_unmet: set[int] = set()
    centre_plans: list[AllocationCentreRead] = []
    result_rows: list[dict] = []

    for plan in eligible_plans:
        centre_node_id = centre_node_ids[plan.relief_centre_id]
        lines: list[AllocationLineRead] = []
        any_allocated = False
        any_unmet = False
        for item in plan.items:
            line = _allocate_for_supply(
                plan=plan,
                item=item,
                centre_node_id=centre_node_id,
                road_graph=road_graph,
                warehouses=warehouses,
                warehouse_node_ids=warehouse_node_ids,
                ledger=ledger,
            )
            lines.append(line)
            allocated_total[item.supply_type.value] = (
                allocated_total.get(item.supply_type.value, 0.0) + line.allocated_quantity
            )
            total_required[item.supply_type.value] = (
                total_required.get(item.supply_type.value, 0.0) + item.required_quantity
            )
            if line.allocated_quantity > 0:
                any_allocated = True
            if line.unfulfilled_quantity > 0:
                any_unmet = True
            result_rows.append(
                {
                    "relief_centre_id": plan.relief_centre_id,
                    "relief_centre_name": plan.name,
                    "supply_type": item.supply_type,
                    "required_quantity": item.required_quantity,
                    "current_centre_stock": item.current_stock,
                    "sources": line.sources,
                    "allocated_quantity": line.allocated_quantity,
                    "unfulfilled_quantity": line.unfulfilled_quantity,
                }
            )
        centre_plans.append(
            AllocationCentreRead(
                relief_centre_id=plan.relief_centre_id,
                name=plan.name,
                district=plan.district,
                affected_population=plan.affected_population,
                centre_priority=plan.centre_priority,
                priority_score=plan.priority_score,
                operational_status=plan.operational_status,
                lines=lines,
            )
        )
        if any_allocated:
            centres_served.add(plan.relief_centre_id)
        if any_unmet:
            centres_unmet.add(plan.relief_centre_id)

    utilisation = _build_utilisation(warehouses, initial_available, ledger)
    remaining_by_supply: dict[str, float] = {}
    for (warehouse_id, supply_type), remaining in ledger.items():
        remaining_by_supply[supply_type.value] = (
            remaining_by_supply.get(supply_type.value, 0.0) + remaining
        )
    total_required_all = sum(total_required.values())
    total_allocated_all = sum(allocated_total.values())
    fulfilment_pct = (
        round(total_allocated_all / total_required_all * 100.0, 2)
        if total_required_all > 0
        else 100.0
    )

    summary = AllocationSummary(
        required_by_supply=_rounded_map(total_required),
        allocated_by_supply=_rounded_map(allocated_total),
        unfulfilled_by_supply={
            key: round(max(value - allocated_total.get(key, 0.0), 0.0), 2)
            for key, value in total_required.items()
        },
        fulfilment_percentage=fulfilment_pct,
        centres_planned=len(centre_plans),
        centres_served=len(centres_served),
        centres_with_unmet_demand=len(centres_unmet),
        warehouse_utilisation=utilisation,
        remaining_by_supply=_rounded_map(remaining_by_supply),
    )

    response = AllocationPlanResponse(
        data_mode="SIMULATED",
        generated_at=utcnow(),
        planning_run_id=None,
        horizon_hours=horizon,
        assumptions=get_demand_assumptions().model_copy(
            update={"planning_horizon_hours": horizon}
        ),
        summary=summary,
        centres=centre_plans,
        excluded_centres=excluded,
    )

    # --- Persistence (single commit; never mutates physical stock) -----------
    run = PlanningRun(
        planning_type=PlanningType.ALLOCATION,
        status=PlanningStatus.COMPLETED,
        planning_horizon_hours=horizon,
        assumptions=response.assumptions.model_dump(mode="json"),
        summary=summary.model_dump(mode="json"),
    )
    db.add(run)
    db.flush()
    response.planning_run_id = run.id
    response_snapshot = response.model_dump(mode="json")
    response_snapshot["planning_run_id"] = run.id
    run.snapshot = response_snapshot
    for row in result_rows:
        for source in row["sources"]:
            db.add(
                AllocationResult(
                    planning_run_id=run.id,
                    relief_centre_id=row["relief_centre_id"],
                    relief_centre_name=row["relief_centre_name"],
                    warehouse_id=source.warehouse_id,
                    warehouse_name=source.warehouse_name,
                    supply_type=row["supply_type"],
                    required_quantity=row["required_quantity"],
                    current_centre_stock=row["current_centre_stock"],
                    allocated_quantity=source.quantity,
                    unfulfilled_quantity=0.0,
                    route_distance_km=source.route_distance_km,
                    route_travel_time_minutes=source.route_travel_time_minutes,
                    route_risk=source.route_risk,
                )
            )
        # Record unfulfilled remainder so audit history is complete.
        unfulfilled = row["unfulfilled_quantity"]
        if unfulfilled > 0:
            db.add(
                AllocationResult(
                    planning_run_id=run.id,
                    relief_centre_id=row["relief_centre_id"],
                    relief_centre_name=row["relief_centre_name"],
                    warehouse_id=None,
                    warehouse_name=None,
                    supply_type=row["supply_type"],
                    required_quantity=row["required_quantity"],
                    current_centre_stock=row["current_centre_stock"],
                    allocated_quantity=0.0,
                    unfulfilled_quantity=unfulfilled,
                    route_distance_km=None,
                    route_travel_time_minutes=None,
                    route_risk=None,
                )
            )
    db.commit()
    logger.info(
        "Allocation plan persisted as run %s (horizon=%sh, fulfilment=%.2f%%, served=%s/%s)",
        run.id, horizon, fulfilment_pct, len(centres_served), len(centre_plans),
    )
    return response


def get_latest_allocation_plan(db: Session) -> AllocationPlanResponse | None:
    """Return the most recent persisted allocation plan, if any."""
    run = db.scalar(
        select(PlanningRun)
        .where(PlanningRun.planning_type == PlanningType.ALLOCATION)
        .order_by(PlanningRun.created_at.desc(), PlanningRun.id.desc())
        .limit(1)
    )
    if run is None or not run.snapshot:
        return None
    return AllocationPlanResponse.model_validate(run.snapshot)


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #


def _allocate_for_supply(
    *,
    plan,
    item,
    centre_node_id: int,
    road_graph: RoadGraph,
    warehouses: list[Warehouse],
    warehouse_node_ids: dict[int, int],
    ledger: dict[tuple[int, SupplyType], float],
) -> AllocationLineRead:
    """Greedy allocation for a single (centre, supply-type) shortage."""
    remaining_shortage = item.shortage_quantity
    sources: list[AllocationSourceRead] = []
    allocated = 0.0

    if remaining_shortage > 0:
        candidates = _rank_warehouses(
            road_graph=road_graph,
            supply_type=item.supply_type,
            centre_node_id=centre_node_id,
            warehouses=warehouses,
            warehouse_node_ids=warehouse_node_ids,
            ledger=ledger,
        )
        for candidate in candidates:
            if remaining_shortage <= 0:
                break
            warehouse = candidate.warehouse
            available = ledger.get((warehouse.id, item.supply_type), 0.0)
            if available <= 0:
                continue
            quantity = min(remaining_shortage, available)
            ledger[(warehouse.id, item.supply_type)] = available - quantity
            remaining_shortage -= quantity
            allocated += quantity
            sources.append(
                AllocationSourceRead(
                    warehouse_id=warehouse.id,
                    warehouse_name=warehouse.name,
                    quantity=quantity,
                    route_distance_km=candidate.route.distance_km,
                    route_travel_time_minutes=candidate.route.estimated_travel_time_minutes,
                    route_risk=candidate.route.route_risk,
                    route_cost=round(candidate.route_cost, 2),
                )
            )

    fulfilment = (
        round(allocated / item.shortage_quantity * 100.0, 2)
        if item.shortage_quantity > 0
        else 100.0
    )
    return AllocationLineRead(
        supply_type=item.supply_type,
        required_quantity=item.required_quantity,
        current_stock=item.current_stock,
        shortage_quantity=item.shortage_quantity,
        allocated_quantity=round(allocated, 2),
        unfulfilled_quantity=round(max(remaining_shortage, 0.0), 2),
        fulfilment_percentage=fulfilment,
        sources=sources,
    )


@dataclass
class _Candidate:
    warehouse: Warehouse
    route_cost: float
    route: object = field(default=None)


def _rank_warehouses(
    *,
    road_graph: RoadGraph,
    supply_type: SupplyType,
    centre_node_id: int,
    warehouses: list[Warehouse],
    warehouse_node_ids: dict[int, int],
    ledger: dict[tuple[int, SupplyType], float],
) -> list[_Candidate]:
    """Operational warehouses with stock that can reach the centre, ranked by cost."""
    candidates: list[_Candidate] = []
    for warehouse in warehouses:
        if warehouse.operational_status != OperationalStatus.OPERATIONAL:
            continue
        available = ledger.get((warehouse.id, supply_type), 0.0)
        if available <= 0:
            continue
        warehouse_node_id = warehouse_node_ids.get(warehouse.id)
        if warehouse_node_id is None:
            continue  # unreachable (no road node): not a valid source
        route = _route_on_graph(road_graph, warehouse_node_id, centre_node_id)
        if not route.reachable:
            continue  # road network does not connect warehouse to centre
        route_cost = route.estimated_travel_time_minutes + route.route_risk * (
            planning_settings.risk_penalty_minutes
        )
        candidates.append(
            _Candidate(
                warehouse=warehouse,
                route_cost=route_cost,
                route=route,
            )
        )
    # Deterministic: cost asc, then remaining stock desc, then warehouse id.
    candidates.sort(
        key=lambda c: (
            round(c.route_cost, 3),
            -ledger.get((c.warehouse.id, supply_type), 0.0),
            c.warehouse.id,
        )
    )
    return candidates


def _linked_node_ids(db: Session, node_type: NodeType) -> dict[int, int]:
    """entity_id -> road node id for the given entity kind."""
    rows = db.execute(
        select(RoadNode.linked_entity_id, RoadNode.id).where(RoadNode.node_type == node_type)
    ).all()
    return {int(entity_id): int(node_id) for entity_id, node_id in rows if entity_id is not None}


def _build_utilisation(
    warehouses: list[Warehouse],
    initial_available: dict[int, dict[str, float]],
    ledger: dict[tuple[int, SupplyType], float],
) -> list[WarehouseUtilisationRead]:
    utilisation: list[WarehouseUtilisationRead] = []
    for warehouse in warehouses:
        if warehouse.id not in initial_available:
            # Non-operational warehouses were excluded from the ledger entirely.
            available_map = {
                item.supply_type.value: float(max(item.available_quantity, 0))
                for item in warehouse.inventory
            }
            utilisation.append(
                WarehouseUtilisationRead(
                    warehouse_id=warehouse.id,
                    warehouse_name=warehouse.name,
                    initial_available_by_supply=available_map,
                    allocated_by_supply={key: 0.0 for key in available_map},
                    remaining_by_supply=available_map,
                )
            )
            continue
        allocated_map: dict[str, float] = {}
        remaining_map: dict[str, float] = {}
        for (warehouse_id, supply_type), remaining in ledger.items():
            if warehouse_id != warehouse.id:
                continue
            initial = initial_available[warehouse.id].get(supply_type.value, 0.0)
            allocated_map[supply_type.value] = round(initial - remaining, 2)
            remaining_map[supply_type.value] = round(remaining, 2)
        initial_map = initial_available[warehouse.id]
        unused_keys = set(initial_map) - set(allocated_map)
        for key in unused_keys:
            allocated_map[key] = 0.0
            remaining_map[key] = initial_map[key]
        utilisation.append(
            WarehouseUtilisationRead(
                warehouse_id=warehouse.id,
                warehouse_name=warehouse.name,
                initial_available_by_supply={k: round(v, 2) for k, v in initial_map.items()},
                allocated_by_supply=_rounded_map(allocated_map),
                remaining_by_supply=_rounded_map(remaining_map),
            )
        )
    return utilisation


def _rounded_map(values: dict[str, float]) -> dict[str, float]:
    """Round a supply-keyed dict to 2 decimals with stable key ordering."""
    return {key: round(values[key], 2) for key in sorted(values)}
