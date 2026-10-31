"""Central tool registry + dispatcher (controlled function-calling).

Only tools registered here can ever be executed: the dispatcher looks the
model's requested name up in this allowlist, validates arguments with a
Pydantic schema, and calls the mapped handler with the current database
session. Unknown names and malformed arguments never reach business logic.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.ai.tools import (
    allocation_tools,
    demand_tools,
    inventory_tools,
    routing_tools,
    situation_tools,
)
from app.ai.tools.declarations import DECLARATIONS
from app.core.config import settings as _settings  # noqa: F401  (documented logging)
from app.core.exceptions import AgentToolError, NotFoundError
from app.core.planning_config import ALLOWED_HORIZONS
from app.models.enums import IncidentType, Severity

logger = logging.getLogger("reliefmesh.ai.tools")

# --------------------------------------------------------------------------- #
# Argument validation schemas (never let malformed args reach services)
# --------------------------------------------------------------------------- #


class NoArgs(BaseModel):
    """Validation model for parameter-less tools."""

    model_config = ConfigDict(extra="forbid")


class ListIncidentsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity: str | None = Field(default=None)
    incident_type: str | None = Field(default=None)

    @field_validator("severity")
    @classmethod
    def _severity(cls, value: str | None) -> str | None:
        if value is not None and value not in {s.value for s in Severity}:
            raise ValueError(f"severity must be one of {[s.value for s in Severity]}")
        return value

    @field_validator("incident_type")
    @classmethod
    def _incident_type(cls, value: str | None) -> str | None:
        if value is not None and value not in {t.value for t in IncidentType}:
            raise ValueError(
                f"incident_type must be one of {[t.value for t in IncidentType]}"
            )
        return value


class DemandAssessmentArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    horizon_hours: int = Field(default=24)
    relief_centre_name: str | None = Field(default=None)

    @field_validator("horizon_hours")
    @classmethod
    def _horizon(cls, value: int) -> int:
        if value not in ALLOWED_HORIZONS:
            raise ValueError(f"horizon_hours must be one of {ALLOWED_HORIZONS}")
        return value

    @field_validator("relief_centre_name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("relief_centre_name must not be empty")
        return value


class WarehouseInventoryArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    warehouse_name: str | None = Field(default=None)

    @field_validator("warehouse_name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("warehouse_name must not be empty")
        return value


class AllocationArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    horizon_hours: int = Field(default=24)

    @field_validator("horizon_hours")
    @classmethod
    def _horizon(cls, value: int) -> int:
        if value not in ALLOWED_HORIZONS:
            raise ValueError(f"horizon_hours must be one of {ALLOWED_HORIZONS}")
        return value


class SafeRouteArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    origin_name: str = Field(min_length=1)
    destination_name: str = Field(min_length=1)


class ExplainPriorityArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relief_centre_name: str = Field(min_length=1)


# --------------------------------------------------------------------------- #
# Tool specs + allowlist
# --------------------------------------------------------------------------- #

READ_ONLY = "read_only"
PLANNING = "planning"

_DECLARATION_BY_NAME = {declaration["name"]: declaration for declaration in DECLARATIONS}


@dataclass(frozen=True)
class ToolSpec:
    """One registered tool: identity, validation, handler, permission level."""

    name: str
    description: str
    parameters: dict
    validation: type[BaseModel]
    handler: Callable[[Session, BaseModel], dict]
    category: str
    summary_template: str

    def summarise(self, result: dict) -> str:
        """Human-readable one-liner for the execution trace (fails safe)."""

        class _SafeDict(dict):
            def __missing__(self, key: str) -> str:  # pragma: no cover
                return f"<{key}>"

        return self.summary_template.format_map(_SafeDict(result or {}))


def _spec(name: str, category: str, summary_template: str) -> ToolSpec:
    declaration = _DECLARATION_BY_NAME[name]
    handler, validation = HANDLERS[name]
    return ToolSpec(
        name=name,
        description=declaration["description"],
        parameters=declaration["parameters"],
        validation=validation,
        handler=handler,
        category=category,
        summary_template=summary_template,
    )


# name -> (handler, validation model); keep this mapping in one place.
HANDLERS: dict[str, tuple[Callable[[Session, BaseModel], dict], type[BaseModel]]] = {
    "get_situation_overview": (situation_tools.get_situation_overview, NoArgs),
    "list_active_incidents": (situation_tools.list_active_incidents, ListIncidentsArgs),
    "get_demand_assessment": (demand_tools.get_demand_assessment, DemandAssessmentArgs),
    "get_warehouse_inventory": (inventory_tools.get_warehouse_inventory, WarehouseInventoryArgs),
    "compute_resource_allocation": (
        allocation_tools.compute_resource_allocation,
        AllocationArgs,
    ),
    "calculate_safe_route": (routing_tools.calculate_safe_route, SafeRouteArgs),
    "get_latest_allocation_plan": (allocation_tools.latest_allocation_plan, NoArgs),
    "explain_relief_centre_priority": (
        demand_tools.explain_relief_centre_priority,
        ExplainPriorityArgs,
    ),
}


REGISTRY: dict[str, ToolSpec] = {
    "get_situation_overview": _spec(
        "get_situation_overview",
        READ_ONLY,
        "Retrieved situation overview with {active_incident_count} active incident(s)",
    ),
    "list_active_incidents": _spec(
        "list_active_incidents",
        READ_ONLY,
        "Listed {count} active incident(s)",
    ),
    "get_demand_assessment": _spec(
        "get_demand_assessment",
        READ_ONLY,
        "Assessed demand across {centres_assessed} relief centre(s) (horizon {horizon_hours}h)",
    ),
    "get_warehouse_inventory": _spec(
        "get_warehouse_inventory",
        READ_ONLY,
        "Retrieved stock for {warehouse_count} warehouse(s)",
    ),
    "compute_resource_allocation": _spec(
        "compute_resource_allocation",
        PLANNING,
        "Computed allocation plan run {planning_run_id} (fulfilment {fulfilment_pct}%)",
    ),
    "calculate_safe_route": _spec(
        "calculate_safe_route",
        READ_ONLY,
        "Calculated route {origin} -> {destination} (reachable: {reachable})",
    ),
    "get_latest_allocation_plan": _spec(
        "get_latest_allocation_plan",
        READ_ONLY,
        "Retrieved latest allocation plan",
    ),
    "explain_relief_centre_priority": _spec(
        "explain_relief_centre_priority",
        READ_ONLY,
        "Explained priority for {relief_centre}",
    ),
}


# --------------------------------------------------------------------------- #
# Dispatcher (the ONLY execution path: validate -> allowlist -> handler)
# --------------------------------------------------------------------------- #


def execute_tool(db: Session, tool_name: str, arguments: dict[str, Any]) -> tuple[dict, str, str]:
    """Validate and execute one tool call.

    Returns (result, status, summary) where status is 'success' or 'error'.
    Unknown tool names raise AgentToolError immediately; validation and
    handler failures are converted into structured error results so the
    orchestrator can hand them back to the model for explanation.
    """
    spec = REGISTRY.get(tool_name)
    if spec is None:
        raise AgentToolError(
            f"Unknown tool: {tool_name}",
            details={"allowed_tools": sorted(REGISTRY)},
        )
    arguments = arguments if isinstance(arguments, dict) else {}
    try:
        validated = spec.validation.model_validate(arguments)
    except Exception as exc:  # pydantic.ValidationError
        raise AgentToolError(
            f"Invalid arguments for tool {tool_name}",
            details={"errors": str(exc)[:400]},
        ) from exc
    started = time.perf_counter()
    try:
        result = spec.handler(db, validated)
        status = "success"
        summary = spec.summarise(result)
        if spec.category == PLANNING and result.get("note"):
            summary += " (planning only)"
    except AgentToolError:
        raise
    except NotFoundError as exc:
        return (
            {"status": "error", "error": {"code": "not_found", "message": exc.message}},
            "error",
            f"Tool {tool_name} failed: {exc.message}",
        )
    except Exception as exc:  # handler failure -> structured error
        logger.exception("Tool %s execution failed", tool_name)
        return (
            {
                "status": "error",
                "error": {"code": "tool_execution_failed", "message": str(exc)[:300]},
            },
            "error",
            f"Tool {tool_name} failed: {exc.__class__.__name__}",
        )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    logger.info("Tool %s executed in %sms (%s)", tool_name, elapsed_ms, status)
    if status == "success":
        result["execution_time_ms"] = elapsed_ms
    return result, status, summary
