"""Simulation endpoint tests: reset + event handling."""

from __future__ import annotations

from sqlalchemy import select

from app.models import Incident, RoadSegment, Vehicle, Warehouse
from app.services.seed_service import seed_demo


def _unblocked_segment_id(client) -> int:
    body = client.get("/api/v1/map/overview").json()
    return next(
        s["id"]
        for s in body["road_segments"]
        if s["from_node_name"] == "Thanjavur Junction"
        and s["to_node_name"] == "Orathanadu Junction"
    )


def test_bridge_collapse_blocks_segment(seeded_db, client):
    segment_id = _unblocked_segment_id(client)
    assert (
        client.get("/api/v1/dashboard/summary").json()["summary"]["blocked_roads"] == 1
    )

    response = client.post(
        "/api/v1/simulation/events",
        json={
            "event_type": "bridge_collapse",
            "road_segment_id": segment_id,
            "blockage_reason": "Simulated collapse during test",
        },
    )
    assert response.status_code == 201
    result = response.json()
    assert result["data_mode"] == "SIMULATED"
    assert result["event"]["event_type"] == "bridge_collapse"
    assert result["changes"]  # a clear description of state changes

    assert (
        client.get("/api/v1/dashboard/summary").json()["summary"]["blocked_roads"] == 2
    )
    segment = seeded_db.get(RoadSegment, segment_id)
    seeded_db.refresh(segment)
    assert segment.is_blocked is True
    assert segment.blockage_reason == "Simulated collapse during test"


def test_warehouse_unavailable_keeps_inventory(seeded_db, client):
    inventory_count = len(client.get("/api/v1/warehouses/3").json()["inventory"])

    response = client.post(
        "/api/v1/simulation/events",
        json={"event_type": "warehouse_unavailable", "warehouse_id": 3},
    )
    assert response.status_code == 201
    warehouse = client.get("/api/v1/warehouses/3").json()
    assert warehouse["operational_status"] == "unavailable"
    # Inventory is retained, not deleted.
    assert len(warehouse["inventory"]) == inventory_count == 4

    # Duplicate event is tolerated gracefully.
    duplicate = client.post(
        "/api/v1/simulation/events",
        json={"event_type": "warehouse_unavailable", "warehouse_id": 3},
    )
    assert duplicate.status_code == 201


def test_vehicle_breakdown_sets_maintenance(seeded_db, client):
    response = client.post(
        "/api/v1/simulation/events",
        json={"event_type": "vehicle_breakdown", "vehicle_id": 1},
    )
    assert response.status_code == 201
    assert response.json()["event"]["affected_entity_type"] == "vehicle"

    vehicle = client.get("/api/v1/vehicles/1").json()
    assert vehicle["status"] == "maintenance"
    assert client.get("/api/v1/vehicles", params={"status": "available"}).json()["total"] == 8


def test_water_shortage_escalates_priority(client):
    response = client.post(
        "/api/v1/simulation/events",
        json={"event_type": "relief_centre_water_shortage", "relief_centre_id": 2},
    )
    assert response.status_code == 201
    centre = client.get("/api/v1/relief-centres/2").json()
    assert centre["water_shortage"] is True
    assert centre["priority"] == "critical"  # escalated from high


def test_missing_event_targets_are_rejected(client):
    missing_vehicle = client.post(
        "/api/v1/simulation/events", json={"event_type": "vehicle_breakdown"}
    )
    assert missing_vehicle.status_code == 400
    assert missing_vehicle.json()["error"]["code"] == "bad_request"

    missing_segment = client.post(
        "/api/v1/simulation/events", json={"event_type": "bridge_collapse"}
    )
    assert missing_segment.status_code == 400


def test_invalid_event_type_is_rejected(client):
    response = client.post(
        "/api/v1/simulation/events",
        json={"event_type": "meteor_strike", "vehicle_id": 1},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_simulation_events_listing_is_chronological(client):
    client.post(
        "/api/v1/simulation/events",
        json={"event_type": "vehicle_breakdown", "vehicle_id": 2},
    )
    client.post(
        "/api/v1/simulation/events",
        json={"event_type": "vehicle_breakdown", "vehicle_id": 6},
    )
    body = client.get("/api/v1/simulation/events").json()
    created = [item["created_at"] for item in body["items"]]
    assert created == sorted(created)
    assert body["items"][-1]["event_type"] == "vehicle_breakdown"


def test_simulation_reset_restores_initial_state(seeded_db, session_factory, client):
    # Disrupt the scenario.
    segment_id = _unblocked_segment_id(client)
    client.post(
        "/api/v1/simulation/events",
        json={"event_type": "bridge_collapse", "road_segment_id": segment_id},
    )
    client.post(
        "/api/v1/simulation/events",
        json={"event_type": "warehouse_unavailable", "warehouse_id": 3},
    )
    client.post(
        "/api/v1/simulation/events",
        json={"event_type": "vehicle_breakdown", "vehicle_id": 1},
    )

    # Operator-added data that must survive the reset.
    client.post(
        "/api/v1/incidents",
        json={
            "incident_type": "fire",
            "title": "Operator-reported fire drill",
            "description": "Must survive simulation reset.",
            "source": "operator",
            "severity": "medium",
            "location_name": "Test HQ",
            "latitude": 10.5,
            "longitude": 79.2,
        },
    )

    pre_reset_summary = client.get("/api/v1/dashboard/summary").json()["summary"]
    assert pre_reset_summary["blocked_roads"] == 2

    response = client.post("/api/v1/simulation/reset")
    assert response.status_code == 200
    counts = response.json()["counts"]
    assert counts["warehouses"] == 3
    assert counts["relief_centres"] == 5
    assert counts["vehicles"] == 14
    assert counts["incidents"] == 4
    assert counts["road_segments"] == 20

    # Scenario restored.
    summary = client.get("/api/v1/dashboard/summary").json()["summary"]
    assert summary["blocked_roads"] == 1
    assert client.get("/api/v1/warehouses/3").json()["operational_status"] == "operational"
    assert client.get("/api/v1/vehicles/1").json()["status"] == "available"

    # Operator incident preserved; simulation events cleared to the seeded four.
    titles = [
        item["title"]
        for item in client.get("/api/v1/incidents", params={"source": "operator"}).json()["items"]
    ]
    assert "Operator-reported fire drill" in titles
    assert len(client.get("/api/v1/simulation/events").json()["items"]) == 4


def test_reset_and_seed_flow_db_level(session_factory):
    """Seed -> disrupt -> reset leaves consistent DB state directly."""
    with session_factory() as db:
        seed_demo(db)
        vehicle = db.scalar(select(Vehicle).where(Vehicle.vehicle_code == "TRK-01"))
        vehicle.status = "maintenance"
        db.commit()
    with session_factory() as db:
        seed_demo(db)  # idempotent: does not reset vehicle state
        assert db.scalar(select(Vehicle).where(Vehicle.vehicle_code == "TRK-01")).status == "maintenance"
