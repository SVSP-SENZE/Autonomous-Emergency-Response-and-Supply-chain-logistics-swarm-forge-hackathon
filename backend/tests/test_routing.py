"""Phase-2 routing engine tests (+ planning/simulation integration).

Expected baseline figures derive from the seeded road data (SIMULATED):
Chennai Hub -> Chennai Bypass -> Trichy Bypass -> Thanjavur Junction ->
Thanjavur Centre Node = 30 + 345 + 65 + 8 = 448 min, 18 + 320 + 55 + 4 = 397 km,
mean risk (0.1 + 0.25 + 0.2 + 0.1) / 4 = 0.1625 -> 0.163 rounded.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import (
    AllocationResult,
    Inventory,
    PlanningRun,
    RoadNode,
    RoadSegment,
)
from app.models.enums import PlanningType


def _node_id(db, node_name: str) -> int:
    node_id = db.scalar(select(RoadNode.id).where(RoadNode.node_name == node_name))
    assert node_id is not None, node_name
    return node_id


def _segment(db, from_name: str, to_name: str) -> RoadSegment:
    from_id = _node_id(db, from_name)
    to_id = _node_id(db, to_name)
    return db.scalar(
        select(RoadSegment).where(
            RoadSegment.from_node_id == from_id, RoadSegment.to_node_id == to_id
        )
    )


def test_shortest_path_baseline(seeded_db, client):
    origin = _node_id(seeded_db, "Chennai Hub")
    destination = _node_id(seeded_db, "Thanjavur Centre Node")
    response = client.get(
        "/api/v1/planning/routes",
        params={"origin_node_id": origin, "destination_node_id": destination},
    )
    assert response.status_code == 200
    route = response.json()
    assert route["reachable"] is True
    assert route["route_node_names"] == [
        "Chennai Hub",
        "Chennai Bypass",
        "Trichy Bypass",
        "Thanjavur Junction",
        "Thanjavur Centre Node",
    ]
    assert route["estimated_travel_time_minutes"] == 448
    assert route["distance_km"] == 397.0
    assert route["route_risk"] == 0.163


def test_bidirectional_traversal(seeded_db, client):
    origin = _node_id(seeded_db, "Thanjavur Centre Node")
    destination = _node_id(seeded_db, "Chennai Hub")
    route = client.get(
        "/api/v1/planning/routes",
        params={"origin_node_id": origin, "destination_node_id": destination},
    ).json()
    assert route["reachable"] is True
    assert route["estimated_travel_time_minutes"] == 448
    assert route["route_node_names"][0] == "Thanjavur Centre Node"


def test_get_matches_post_compute_and_persists_run(seeded_db, client):
    origin = _node_id(seeded_db, "Chennai Hub")
    destination = _node_id(seeded_db, "Thanjavur Centre Node")
    get_route = client.get(
        "/api/v1/planning/routes",
        params={"origin_node_id": origin, "destination_node_id": destination},
    ).json()
    post_route = client.post(
        "/api/v1/planning/routes/compute",
        json={"origin_node_id": origin, "destination_node_id": destination},
    ).json()
    compare_keys = (
        "reachable",
        "route_nodes",
        "distance_km",
        "estimated_travel_time_minutes",
        "route_risk",
    )
    for key in compare_keys:
        assert get_route[key] == post_route[key]
    assert post_route["planning_run_id"] is not None
    seeded_db.expire_all()
    run = seeded_db.get(PlanningRun, post_route["planning_run_id"])
    assert run.planning_type == PlanningType.ROUTE_CALCULATION
    assert run.snapshot["estimated_travel_time_minutes"] == 448


def test_route_between_entities(seeded_db, client):
    response = client.post(
        "/api/v1/planning/routes/between-entities",
        json={
            "origin_type": "warehouse",
            "origin_id": 2,
            "destination_type": "relief_centre",
            "destination_id": 1,
        },
    )
    assert response.status_code == 200
    route = response.json()
    assert route["reachable"] is True
    # Trichy warehouse -> Thanjavur centre: 20 + 65 + 8 = 93 min.
    assert route["estimated_travel_time_minutes"] == 93

    bad_entity = client.post(
        "/api/v1/planning/routes/between-entities",
        json={
            "origin_type": "warehouse",
            "origin_id": 999,
            "destination_type": "relief_centre",
            "destination_id": 1,
        },
    )
    assert bad_entity.status_code == 404

    unsupported = client.post(
        "/api/v1/planning/routes/between-entities",
        json={
            "origin_type": "helicopter",
            "origin_id": 2,
            "destination_type": "relief_centre",
            "destination_id": 1,
        },
    )
    assert unsupported.status_code == 422


def test_blocked_segment_excluded_and_alternative_found(seeded_db, client):
    segment = _segment(seeded_db, "Trichy Bypass", "Thanjavur Junction")
    origin = _node_id(seeded_db, "Chennai Hub")
    destination = _node_id(seeded_db, "Thanjavur Centre Node")
    blocked_ids = client.post(
        "/api/v1/simulation/events",
        json={"event_type": "road_blocked", "road_segment_id": segment.id},
    ).json()["changes"]
    assert blocked_ids

    route = client.get(
        "/api/v1/planning/routes",
        params={"origin_node_id": origin, "destination_node_id": destination},
    ).json()
    assert route["reachable"] is True
    # Alternative via Needamangalam: 30 + 345 + 85 + 45 + 8 = 513 min.
    assert route["estimated_travel_time_minutes"] == 513
    assert "Needamangalam Junction" in route["route_node_names"]
    used_ids = {s["segment_id"] for s in route["segments"]}
    assert segment.id not in used_ids  # blocked segment is never traversed
    assert route["blocked_segments_avoided"] == 1


def test_recalculation_compares_history(seeded_db, client):
    origin = _node_id(seeded_db, "Chennai Hub")
    destination = _node_id(seeded_db, "Thanjavur Centre Node")
    segment = _segment(seeded_db, "Trichy Bypass", "Thanjavur Junction")

    # Baseline (persisted) route before the disruption.
    client.post(
        "/api/v1/planning/routes/compute",
        json={"origin_node_id": origin, "destination_node_id": destination},
    )
    client.post(
        "/api/v1/simulation/events",
        json={
            "event_type": "bridge_collapse",
            "road_segment_id": segment.id,
            "blockage_reason": "Collapsed in test",
        },
    )
    response = client.post(
        "/api/v1/planning/routes/recalculate",
        json={"origin_node_id": origin, "destination_node_id": destination},
    )
    assert response.status_code == 201
    comparison = response.json()
    assert comparison["historical_route_available"] is True
    assert comparison["previous_route"]["estimated_travel_time_minutes"] == 448
    assert comparison["current_route"]["estimated_travel_time_minutes"] == 513
    assert comparison["delay_minutes"] == 65
    assert comparison["previous_route"]["distance_km"] == 397.0
    assert comparison["current_route"]["distance_km"] == 448.0
    blocked_reported = {s["segment_id"] for s in comparison["blocked_segments"]}
    assert segment.id in blocked_reported
    assert comparison["alternative_route_available"] is True
    assert comparison["data_mode"] == "SIMULATED"


def test_recalculation_without_history(seeded_db, client):
    origin = _node_id(seeded_db, "Chennai Hub")
    destination = _node_id(seeded_db, "Orathanadu Centre Node")
    comparison = client.post(
        "/api/v1/planning/routes/recalculate",
        json={"origin_node_id": origin, "destination_node_id": destination},
    ).json()
    assert comparison["historical_route_available"] is False
    assert comparison["previous_route"] is None
    assert comparison["delay_minutes"] is None
    assert comparison["current_route"]["reachable"] is True
    assert "No historical route snapshot" in comparison["explanation"]


def test_unreachable_destination_when_all_paths_blocked(seeded_db, client):
    origin = _node_id(seeded_db, "Chennai Hub")
    destination = _node_id(seeded_db, "Kumbakonam Centre Node")

    # Cut Kumbakonam Junction off: block its approaches (the Thanjavur
    # Junction -> Kumbakonam Junction segment is blocked in the seed data).
    for from_name, to_name in (
        ("Trichy Bypass", "Kumbakonam Junction"),
        ("Kumbakonam Junction", "Needamangalam Junction"),
    ):
        segment = _segment(seeded_db, from_name, to_name)
        event = client.post(
            "/api/v1/simulation/events",
            json={"event_type": "road_blocked", "road_segment_id": segment.id},
        )
        assert event.status_code == 201

    route = client.get(
        "/api/v1/planning/routes",
        params={"origin_node_id": origin, "destination_node_id": destination},
    ).json()
    assert route["reachable"] is False
    assert route["segments"] == []
    assert route["route_nodes"] == []
    assert "No reachable route" in route["message"]


def test_malformed_route_requests(seeded_db, client):
    origin = _node_id(seeded_db, "Chennai Hub")
    unknown = client.get(
        "/api/v1/planning/routes",
        params={"origin_node_id": origin, "destination_node_id": 99999},
    )
    assert unknown.status_code == 404

    identical = client.get(
        "/api/v1/planning/routes",
        params={"origin_node_id": origin, "destination_node_id": origin},
    )
    assert identical.status_code == 400


def test_risk_penalty_changes_route_choice(seeded_db, session_factory, client):
    """A shorter risky segment must lose to a longer safe route (cost model)."""
    from app.core.planning_config import planning_settings

    assert planning_settings.risk_penalty_minutes == 120.0

    with session_factory() as db:
        base = db.scalar(select(RoadNode).where(RoadNode.node_name == "Thanjavur Junction"))
        hot = RoadNode(
            node_name="Risky Heliport Node",
            latitude=base.latitude + 0.01,
            longitude=base.longitude,
            node_type="junction",
            is_demo=False,
        )
        cold = RoadNode(
            node_name="Safe Heliport Node",
            latitude=base.latitude + 0.02,
            longitude=base.longitude + 0.01,
            node_type="junction",
            is_demo=False,
        )
        db.add_all([hot, cold])
        db.flush()
        # Direct: short & very risky (10 min + 0.9 risk -> cost 118).
        db.add(
            RoadSegment(
                from_node_id=hot.id,
                to_node_id=base.id,
                distance_km=5.0,
                estimated_travel_time_minutes=10,
                risk_factor=0.9,
                is_demo=False,
            )
        )
        # Detour via safe node: longer, no risk (40 + 40 = cost 80 < 118).
        db.add(
            RoadSegment(
                from_node_id=hot.id,
                to_node_id=cold.id,
                distance_km=30.0,
                estimated_travel_time_minutes=40,
                risk_factor=0.0,
                is_demo=False,
            )
        )
        db.add(
            RoadSegment(
                from_node_id=cold.id,
                to_node_id=base.id,
                distance_km=30.0,
                estimated_travel_time_minutes=40,
                risk_factor=0.0,
                is_demo=False,
            )
        )
        db.commit()
        hot_id, cold_id, base_id = hot.id, cold.id, base.id

    route = client.get(
        "/api/v1/planning/routes",
        params={"origin_node_id": hot_id, "destination_node_id": base_id},
    ).json()
    assert route["reachable"] is True
    assert route["route_nodes"] == [hot_id, cold_id, base_id]
    assert route["estimated_travel_time_minutes"] == 80
    assert route["route_risk"] == 0.0


# --------------------------------------------------------------------------- #
# Integration: allocation plan -> bridge collapse -> recalculated plan
# --------------------------------------------------------------------------- #


def test_full_planning_integration_flow(seeded_db, client, session_factory):
    warehouse = _node_id(seeded_db, "Madurai Warehouse")
    centre = _node_id(seeded_db, "Thanjavur Centre Node")

    # 1. Baseline allocation plan.
    plan_a = client.post(
        "/api/v1/planning/allocation/compute", json={"horizon_hours": 24}
    ).json()
    thanjavur_a = next(
        c for c in plan_a["centres"] if c["name"] == "Thanjavur Relief Centre"
    )
    water_a = next(l for l in thanjavur_a["lines"] if l["supply_type"] == "water_litre")
    madurai_a = next(
        s for s in water_a["sources"] if s["warehouse_name"] == "Madurai Distribution Centre"
    )
    assert madurai_a["route_travel_time_minutes"] == 233  # 15 + 170 + 40 + 8

    # 2. Persisted snapshot + inventory + baseline route before the disruption.
    with session_factory() as db:
        run_a = db.get(PlanningRun, plan_a["planning_run_id"])
        snapshot_a = run_a.snapshot
        results_a = db.scalars(
            select(AllocationResult).where(
                AllocationResult.planning_run_id == plan_a["planning_run_id"]
            )
        ).all()
        inventory_before = {
            (r.warehouse_id, r.supply_type.value): (r.quantity, r.reserved_quantity)
            for r in db.scalars(select(Inventory)).all()
        }
        collapsed = _segment(db, "Thanjavur Junction", "Orathanadu Junction")
        collapsed_id = collapsed.id

    # Persist a baseline Madurai->Thanjavur route snapshot (audit history).
    baseline_route = client.post(
        "/api/v1/planning/routes/compute",
        json={"origin_node_id": warehouse, "destination_node_id": centre},
    )
    assert baseline_route.status_code == 201

    # 3. Block the Madurai -> Thanjavur link (Orathanadu road).
    event = client.post(
        "/api/v1/simulation/events",
        json={
            "event_type": "bridge_collapse",
            "road_segment_id": collapsed_id,
            "blockage_reason": "Integration test collapse",
        },
    )
    assert event.status_code == 201

    # 4. Route recalculation reflects the new network.
    comparison = client.post(
        "/api/v1/planning/routes/recalculate",
        json={"origin_node_id": warehouse, "destination_node_id": centre},
    ).json()
    assert comparison["historical_route_available"] is True
    assert comparison["alternative_route_available"] is True
    assert comparison["delay_minutes"] > 0
    blocked_ids = {s["segment_id"] for s in comparison["blocked_segments"]}
    assert collapsed_id in blocked_ids

    # 5. New allocation plan routes around the blocked segment.
    plan_b = client.post(
        "/api/v1/planning/allocation/compute", json={"horizon_hours": 24}
    ).json()
    thanjavur_b = next(
        c for c in plan_b["centres"] if c["name"] == "Thanjavur Relief Centre"
    )
    water_b = next(l for l in thanjavur_b["lines"] if l["supply_type"] == "water_litre")
    madurai_b = next(
        s for s in water_b["sources"] if s["warehouse_name"] == "Madurai Distribution Centre"
    )
    # Cheapest detour: Madurai Bypass -> Pattukkottai -> Needamangalam ->
    # Thanjavur Junction -> Centre: 15 + 150 + 70 + 45 + 8 = 288 min (was 233).
    assert madurai_b["route_travel_time_minutes"] == 288
    assert madurai_b["route_cost"] > madurai_a["route_cost"]

    # 6. Previous plan snapshot/results preserved; inventory untouched.
    with session_factory() as db:
        assert db.get(PlanningRun, plan_a["planning_run_id"]).snapshot == snapshot_a
        results_a_after = db.scalars(
            select(AllocationResult).where(
                AllocationResult.planning_run_id == plan_a["planning_run_id"]
            )
        ).all()
        assert [
            (r.warehouse_id, r.relief_centre_id, r.supply_type.value, r.allocated_quantity)
            for r in results_a_after
        ] == [
            (r.warehouse_id, r.relief_centre_id, r.supply_type.value, r.allocated_quantity)
            for r in results_a
        ]
        inventory_after = {
            (r.warehouse_id, r.supply_type.value): (r.quantity, r.reserved_quantity)
            for r in db.scalars(select(Inventory)).all()
        }
        assert inventory_after == inventory_before


def test_planning_runs_never_touch_inventory(seeded_db, client, session_factory):
    with session_factory() as db:
        before = {
            (r.warehouse_id, r.supply_type.value): (r.quantity, r.reserved_quantity)
            for r in db.scalars(select(Inventory)).all()
        }
    client.post("/api/v1/planning/demand/estimate", json={})
    client.post("/api/v1/planning/allocation/compute", json={"horizon_hours": 24})
    origin = _node_id(seeded_db, "Chennai Hub")
    destination = _node_id(seeded_db, "Thanjavur Centre Node")
    client.post(
        "/api/v1/planning/routes/compute",
        json={"origin_node_id": origin, "destination_node_id": destination},
    )
    with session_factory() as db:
        after = {
            (r.warehouse_id, r.supply_type.value): (r.quantity, r.reserved_quantity)
            for r in db.scalars(select(Inventory)).all()
        }
    assert after == before


@pytest.mark.parametrize(
    "horizon",
    [1, 5, 30, 100],
)
def test_disallowed_horizons_rejected(seeded_db, client, horizon):
    response = client.get("/api/v1/planning/demand", params={"horizon_hours": horizon})
    assert response.status_code == 400
