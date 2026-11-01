"""Map overview live-layer and provenance tests.

These tests exercise the map payload WITHOUT any external network access
(conftest disables startup auto-sync, and the live cache starts empty), which
is exactly how graceful degradation must behave when external APIs are
unavailable or have never synced.
"""

from __future__ import annotations

from app.services import map_service
from app.services import live_data_service as live


def test_map_overview_carries_marker_provenance(client):
    """Markers expose source/is_demo so the frontend can hide seeded demo data."""
    body = client.get("/api/v1/map/overview").json()

    assert body["incidents"]
    for marker in body["incidents"]:
        assert "source" in marker
        assert isinstance(marker["is_demo"], bool)

    for collection in (body["relief_centres"], body["warehouses"], body["vehicles"]):
        assert collection
        for marker in collection:
            assert isinstance(marker["is_demo"], bool)


def test_live_layers_degrade_gracefully_without_sync(client):
    """With no live sync yet, layers are unavailable and empty — never demo data."""
    # Force a clean cache: no stations / events / hospitals / alerts.
    live._LIVE_CACHE.update(
        {
            "last_sync_utc": None,
            "status": "initialising",
            "stations": [],
            "nasa_events": [],
            "gdacs": {"alerts": [], "fetched_at": None, "status": "unavailable"},
            "hospitals": {"items": [], "fetched_at": None, "status": "unavailable"},
        }
    )
    body = client.get("/api/v1/map/overview").json()
    layers = body["live_layers"]

    assert layers["weather_stations"] == []
    assert layers["river_gauges"] == []
    assert layers["disaster_events"] == []
    assert layers["facilities"] == []

    statuses = {item["source"]: item for item in layers["statuses"]}
    assert set(statuses) == {
        "open-meteo",
        "open-meteo-flood",
        "nasa-eonet",
        "gdacs",
        "osm-nominatim",
    }
    for item in statuses.values():
        assert item["status"] == "unavailable"


def test_live_layers_render_synced_station_data(client):
    """Synced (fresh) cache data appears as markers with real coordinates."""
    from app.services.map_service import _build_live_layers

    now_iso = live.utcnow().isoformat()
    live._LIVE_CACHE.update(
        {
            "last_sync_utc": now_iso,
            "status": "active",
            "stations": [
                {
                    "name": "Thanjavur Central",
                    "district": "Thanjavur",
                    "latitude": 10.7870,
                    "longitude": 79.1378,
                    "temperature_c": 27.4,
                    "precipitation_mm": 4.2,
                    "daily_precipitation_mm": 18.3,
                    "wind_speed_kmh": 12.0,
                    "wind_gusts_kmh": 18.0,
                    "weather_code": 3,
                    "river": "Vennar / Cauvery Delta",
                    "river_discharge_m3s": 8.7,
                    "synced_at": now_iso,
                }
            ],
            "nasa_events": [
                {
                    "id": "EONET-123",
                    "title": "Flooding in Tamil Nadu",
                    "category": "Floods",
                    "latitude": 11.0,
                    "longitude": 80.0,
                    "date": now_iso,
                    "link": "https://eonet.example/123",
                }
            ],
            "gdacs": {
                "fetched_at": now_iso,
                "status": "ok",
                "alerts": [
                    {
                        "id": "gdacs-1000-e1",
                        "title": "Cyclone Alert Test",
                        "eventtype": "tc",
                        "alert_level": "Orange",
                        "severity_text": "High impact cyclone",
                        "latitude": 13.2,
                        "longitude": 82.1,
                        "occurred_at": now_iso,
                        "last_updated_at": now_iso,
                        "link": None,
                    }
                ],
            },
            "hospitals": {
                "fetched_at": now_iso,
                "status": "ok",
                "items": [
                    {
                        "name": "Umarani Hospital",
                        "display_name": "Umarani Hospital, Thanjavur, Tamil Nadu, India",
                        "town": "Thanjavur",
                        "latitude": 10.7698,
                        "longitude": 79.1124,
                        "osm_id": "256283611",
                        "osm_type": "node",
                    }
                ],
            },
        }
    )
    layers = _build_live_layers()

    # Stations: weather + river markers with EXACT source coordinates.
    assert [station.name for station in layers.weather_stations] == ["Thanjavur Central"]
    weather = layers.weather_stations[0]
    assert (weather.latitude, weather.longitude) == (10.7870, 79.1378)
    assert weather.temperature_c == 27.4
    assert weather.updated_at is not None

    river = layers.river_gauges[0]
    assert (river.latitude, river.longitude) == (10.7870, 79.1378)
    assert river.river_discharge_m3s == 8.7

    # Disaster events: EONET + GDACS, each keeping its source coordinates.
    events = {e.source: e for e in layers.disaster_events}
    assert set(events) == {"NASA EONET", "GDACS"}
    assert (events["NASA EONET"].latitude, events["NASA EONET"].longitude) == (11.0, 80.0)
    assert events["GDACS"].severity is not None
    assert events["GDACS"].severity.value == "high"  # Orange alert

    # Facilities: Nominatim hospital, real coordinates.
    facility = layers.facilities[0]
    assert facility.name == "Umarani Hospital"
    assert (facility.latitude, facility.longitude) == (10.7698, 79.1124)

    # Fresh sync => all statuses ok.
    statuses = {s.source: s.status for s in layers.statuses}
    assert statuses == {
        "open-meteo": "ok",
        "open-meteo-flood": "ok",
        "nasa-eonet": "ok",
        "gdacs": "ok",
        "osm-nominatim": "ok",
    }


def test_live_layer_becomes_stale_when_old(client):
    """Stale cached data is flagged, never silently renamed or replaced."""
    old_iso = "2020-01-01T00:00:00"
    live._LIVE_CACHE.update(
        {
            "last_sync_utc": old_iso,
            "status": "active",
            "stations": [
                {
                    "name": "Old Station",
                    "district": "X",
                    "latitude": 10.0,
                    "longitude": 79.0,
                    "synced_at": old_iso,
                }
            ],
        }
    )
    layers = map_service._build_live_layers()
    statuses = {s.source: s.status for s in layers.statuses}
    assert statuses["open-meteo"] == "stale"
    assert statuses["open-meteo-flood"] == "stale"
