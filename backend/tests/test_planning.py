"""Phase-2 demand estimation & allocation tests.

All figures follow the documented DEMO assumptions in
`app/core/planning_config.py` (water 3 L/person/day, food 1 kit / 5 people /
day, medical 1 kit / 50 people / day, hygiene 1 kit / 10 people / day).
"""

from __future__ import annotations

from sqlalchemy import select

from app.models import (
    AllocationResult,
    Inventory,
    PlanningRun,
    ReliefCentre,
    ReliefCentreInventory,
    RoadNode,
    Warehouse,
)
from app.models.enums import (
    NodeType,
    OperationalStatus,
    PlanningType,
    Priority,
    SupplyType as SupplyTypeEnum,
)


def _node_id(db, node_name: str) -> int:
    return db.scalar(select(RoadNode.id).where(RoadNode.node_name == node_name))


def _centre(db, name: str) -> ReliefCentre:
    return db.scalar(select(ReliefCentre).where(ReliefCentre.name == name))


# --------------------------------------------------------------------------- #
# Demand estimation
# --------------------------------------------------------------------------- #


def test_water_demand_matches_formula(seeded_db, client):
    body = client.get("/api/v1/planning/demand", params={"horizon_hours": 24}).json()
    body_thanjavur = next(
        c for c in body["centres"] if c["name"] == "Thanjavur Relief Centre"
    )
    water = next(
        i for i in body_thanjavur["items"] if i["supply_type"] == "water_litre"
    )
    # 52000 people x 3 L/day x (24/24) = 156000 litres.
    assert water["required_quantity"] == 156000.0
    assert water["current_stock"] == 6000
    assert water["shortage_quantity"] == 150000.0
    assert water["shortage_percentage"] == 96.15  # 150000/156000*100 rounded
    assert body["horizon_hours"] == 24
    assert body["data_mode"] == "SIMULATED"


def test_planning_horizon_scaling(seeded_db, client):
    for horizon, expected in ((6, 39000.0), (12, 78000.0), (48, 312000.0), (72, 468000.0)):
        body = client.get(
            "/api/v1/planning/demand", params={"horizon_hours": horizon}
        ).json()
        thanjavur = next(
            c for c in body["centres"] if c["name"] == "Thanjavur Relief Centre"
        )
        water = next(
            i for i in thanjavur["items"] if i["supply_type"] == "water_litre"
        )
        assert water["required_quantity"] == expected, horizon


def test_kit_quantities_rounded_up(seeded_db, session_factory):
    """A centre of 1234 people for 6h: ceil rules per supply type."""
    from app.services.demand_service import estimate_demand

    with session_factory() as db:
        db.add(
            ReliefCentre(
                name="Rounding Test Centre",
                district="Test District",
                latitude=10.0,
                longitude=79.0,
                affected_population=1234,
                priority=Priority.HIGH,
                operational_status=OperationalStatus.OPERATIONAL,
                is_demo=False,
            )
        )
        db.commit()
        assessment = estimate_demand(db, horizon_hours=6)

    plan = next(c for c in assessment.centres if c.name == "Rounding Test Centre")
    items = {i.supply_type.value: i for i in plan.items}
    # Exact: 1234 * 3 * 0.25 = 925.5 L (precision retained, 2 decimals).
    assert items["water_litre"].required_quantity == 925.5
    # 1234 * 0.2 * 0.25 = 61.7 -> ceil 62 kits; medical 6.17 -> 7; hygiene 30.85 -> 31.
    assert items["food_kit"].required_quantity == 62.0
    assert items["medical_kit"].required_quantity == 7.0
    assert items["hygiene_kit"].required_quantity == 31.0


def test_shortage_fields_and_zero_demand(seeded_db, client):
    body = client.get("/api/v1/planning/demand").json()
    for centre in body["centres"]:
        for item in centre["items"]:
            assert item["shortage_quantity"] == max(
                item["required_quantity"] - item["current_stock"], 0
            )
            assert item["surplus_quantity"] == max(
                item["current_stock"] - item["required_quantity"], 0
            )
            if item["required_quantity"] > 0:
                expected_pct = round(
                    item["shortage_quantity"] / item["required_quantity"] * 100, 2
                )
                assert item["shortage_percentage"] == expected_pct


def test_priority_scoring_ordering_and_classification(seeded_db, client):
    body = client.get("/api/v1/planning/demand").json()
    scores = [c["priority_score"] for c in body["centres"]]
    assert scores == sorted(scores, reverse=True)
    assert all(0 <= s <= 100 for s in scores)
    thanjavur = next(
        c for c in body["centres"] if c["name"] == "Thanjavur Relief Centre"
    )
    assert thanjavur["priority_classification"] == "Critical"
    for centre in body["centres"]:
        cls = centre["priority_classification"]
        score = centre["priority_score"]
        if cls == "Critical":
            assert score >= 85
        elif cls == "High":
            assert 65 <= score < 85
        elif cls == "Medium":
            assert 40 <= score < 65
        else:
            assert score < 40


def test_demand_filters_and_demand_endpoint_errors(seeded_db, client):
    body = client.get("/api/v1/planning/demand", params={"priority": "critical"}).json()
    assert body["summary"]["centres_assessed"] == 1
    assert body["centres"][0]["name"] == "Thanjavur Relief Centre"

    centre_id = next(
        c["relief_centre_id"] for c in body["centres"]
    )
    single = client.get(
        "/api/v1/planning/demand", params={"relief_centre_id": centre_id}
    ).json()
    assert len(single["centres"]) == 1

    bad_horizon = client.get("/api/v1/planning/demand", params={"horizon_hours": 7})
    assert bad_horizon.status_code == 400
    assert bad_horizon.json()["error"]["code"] == "bad_request"

    missing = client.get("/api/v1/planning/demand", params={"relief_centre_id": 999})
    assert missing.status_code == 404


def test_post_demand_estimate_persists_planning_run(seeded_db, client):
    runs_before = len(
        seeded_db.scalars(
            select(PlanningRun).where(PlanningRun.planning_type == PlanningType.DEMAND)
        ).all()
    )
    response = client.post("/api/v1/planning/demand/estimate", json={})
    assert response.status_code == 201
    result = response.json()
    assert result["planning_run_id"] is not None
    seeded_db.expire_all()
    runs = seeded_db.scalars(
        select(PlanningRun).where(PlanningRun.planning_type == PlanningType.DEMAND)
    ).all()
    assert len(runs) == runs_before + 1
    run = runs[-1]
    assert run.snapshot["horizon_hours"] == 24
    assert run.snapshot["assumptions"]["consumption_rates_per_person_per_day"]["water_litre"] == 3.0
    assert run.planning_horizon_hours == 24


# --------------------------------------------------------------------------- #
# Allocation
# --------------------------------------------------------------------------- #


def _snapshot_inventory(db) -> dict:
    rows = db.scalars(select(Inventory)).all()
    inv = {(r.warehouse_id, r.supply_type.value): (r.quantity, r.reserved_quantity) for r in rows}
    centre_rows = db.scalars(select(ReliefCentreInventory)).all()
    centres = {(r.relief_centre_id, r.supply_type.value): r.quantity for r in centre_rows}
    return {"warehouse": inv, "centre": centres}


def test_allocation_respects_stock_and_reserved(seeded_db, client):
    before = _snapshot_inventory(seeded_db)
    response = client.post("/api/v1/planning/allocation/compute", json={"horizon_hours": 24})
    assert response.status_code == 201
    plan = response.json()

    utilisation = plan["summary"]["warehouse_utilisation"]
    by_warehouse = {u["warehouse_id"]: u for u in utilisation}
    # Total allocated per (warehouse, supply) never exceeds initial available
    # and remaining + allocated == initial (ledger invariants).
    for warehouse_id, util in by_warehouse.items():
        for supply, initial in util["initial_available_by_supply"].items():
            allocated = util["allocated_by_supply"].get(supply, 0.0)
            remaining = util["remaining_by_supply"].get(supply, 0.0)
            assert allocated <= initial + 1e-6, (warehouse_id, supply)
            assert round(allocated + remaining, 2) == round(initial, 2)
    # Available inventory subtracts reserved quantities: Chennai water is
    # 120000 quantity with 3000 reserved -> at most 117000 can be allocated.
    chennai = by_warehouse[1]
    assert chennai["allocated_by_supply"]["water_litre"] <= 117000.0

    after = _snapshot_inventory(seeded_db)
    assert after == before  # planning never mutates physical stock


def test_allocations_source_totals_match_lines(seeded_db, client):
    plan = client.post(
        "/api/v1/planning/allocation/compute", json={"horizon_hours": 24}
    ).json()
    for centre in plan["centres"]:
        for line in centre["lines"]:
            source_total = sum(s["quantity"] for s in line["sources"])
            assert round(source_total, 2) == round(line["allocated_quantity"], 2)
            assert line["allocated_quantity"] + line["unfulfilled_quantity"] <= line[
                "shortage_quantity"
            ] + 1e-6
            assert line["unfulfilled_quantity"] == round(
                max(line["shortage_quantity"] - line["allocated_quantity"], 0.0), 2
            )


def test_high_priority_centre_served_first_with_split_sources(seeded_db, client):
    plan = client.post(
        "/api/v1/planning/allocation/compute", json={"horizon_hours": 24}
    ).json()
    # Centres are processed in priority-score (desc) order.
    scores = [c["priority_score"] for c in plan["centres"]]
    assert scores == sorted(scores, reverse=True)

    thanjavur = next(
        c for c in plan["centres"] if c["name"] == "Thanjavur Relief Centre"
    )
    water = next(
        l for l in thanjavur["lines"] if l["supply_type"] == "water_litre"
    )
    # Highest priority centre gets its full water shortage.
    assert water["allocated_quantity"] == 150000.0
    assert water["unfulfilled_quantity"] == 0.0
    assert water["fulfilment_percentage"] == 100.0
    # Demand split across multiple warehouses.
    assert len(water["sources"]) >= 2
    # Cheapest route (Trichy) contributes before more distant warehouses.
    assert water["sources"][0]["warehouse_name"] == "Tiruchirappalli Regional Warehouse"
    assert water["sources"][0]["quantity"] == 63000.0


def test_summary_unfulfilled_and_centre_counts(seeded_db, client):
    plan = client.post(
        "/api/v1/planning/allocation/compute", json={"horizon_hours": 24}
    ).json()
    summary = plan["summary"]
    for supply, required in summary["required_by_supply"].items():
        allocated = summary["allocated_by_supply"].get(supply, 0.0)
        unfulfilled = summary["unfulfilled_by_supply"].get(supply, 0.0)
        assert round(allocated + unfulfilled, 2) == round(required, 2)
    assert summary["fulfilment_percentage"] == 61.84
    assert summary["centres_with_unmet_demand"] >= 1
    # The degraded centre is excluded with a reason.
    excluded_names = {c["name"]: c["reason"] for c in plan["excluded_centres"]}
    assert "Pattukkottai Relief Centre" in excluded_names
    assert "degraded" in excluded_names["Pattukkottai Relief Centre"]


def test_allocation_persisted_results_and_latest_snapshot(seeded_db, client):
    # Before any computation the latest endpoint reports 404.
    missing = client.get("/api/v1/planning/allocation/latest")
    assert missing.status_code == 404

    computed = client.post(
        "/api/v1/planning/allocation/compute", json={"horizon_hours": 24}
    ).json()
    run_id = computed["planning_run_id"]
    latest = client.get("/api/v1/planning/allocation/latest")
    assert latest.status_code == 200
    assert latest.json()["planning_run_id"] == run_id

    seeded_db.expire_all()
    results = seeded_db.scalars(
        select(AllocationResult).where(AllocationResult.planning_run_id == run_id)
    ).all()
    assert results  # tabular allocation rows persisted
    for row in results:
        assert row.allocated_quantity >= 0
        assert row.unfulfilled_quantity >= 0
        assert row.relief_centre_name  # denormalised audit name


def test_unavailable_warehouse_excluded(seeded_db, session_factory, client):
    # Make the Madurai warehouse unavailable via direct update.
    with session_factory() as db:
        warehouse = db.scalar(select(Warehouse).where(Warehouse.name == "Madurai Distribution Centre"))
        warehouse.operational_status = OperationalStatus.UNAVAILABLE
        db.commit()

    plan = client.post(
        "/api/v1/planning/allocation/compute", json={"horizon_hours": 24}
    ).json()
    for util in plan["summary"]["warehouse_utilisation"]:
        if util["warehouse_name"] == "Madurai Distribution Centre":
            assert all(v == 0.0 for v in util["allocated_by_supply"].values())
    for centre in plan["centres"]:
        for line in centre["lines"]:
            for source in line["sources"]:
                assert source["warehouse_name"] != "Madurai Distribution Centre"


def test_disconnected_warehouse_excluded(seeded_db, session_factory, client):
    """A warehouse without any road node cannot be an allocation source."""
    with session_factory() as db:
        # Add stock to a warehouse that has no road node at all.
        orphan = Warehouse(
            name="Orphan Test Warehouse",
            location_name="Isolated",
            latitude=11.0,
            longitude=79.5,
            operational_status=OperationalStatus.OPERATIONAL,
            is_demo=False,
        )
        db.add(orphan)
        db.flush()
        db.add(
            Inventory(
                warehouse_id=orphan.id,
                supply_type=SupplyTypeEnum.WATER_LITRE,
                quantity=10000,
                reserved_quantity=0,
                unit="litres",
            )
        )
        # Sanity: no warehouse-type road node linked to this warehouse.
        node = db.scalar(
            select(RoadNode).where(
                RoadNode.linked_entity_id == orphan.id,
                RoadNode.node_type == NodeType.WAREHOUSE,
            )
        )
        assert node is None
        db.commit()
        orphan_id = orphan.id

    plan = client.post(
        "/api/v1/planning/allocation/compute", json={"horizon_hours": 24}
    ).json()
    for centre in plan["centres"]:
        for line in centre["lines"]:
            for source in line["sources"]:
                assert source["warehouse_id"] != orphan_id
    # Its stock stays untouched in utilisation reporting.
    orphan_util = next(
        u
        for u in plan["summary"]["warehouse_utilisation"]
        if u["warehouse_id"] == orphan_id
    )
    assert orphan_util["allocated_by_supply"]["water_litre"] == 0.0
    assert orphan_util["remaining_by_supply"]["water_litre"] == 10000.0


def test_non_operational_centre_excluded_from_allocation(seeded_db, session_factory, client):
    with session_factory() as db:
        centre = _centre(db, "Kumbakonam Relief Centre")
        centre.operational_status = OperationalStatus.UNAVAILABLE
        db.commit()

    plan = client.post(
        "/api/v1/planning/allocation/compute", json={"horizon_hours": 24}
    ).json()
    planned_names = {c["name"] for c in plan["centres"]}
    assert "Kumbakonam Relief Centre" not in planned_names
    excluded = {c["name"]: c["reason"] for c in plan["excluded_centres"]}
    assert "Kumbakonam Relief Centre" in excluded

    # Existing stock at the excluded centre is unchanged.
    with session_factory() as db:
        centre = _centre(db, "Kumbakonam Relief Centre")
        stock = {
            i.supply_type.value: i.quantity
            for i in centre.inventory_of_centre
        }
        assert stock["water_litre"] == 4200


def test_two_plans_both_preserved(seeded_db, client, session_factory):
    """A second run appends a new PlanningRun; earlier snapshots are not touched."""
    plan_a = client.post(
        "/api/v1/planning/allocation/compute", json={"horizon_hours": 24}
    ).json()
    with session_factory() as db:
        snapshot_a = db.get(PlanningRun, plan_a["planning_run_id"]).snapshot
        centre_id = db.scalar(select(ReliefCentre.id).where(
            ReliefCentre.name == "Thanjavur Relief Centre"
        ))
        water_row = db.scalar(
            select(ReliefCentreInventory).where(
                ReliefCentreInventory.relief_centre_id == centre_id,
                ReliefCentreInventory.supply_type == SupplyTypeEnum.WATER_LITRE,
            )
        )
        water_row.quantity = 106000  # 6000 -> 106000 via a direct DB edit
        db.commit()

    plan_b = client.post(
        "/api/v1/planning/allocation/compute", json={"horizon_hours": 24}
    ).json()
    assert plan_b["planning_run_id"] != plan_a["planning_run_id"]
    thanjavur_b = next(
        c for c in plan_b["centres"] if c["name"] == "Thanjavur Relief Centre"
    )
    water_b = next(l for l in thanjavur_b["lines"] if l["supply_type"] == "water_litre")
    # Increased centre stock -> smaller shortage now (156000 - 106000).
    assert water_b["shortage_quantity"] == 50000.0

    with session_factory() as db:
        snapshot_a_after = db.get(PlanningRun, plan_a["planning_run_id"]).snapshot
        assert snapshot_a_after == snapshot_a  # never overwritten
