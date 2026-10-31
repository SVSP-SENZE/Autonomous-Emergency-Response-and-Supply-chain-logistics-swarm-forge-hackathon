"""Health endpoint and database connectivity tests."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import text


def test_health_returns_ok(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "connected"
    assert body["version"] == "0.1.0"
    assert body["data_mode"] == "SIMULATED"
    # Timestamp must be timezone-aware.
    assert datetime.fromisoformat(body["timestamp"]).tzinfo is not None


def test_database_connectivity(seeded_db):
    assert seeded_db.execute(text("SELECT 1")).scalar() == 1
