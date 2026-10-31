"""AI subsystem tests: Gemini client, tool registry and tool handlers.

All tests run against isolated temporary databases and a REAL ReliefMesh
backend (the actual services), never the real Gemini API.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import select

from app.ai.client import GeminiClient, reset_gemini_client
from app.ai.tools.declarations import DECLARATIONS
from app.ai.tools.dispatcher import execute_tool
from app.ai.tools.registry import PLANNING, READ_ONLY, REGISTRY
from app.core.config import Settings
from app.core.exceptions import (
    AiNotConfiguredError,
    AiQuotaError,
    AgentToolError,
    AiUpstreamError,
)
from app.models import Inventory, PlanningRun, RoadNode
from app.models.enums import PlanningType


# --------------------------------------------------------------------------- #
# Gemini client
# --------------------------------------------------------------------------- #


def test_client_requires_api_key():
    with pytest.raises(AiNotConfiguredError):
        GeminiClient("", "gemini-x")
    with pytest.raises(AiNotConfiguredError):
        GeminiClient("   ", "gemini-x")


def test_model_configuration_from_environment(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-fake-key-value")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-settings-flash")
    fresh = Settings()  # built straight from the (patched) environment
    assert fresh.gemini_api_key == "test-fake-key-value"
    assert fresh.gemini_model == "gemini-settings-flash"
    assert fresh.gemini_ready is True
    assert fresh.gemini_max_tool_iterations >= 1


def test_missing_key_keeps_app_serving(monkeypatch):
    reset_gemini_client()
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_ENABLED", "true")
    # get_gemini_client() must surface the same clear error, not crash.
    from app.ai import client as client_module

    monkeypatch.setattr(client_module.settings, "gemini_api_key", "")
    with pytest.raises(AiNotConfiguredError):
        client_module.get_gemini_client()
    reset_gemini_client()


def test_quota_error_translated():
    from app.ai.client import _translate_sdk_error

    translated = _translate_sdk_error(_FakeSdkError("429 RESOURCE_EXHAUSTED quota exceeded"))
    assert isinstance(translated, AiQuotaError)
    auth = _translate_sdk_error(_FakeSdkError("401 API key not valid"))
    assert isinstance(auth, AiUpstreamError)


class _FakeSdkError(Exception):
    def __str__(self) -> str:  # exception text used by the translator
        return self.args[0]


# --------------------------------------------------------------------------- #
# Tool registry declarations
# --------------------------------------------------------------------------- #


def test_every_registered_tool_has_a_valid_declaration():
    from app.ai.tools.declarations import DECLARATIONS

    declared = {declaration["name"] for declaration in DECLARATIONS}
    assert declared == set(REGISTRY)  # registry and declarations stay in sync
    for spec in REGISTRY.values():
        assert spec.category in (READ_ONLY, PLANNING)
        assert spec.name == spec.name.strip()
        assert spec.description.strip()


def test_only_allocation_is_planning_and_no_dispatch_draft_tool_exists():
    assert [name for name, spec in REGISTRY.items() if spec.category == PLANNING] == [
        "compute_resource_allocation",
    ]
    # Phase-5 security regression: draft dispatch-order generation must never be
    # a Gemini-executable tool. It stays an explicit operator-only API action.
    assert "prepare_dispatch_orders" not in REGISTRY
    assert "prepare_dispatch_orders" not in {d["name"] for d in DECLARATIONS}


def test_unknown_tool_rejected(seeded_db):
    with pytest.raises(AgentToolError):
        execute_tool(seeded_db, "destroy_all_data", {})
    with pytest.raises(AgentToolError):
        execute_tool(seeded_db, "__import__('os').system", {})


def test_invalid_tool_arguments_rejected(seeded_db):
    with pytest.raises(AgentToolError):
        execute_tool(seeded_db, "get_demand_assessment", {"horizon_hours": 999})
    with pytest.raises(AgentToolError):
        execute_tool(seeded_db, "get_demand_assessment", {"bogus": True})
    with pytest.raises(AgentToolError):
        execute_tool(
            seeded_db,
            "get_warehouse_inventory",
            {"warehouse_name": "   "},
        )


# --------------------------------------------------------------------------- #
# Tool handlers call the REAL services
# --------------------------------------------------------------------------- #


def test_situation_overview_uses_real_dashboard(seeded_db):
    result, status, summary = execute_tool(seeded_db, "get_situation_overview", {})
    assert status == "success"
    assert result["summary"]["relief_centres"] == 5
    assert result["summary"]["blocked_roads"] == 1
    assert len(result["critical_relief_centres"]) >= 1
    assert result["active_incident_count"] >= 1


def test_list_incidents_filters(seeded_db):
    result, status, _ = execute_tool(
        seeded_db, "list_active_incidents", {"severity": "critical"}
    )
    assert status == "success"
    assert all(i["severity"] == "critical" for i in result["incidents"])
    assert result["count"] >= 1  # the seeded critical Thanjavur flood incident


def test_demand_tool_matches_real_demand_service(seeded_db):
    result, status, _ = execute_tool(
        seeded_db,
        "get_demand_assessment",
        {"horizon_hours": 24, "relief_centre_name": "Thanjavur Relief Centre"},
    )
    assert status == "success"
    assert result["centres_assessed"] == 1
    thanjavur = result["centres"][0]
    water = thanjavur["items"]["water_litre"]
    # Real service figures: 52000 x 3 L/day x 24h.
    assert water["required"] == 156000.0
    assert water["shortage"] == 150000.0
    assert thanjavur["classification"] == "Critical"


def test_allocation_tool_real_service_and_no_inventory_change(seeded_db):
    before = {
        row.id: (row.quantity, row.reserved_quantity)
        for row in seeded_db.scalars(select(Inventory)).all()
    }
    result, status, summary = execute_tool(
        seeded_db, "compute_resource_allocation", {"horizon_hours": 24}
    )
    assert status == "success"
    assert result["planning_run_id"] >= 1
    assert result["summary"]["allocated_by_supply"]["water_litre"] == 228000.0
    after = {
        row.id: (row.quantity, row.reserved_quantity)
        for row in seeded_db.scalars(select(Inventory)).all()
    }
    assert after == before  # proposed plan only
    seeded_db.expire_all()
    run = seeded_db.get(PlanningRun, result["planning_run_id"])
    assert run.planning_type == PlanningType.ALLOCATION


def test_route_tool_uses_real_routing_service(seeded_db):
    result, status, _ = execute_tool(
        seeded_db,
        "calculate_safe_route",
        {"origin_name": "Chennai Relief Hub", "destination_name": "Thanjavur Relief Centre"},
    )
    assert status == "success"
    assert result["reachable"] is True
    assert result["estimated_travel_time_minutes"] == 448
    assert result["distance_km"] == 397.0


def test_route_tool_unreachable_clearly_reported(seeded_db):
    from app.models import RoadSegment

    # Block all remaining approaches to the Kumbakonam junction cluster
    # (the Thanjavur Junction -> Kumbakonam segment is already blocked in seed).
    for from_name, to_name in (
        ("Trichy Bypass", "Kumbakonam Junction"),
        ("Kumbakonam Junction", "Needamangalam Junction"),
    ):
        from_id = seeded_db.scalar(
            select(RoadNode.id).where(RoadNode.node_name == from_name)
        )
        to_id = seeded_db.scalar(
            select(RoadNode.id).where(RoadNode.node_name == to_name)
        )
        segment = seeded_db.scalar(
            select(RoadSegment).where(
                RoadSegment.from_node_id == from_id,
                RoadSegment.to_node_id == to_id,
            )
        )
        segment.is_blocked = True
    seeded_db.commit()

    result, status, _ = execute_tool(
        seeded_db,
        "calculate_safe_route",
        {"origin_name": "Chennai Relief Hub", "destination_name": "Kumbakonam Relief Centre"},
    )
    assert result["reachable"] is False  # never a fabricated fallback route
    assert "No reachable route" in result["message"]


def test_warehouse_inventory_reports_reserved_and_unavailable(seeded_db):
    result, status, _ = execute_tool(
        seeded_db, "get_warehouse_inventory", {"warehouse_name": "Chennai Relief Hub"}
    )
    assert status == "success"
    warehouse = result["warehouses"][0]
    water = next(i for i in warehouse["items"] if i["supply_type"] == "water_litre")
    assert water["total_quantity"] == 120000
    assert water["reserved_quantity"] == 3000
    assert water["available_quantity"] == 117000
    # An unavailable warehouse must not look dispatchable.
    all_inv, _, _ = execute_tool(seeded_db, "get_warehouse_inventory", {})
    assert len(all_inv["warehouses"]) == 3


def test_explain_priority_uses_real_figures(seeded_db):
    result, status, _ = execute_tool(
        seeded_db,
        "explain_relief_centre_priority",
        {"relief_centre_name": "Thanjavur"},
    )
    assert status == "success"
    assert result["priority_score"] == 94.1
    assert result["classification"] == "Critical"
    assert result["factors"]["shortages"]["water_litre"]["shortage"] == 150000.0
    assert result["factors"]["population_component_max_is_100"] == 100.0


def test_latest_allocation_plan_states_absence(seeded_db):
    result, status, _ = execute_tool(seeded_db, "get_latest_allocation_plan", {})
    assert result["exists"] is False  # no plan generated, return is honest


def test_tool_not_found_error_is_structured(seeded_db):
    result, status, summary = execute_tool(
        seeded_db, "get_demand_assessment", {"relief_centre_name": "Atlantis Centre"}
    )
    assert status == "error"
    assert result["status"] == "error"
    assert result["error"]["code"] == "not_found"
    assert "Atlantis" in summary
