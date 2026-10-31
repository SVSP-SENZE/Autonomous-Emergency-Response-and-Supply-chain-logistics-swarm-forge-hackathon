"""Resource endpoint tests: warehouses, relief centres, vehicles, incidents."""

from __future__ import annotations

from sqlalchemy import select

from app.models import Incident
from app.services.seed_service import seed_demo


def test_warehouse_list_includes_inventory(client):
    response = client.get("/api/v1/warehouses")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    trichy = next(
        w for w in body["items"] if w["name"] == "Tiruchirappalli Regional Warehouse"
    )
    assert len(trichy["inventory"]) == 4
    water = next(i for i in trichy["inventory"] if i["supply_type"] == "water_litre")
    assert water["quantity"] == 65000
    assert water["reserved_quantity"] == 2000
    assert water["available_quantity"] == water["quantity"] - water["reserved_quantity"]


def test_warehouse_detail_inventory(client):
    response = client.get("/api/v1/warehouses/1")
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Chennai Relief Hub"
    assert {item["supply_type"] for item in body["inventory"]} == {
        "food_kit", "water_litre", "medical_kit", "hygiene_kit",
    }


def test_warehouse_404(client):
    response = client.get("/api/v1/warehouses/999")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_relief_centres_list_and_filters(seeded_db, client):
    response = client.get("/api/v1/relief-centres")
    assert response.status_code == 200
    assert response.json()["total"] == 5

    critical = client.get("/api/v1/relief-centres", params={"priority": "critical"})
    assert critical.status_code == 200
    items = critical.json()["items"]
    assert len(items) == 1
    assert items[0]["name"] == "Thanjavur Relief Centre"

    degraded = client.get(
        "/api/v1/relief-centres", params={"operational_status": "degraded"}
    )
    assert degraded.status_code == 200
    assert [w["name"] for w in degraded.json()["items"]] == ["Pattukkottai Relief Centre"]


def test_relief_centre_detail(client):
    response = client.get("/api/v1/relief-centres/4")
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Pattukkottai Relief Centre"
    assert body["water_shortage"] is True  # seeded shortage state
    assert 0 <= body["latitude"] <= 90


def test_relief_centre_404(client):
    response = client.get("/api/v1/relief-centres/999")
    assert response.status_code == 404


def test_vehicles_list_and_filters(client):
    response = client.get("/api/v1/vehicles")
    assert response.status_code == 200
    assert response.json()["total"] == 14

    available = client.get("/api/v1/vehicles", params={"status": "available"})
    assert available.json()["total"] == 9

    drones = client.get("/api/v1/vehicles", params={"type": "drone"})
    assert drones.json()["total"] == 3

    available_drones = client.get(
        "/api/v1/vehicles", params={"status": "available", "type": "drone"}
    )
    assert available_drones.json()["total"] == 2


def test_vehicle_404(client):
    response = client.get("/api/v1/vehicles/999")
    assert response.status_code == 404


def test_create_incident(seeded_db, client):
    payload = {
        "incident_type": "flood",
        "title": "Manually reported flash flood",
        "description": "Operator created incident for the test.",
        "source": "operator",
        "severity": "medium",
        "status": "reported",
        "location_name": "Test locality",
        "latitude": 10.5,
        "longitude": 79.2,
        "affected_population": 120,
        "metadata": {"reported_by": "pytest"},
    }
    response = client.post("/api/v1/incidents", json=payload)
    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Manually reported flash flood"
    assert body["is_demo"] is False  # operator data, preserved on simulation reset
    assert body["metadata"] == {"reported_by": "pytest"}

    # Persisted in the shared test DB.
    assert seeded_db.scalar(
        select(Incident).where(Incident.title == "Manually reported flash flood")
    ) is not None


def test_incident_validation_rejects_invalid(seeded_db, client):
    invalid = {
        "incident_type": "flood",
        "title": "Bad incident",
        "description": "Negative population must be rejected.",
        "source": "operator",
        "severity": "medium",
        "location_name": "Test locality",
        "latitude": 999,  # out of range
        "longitude": 79.2,
        "affected_population": 100,
    }
    response = client.post("/api/v1/incidents", json=invalid)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"

    bad_severity = dict(invalid, latitude=10.5, severity="extreme")
    response = client.post("/api/v1/incidents", json=bad_severity)
    assert response.status_code == 422

    missing = {"incident_type": "flood"}
    response = client.post("/api/v1/incidents", json=missing)
    assert response.status_code == 422


def test_incident_filters_and_patch(client):
    assert (
        client.get("/api/v1/incidents", params={"severity": "critical"}).json()["total"]
        == 1
    )
    assert (
        client.get("/api/v1/incidents", params={"status": "active"}).json()["total"] == 2
    )
    assert (
        client.get("/api/v1/incidents", params={"incident_type": "water_shortage"}).json()["total"]
        == 1
    )

    detail = client.get("/api/v1/incidents/1")
    assert detail.status_code == 200

    patched = client.patch(
        "/api/v1/incidents/4", json={"status": "active", "description": "Escalated."}
    )
    assert patched.status_code == 200
    assert patched.json()["status"] == "active"

    assert (
        client.patch("/api/v1/incidents/999", json={"status": "active"}).status_code == 404
    )
    empty = client.patch("/api/v1/incidents/4", json={})
    assert empty.status_code == 400
    unknown = client.patch("/api/v1/incidents/4", json={"title": "nope"})
    assert unknown.status_code == 422  # extra fields forbidden


def test_idempotent_seeding(session_factory):
    with session_factory() as first:
        counts_one = seed_demo(first)
    with session_factory() as second:
        counts_two = seed_demo(second)
    assert counts_one == counts_two
    assert counts_one["warehouses"] == 3
    assert counts_one["relief_centres"] == 5
    assert counts_one["vehicles"] == 14
    assert counts_one["road_nodes"] == 16
    assert counts_one["road_segments"] == 20
    assert counts_one["inventory_items"] == 12
