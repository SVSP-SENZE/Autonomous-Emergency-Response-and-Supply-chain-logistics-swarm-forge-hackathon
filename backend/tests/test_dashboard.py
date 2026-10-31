"""Dashboard + map aggregate tests (values must match the seeded scenario)."""

from __future__ import annotations

# Seeded scenario reference numbers (see services/seed_data.py).
TOTAL_AFFECTED = 52000 + 38000 + 21000 + 26000 + 18000  # 155_000
TOTAL_VEHICLES = 14
AVAILABLE_VEHICLES = 9
IN_TRANSIT_VEHICLES = 1


def test_dashboard_summary_matches_seed(client):
    response = client.get("/api/v1/dashboard/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["data_mode"] == "SIMULATED"

    summary = body["summary"]
    assert summary["affected_population"] == TOTAL_AFFECTED
    assert summary["active_disasters"] == 2  # two active flood incidents
    assert summary["relief_centres"] == 5
    assert summary["critical_centres"] == 1  # Thanjavur
    assert summary["warehouses"] == 3
    assert summary["total_vehicles"] == TOTAL_VEHICLES
    assert summary["available_vehicles"] == AVAILABLE_VEHICLES
    assert summary["vehicles_in_transit"] == IN_TRANSIT_VEHICLES
    assert summary["blocked_roads"] == 1  # Thanjavur -> Kumbakonam causeway

    inventory = {item["supply_type"]: item for item in body["inventory"]}
    assert inventory["water_litre"]["quantity"] == 120000 + 65000 + 48000
    assert inventory["water_litre"]["reserved_quantity"] == 3000 + 2000
    assert inventory["water_litre"]["available_quantity"] == (
        233000 - 5000
    )
    assert inventory["food_kit"]["available_quantity"] == 29200 - 400
    assert inventory["medical_kit"]["available_quantity"] == 6200
    assert inventory["hygiene_kit"]["available_quantity"] == 9900 - 200

    assert body["orders_by_status"]["draft"] == 1
    assert body["orders_by_status"]["approved"] == 1
    assert body["orders_by_status"]["dispatched"] == 1


def test_dashboard_orders_by_status_totals(client):
    body = client.get("/api/v1/dashboard/summary").json()
    orders_by_status = body["orders_by_status"]
    # All declared order statuses are present as keys (Phase 4 adds `delayed`).
    assert set(orders_by_status) == {
        "draft", "awaiting_approval", "approved", "dispatched",
        "in_transit", "delivered", "cancelled", "delayed",
    }
    assert sum(orders_by_status.values()) == 3  # three seeded demo orders


def test_map_overview_structure(client):
    response = client.get("/api/v1/map/overview")
    assert response.status_code == 200
    body = response.json()
    assert body["data_mode"] == "SIMULATED"
    assert body["incidents"] and body["relief_centres"] and body["warehouses"]
    assert body["road_nodes"] and body["road_segments"]
    assert len(body["blocked_roads"]) == 1

    # Every marker must carry coordinates.
    for marker in body["incidents"]:
        assert marker["latitude"] is not None and marker["longitude"] is not None
    for collection in (body["relief_centres"], body["warehouses"], body["road_nodes"]):
        for marker in collection:
            assert isinstance(marker["latitude"], float)
            assert isinstance(marker["longitude"], float)
    for marker in body["road_segments"]:
        assert marker["from_node_id"] and marker["to_node_id"]
        assert marker["from_node_name"] and marker["to_node_name"]

    blocked = body["blocked_roads"][0]
    assert blocked["is_blocked"] is True
    assert blocked["blockage_reason"]
    assert blocked["from_node_name"] == "Thanjavur Junction"
    assert blocked["to_node_name"] == "Kumbakonam Junction"
