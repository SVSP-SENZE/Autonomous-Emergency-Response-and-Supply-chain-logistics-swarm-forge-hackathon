"""Agent endpoint + orchestrator tests (Gemini fully mocked).

The tests exercise the REAL orchestrator loop against the REAL backend
services and an isolated test database; only the Gemini model calls are
replaced with a scripted fake client via the FastAPI dependency override.
"""

from __future__ import annotations

import pytest

from app.ai.client import get_gemini_client, reset_gemini_client
from app.core.config import settings
from app.main import app
from app.models import AgentRun, AgentSession, AgentToolExecution, Inventory, PlanningRun
from app.models.enums import PlanningType
from sqlalchemy import select
from tests.ai_mocks import FakeGeminiClient, FakeResponse, function_call_response, text_response


def _use_fake(fake: FakeGeminiClient) -> None:
    """Route agent chat through the scripted fake instead of real Gemini."""
    app.dependency_overrides[get_gemini_client] = lambda: fake


def _chat(client, message: str, session_id: int | None = None):
    payload = {"message": message}
    if session_id is not None:
        payload["session_id"] = session_id
    return client.post("/api/v1/agent/chat", json=payload)


# --------------------------------------------------------------------------- #
# Simple conversation (no tools)
# --------------------------------------------------------------------------- #


def test_chat_without_tools_end_to_end(client, session_factory):
    fake = FakeGeminiClient([text_response("All systems nominal. No action required.")])
    _use_fake(fake)
    response = _chat(client, "Give me a quick status update.")
    assert response.status_code == 201
    body = response.json()
    assert body["data_mode"] == "SIMULATED"
    assert body["status"] == "completed"
    assert body["assistant_message"] == "All systems nominal. No action required."
    assert body["tool_calls"] == []

    with session_factory() as db:
        session = db.get(AgentSession, body["session_id"])
        assert session is not None
        assert "status update" in session.session_title
        assert [m.role for m in session.messages] == ["user", "assistant"]
        run = db.get(AgentRun, body["run_id"])
        assert run.status == "completed"
        assert run.tool_call_count == 0
        assert run.model_name == "gemini-3.8-flash"


def test_generation_config_declares_the_full_tool_registry(client):
    fake = FakeGeminiClient([text_response("ok")])
    _use_fake(fake)
    _chat(client, "hello")
    config = fake.last_config
    declared = {d.name for d in config.tools[0].function_declarations}
    assert len(declared) == 8
    assert "compute_resource_allocation" in declared
    assert "prepare_dispatch_orders" not in declared
    assert config.temperature == settings.gemini_temperature
    assert config.max_output_tokens == settings.gemini_max_output_tokens


# --------------------------------------------------------------------------- #
# Tool round-trips (real handlers, real DB results)
# --------------------------------------------------------------------------- #


def test_chat_with_tool_round_trip_real_result(client, session_factory):
    fake = FakeGeminiClient(
        [
            function_call_response("get_situation_overview", {}),
            text_response("Overview: the Thanjavur flood is the critical incident."),
        ]
    )
    _use_fake(fake)
    response = _chat(client, "What is the current situation?")
    assert response.status_code == 201
    body = response.json()
    assert len(body["tool_calls"]) == 1
    call = body["tool_calls"][0]
    assert call["tool_name"] == "get_situation_overview"
    assert call["status"] == "success"
    assert "active incident" in call["summary"]

    # The function response reached the model as the last content part.
    function_part = fake.requests[1][-1].parts[0]
    assert function_part.function_response.name == "get_situation_overview"
    payload = function_part.function_response.response
    assert payload["status"] == "success"
    assert payload["result"]["summary"]["relief_centres"] == 5

    with session_factory() as db:
        execution = db.scalars(
            select(AgentToolExecution).where(AgentToolExecution.agent_run_id == body["run_id"])
        ).one()
        assert execution.status == "success"
        assert execution.result_json["summary"]["blocked_roads"] == 1


def test_chat_multi_tool_sequential_flow(client, session_factory):
    fake = FakeGeminiClient(
        [
            function_call_response("list_active_incidents", {}),
            function_call_response("get_warehouse_inventory", {"warehouse_name": "Chennai Relief Hub"}),
            text_response("Two incidents active; Chennai hub holds water stock."),
        ]
    )
    _use_fake(fake)
    response = _chat(client, "What incidents are active and what do we have in Chennai?")
    assert response.status_code == 201
    body = response.json()
    assert [c["tool_name"] for c in body["tool_calls"]] == [
        "list_active_incidents",
        "get_warehouse_inventory",
    ]

    with session_factory() as db:
        executions = db.scalars(
            select(AgentToolExecution)
            .where(AgentToolExecution.agent_run_id == body["run_id"])
            .order_by(AgentToolExecution.id)
        ).all()
        assert [e.tool_name for e in executions] == [
            "list_active_incidents",
            "get_warehouse_inventory",
        ]
        # The Chennai water row is real DB data, not invented by the model.
        water = next(
            i
            for i in executions[1].result_json["warehouses"][0]["items"]
            if i["supply_type"] == "water_litre"
        )
        assert water["total_quantity"] == 120000


def test_unknown_tool_rejected_then_model_explains(client, session_factory):
    fake = FakeGeminiClient(
        [
            function_call_response("delete_all_incidents", {}),
            text_response("That tool is not part of my allowlist, so I cannot run it."),
        ]
    )
    _use_fake(fake)
    response = _chat(client, "delete all incidents")
    assert response.status_code == 201  # turn completes; model explains refusal
    body = response.json()
    assert body["tool_calls"][0]["status"] == "error"

    with session_factory() as db:
        execution = db.scalars(
            select(AgentToolExecution).where(AgentToolExecution.agent_run_id == body["run_id"])
        ).one()
        assert execution.status == "error"
        assert execution.result_json["error"]["code"] == "agent_tool_error"
    # The error payload handed back to the model is structured.
    function_part = fake.requests[1][-1].parts[0]
    assert function_part.function_response.response["status"] == "error"


def test_invalid_tool_arguments_rejected(client):
    fake = FakeGeminiClient(
        [
            function_call_response("get_demand_assessment", {"horizon_hours": 999}),
            text_response("The horizon must be one of the allowed values."),
        ]
    )
    _use_fake(fake)
    response = _chat(client, "Demand for the next 999 hours")
    assert response.status_code == 201
    body = response.json()
    assert body["tool_calls"][0]["status"] == "error"

    function_part = fake.requests[1][-1].parts[0]
    payload = function_part.function_response.response
    assert payload["status"] == "error"
    assert payload["error"]["code"] == "agent_tool_error"


def test_tool_not_found_returned_honestly_to_model(client):
    fake = FakeGeminiClient(
        [
            function_call_response(
                "calculate_safe_route",
                {"origin_name": "Atlantis Hub", "destination_name": "Thanjavur Relief Centre"},
            ),
            text_response("I could not resolve that origin."),
        ]
    )
    _use_fake(fake)
    response = _chat(client, "Route from Atlantis Hub to Thanjavur")
    assert response.status_code == 201
    body = response.json()
    assert body["tool_calls"][0]["status"] == "error"

    function_part = fake.requests[1][-1].parts[0]
    payload = function_part.function_response.response
    assert payload["error"]["code"] == "not_found"


# --------------------------------------------------------------------------- #
# Configuration / failure handling
# --------------------------------------------------------------------------- #


def test_missing_api_key_returns_503_but_app_keeps_serving(client, monkeypatch):
    from app.ai import client as client_module

    monkeypatch.setattr(client_module.settings, "gemini_api_key", "")
    reset_gemini_client()
    try:
        response = _chat(client, "hello")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "ai_not_configured"
        # The rest of the application is unaffected.
        assert client.get("/api/v1/dashboard/summary").status_code == 200
        status_response = client.get("/api/v1/agent/status")
        assert status_response.status_code == 200
        assert status_response.json()["status"] == "not_configured"
        assert status_response.json()["api_key_configured"] is False
    finally:
        reset_gemini_client()


def test_quota_error_maps_to_429_and_run_failed(client, session_factory):
    from app.core.exceptions import AiQuotaError

    fake = FakeGeminiClient([AiQuotaError("quota exhausted for today")])
    _use_fake(fake)
    response = _chat(client, "plan something")
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "ai_quota_exceeded"

    with session_factory() as db:
        runs = db.scalars(select(AgentRun)).all()
        assert len(runs) == 1
        assert runs[0].status == "failed"
        assert "AiQuotaError" in runs[0].error_message
        session = db.get(AgentSession, runs[0].session_id)
        # The user message is retained; no fabricated assistant reply exists.
        assert [m.role for m in session.messages] == ["user"]


def test_malformed_empty_response_maps_to_502(client, session_factory):
    fake = FakeGeminiClient([FakeResponse([])])  # candidate with no parts
    _use_fake(fake)
    response = _chat(client, "hello")
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "ai_upstream_error"

    with session_factory() as db:
        run = db.scalars(select(AgentRun)).one()
        assert run.status == "failed"
        assert run.final_response is None


def test_iteration_limit_enforced(client, session_factory, monkeypatch):
    monkeypatch.setattr(settings, "gemini_max_tool_iterations", 2)
    fake = FakeGeminiClient(
        [
            function_call_response("get_situation_overview", {}),
            function_call_response("get_situation_overview", {}),
        ]
    )
    _use_fake(fake)
    response = _chat(client, "loop forever")
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "agent_run_failed"

    with session_factory() as db:
        run = db.scalars(select(AgentRun)).one()
        assert run.status == "failed"
        assert run.tool_call_count == 2
        assert db.scalars(select(AgentToolExecution)).all().__len__() == 2


def test_tool_call_budget_enforced(client, session_factory, monkeypatch):
    monkeypatch.setattr(settings, "gemini_max_tool_calls", 2)
    fake = FakeGeminiClient(
        [
            function_call_response("list_active_incidents", {}),
            function_call_response("list_active_incidents", {}),
            function_call_response("list_active_incidents", {}),
        ]
    )
    _use_fake(fake)
    response = _chat(client, "list incidents repeatedly")
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "agent_run_failed"

    with session_factory() as db:
        executions = db.scalars(select(AgentToolExecution)).all()
        assert len(executions) == 2  # the third call was blocked


# --------------------------------------------------------------------------- #
# Session persistence + history window
# --------------------------------------------------------------------------- #


def test_session_history_is_reused_across_turns(client, session_factory):
    fake1 = FakeGeminiClient([text_response("First answer")])
    _use_fake(fake1)
    first = _chat(client, "What is happening?")
    assert first.status_code == 201
    session_id = first.json()["session_id"]

    fake2 = FakeGeminiClient([text_response("Second answer, building on the first.")])
    _use_fake(fake2)
    second = _chat(client, "And the warehouses?", session_id=session_id)
    assert second.status_code == 201
    assert second.json()["session_id"] == session_id

    # History window: previous user + assistant messages precede the new one.
    history_contents = fake2.requests[0]
    roles = [c.role for c in history_contents]
    texts = [c.parts[0].text for c in history_contents]
    assert roles[:3] == ["user", "model", "user"]
    assert texts[0] == "What is happening?"
    assert texts[1] == "First answer"
    assert texts[2] == "And the warehouses?"

    detail = client.get(f"/api/v1/agent/sessions/{session_id}")
    assert detail.status_code == 200
    assert len(detail.json()["messages"]) == 4
    assert detail.json()["messages"][1]["role"] == "assistant"


def test_unknown_session_id_is_404(client):
    response = _chat(client, "hello", session_id=987654)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_session_and_run_404s(client):
    assert client.get("/api/v1/agent/sessions/987654").status_code == 404
    assert client.get("/api/v1/agent/runs/987654").status_code == 404


def test_status_endpoint_never_leaks_key(client, monkeypatch):
    from app.ai import client as client_module

    real_key = settings.gemini_api_key
    monkeypatch.setattr(client_module.settings, "gemini_api_key", "unit-test-secret-key")
    reset_gemini_client()
    try:
        response = client.get("/api/v1/agent/status")
        assert response.status_code == 200
        body = response.json()
        assert body["api_key_configured"] is True
        assert body["model"] == settings.gemini_model
        assert body["data_mode"] == "SIMULATED"
        assert "unit-test-secret-key" not in response.text
        assert real_key not in response.text
    finally:
        reset_gemini_client()


def test_run_detail_exposes_safe_trace(client, session_factory):
    fake = FakeGeminiClient(
        [
            function_call_response("get_demand_assessment", {"horizon_hours": 24}),
            text_response("Thanjavur is critical."),
        ]
    )
    _use_fake(fake)
    created = _chat(client, "Assess demand")
    run_id = created.json()["run_id"]

    detail = client.get(f"/api/v1/agent/runs/{run_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["status"] == "completed"
    assert body["user_message"] == "Assess demand"
    assert body["assistant_message"] == "Thanjavur is critical."
    execution = body["tool_executions"][0]
    assert execution["tool_name"] == "get_demand_assessment"
    assert execution["arguments_json"] == {"horizon_hours": 24}
    assert execution["status"] == "success"
    assert execution["execution_time_ms"] >= 0
    assert "centres" in execution["result_json"]


# --------------------------------------------------------------------------- #
# Spec integration conversations (mocked model, real tools + data)
# --------------------------------------------------------------------------- #


def test_conversation_flood_thanjavur_real_demand(client, session_factory):
    fake = FakeGeminiClient(
        [
            function_call_response("get_demand_assessment", {"horizon_hours": 24}),
            text_response("Thanjavur faces a critical water shortage."),
        ]
    )
    _use_fake(fake)
    response = _chat(
        client,
        "A flood is affecting Thanjavur. What is the demand situation?",
    )
    assert response.status_code == 201
    run_id = response.json()["run_id"]

    detail = client.get(f"/api/v1/agent/runs/{run_id}")
    result = detail.json()["tool_executions"][0]["result_json"]
    thanjavur = next(c for c in result["centres"] if "Thanjavur" in c["relief_centre"])
    water = thanjavur["items"]["water_litre"]
    assert water["required"] == 156000.0
    assert water["shortage"] == 150000.0
    assert thanjavur["classification"] == "Critical"
    # A demand read must not quietly create planning data.
    with session_factory() as db:
        assert db.scalars(select(PlanningRun)).all() == []


def test_conversation_allocate_plan_real_plan_inventory_unchanged(client, session_factory):
    with session_factory() as db:
        inventory_before = {
            row.id: (row.quantity, row.reserved_quantity)
            for row in db.scalars(select(Inventory)).all()
        }

    fake = FakeGeminiClient(
        [
            function_call_response("compute_resource_allocation", {"horizon_hours": 24}),
            text_response("Plan computed; awaiting operator approval."),
        ]
    )
    _use_fake(fake)
    response = _chat(client, "Generate an allocation plan for the next 24 hours.")
    assert response.status_code == 201
    run_id = response.json()["run_id"]

    detail = client.get(f"/api/v1/agent/runs/{run_id}")
    result = detail.json()["tool_executions"][0]["result_json"]
    assert result["summary"]["allocated_by_supply"]["water_litre"] == 228000.0
    assert abs(result["summary"]["fulfilment_percentage"] - 61.84) < 0.1

    with session_factory() as db:
        inventory_after = {
            row.id: (row.quantity, row.reserved_quantity)
            for row in db.scalars(select(Inventory)).all()
        }
        assert inventory_after == inventory_before  # proposed plan only
        run = db.get(PlanningRun, result["planning_run_id"])
        assert run.planning_type == PlanningType.ALLOCATION


def test_conversation_safe_route_chennai_to_thanjavur(client):
    fake = FakeGeminiClient(
        [
            function_call_response(
                "calculate_safe_route",
                {"origin_name": "Chennai Relief Hub", "destination_name": "Thanjavur Relief Centre"},
            ),
            text_response("The safest route takes about 448 minutes."),
        ]
    )
    _use_fake(fake)
    response = _chat(client, "Find a safe route from Chennai to Thanjavur.")
    assert response.status_code == 201
    run_id = response.json()["run_id"]

    detail = client.get(f"/api/v1/agent/runs/{run_id}")
    result = detail.json()["tool_executions"][0]["result_json"]
    assert result["reachable"] is True
    assert result["estimated_travel_time_minutes"] == 448
    assert result["distance_km"] == 397.0
    assert result["route_risk"] > 0


def test_conversation_blocked_segment_detected_via_tool(client):
    fake = FakeGeminiClient(
        [
            function_call_response(
                "calculate_safe_route",
                {"origin_name": "Chennai Relief Hub", "destination_name": "Kumbakonam Relief Centre"},
            ),
            text_response("Kumbakonam is currently unreachable from Chennai."),
        ]
    )
    _use_fake(fake)
    response = _chat(client, "Can we reach Kumbakonam?")
    run_id = response.json()["run_id"]
    detail = client.get(f"/api/v1/agent/runs/{run_id}")
    result = detail.json()["tool_executions"][0]["result_json"]
    assert result["reachable"] is True
    assert len(result["route_nodes"]) >= 2
    assert result["estimated_travel_time_minutes"] > 0
