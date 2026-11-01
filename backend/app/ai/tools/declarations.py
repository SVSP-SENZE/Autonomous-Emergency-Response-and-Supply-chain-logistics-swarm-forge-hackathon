"""Groq function declaration registry: name, description, JSON parameters.

Parameters use plain JSON-schema dictionaries here and are converted to
`google.genai.types.Schema` objects on demand (see `build_declarations`), so
the registry stays independent of the SDK.
"""

from __future__ import annotations

EXECUTION_NOTE = (
    "Runs the real ReliefMesh backend against the SIMULATED Thanjavur flood "
    "scenario database. All figures are simulated."
)

DECLARATIONS: list[dict] = [
    {
        "name": "get_situation_overview",
        "description": (
            "Retrieve an overview of the current simulated disaster situation: "
            "KPIs (affected population, active disasters, critical centres, "
            "blocked roads, vehicles), inventory totals, orders by status, "
            "active incidents and critical relief centres. First tool to "
            "consider for overall 'what is happening' questions."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "list_active_incidents",
        "description": (
            "List active (non-resolved) incidents in the simulated "
            "environment with optional filters."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "severity": {
                    "type": "string",
                    "enum": ["low", "medium", "high", "critical"],
                    "description": "Filter by incident severity.",
                },
                "incident_type": {
                    "type": "string",
                    "enum": [
                        "flood",
                        "cyclone",
                        "landslide",
                        "infrastructure_damage",
                        "water_shortage",
                        "fire",
                        "other",
                    ],
                    "description": "Filter by incident type.",
                },
            },
        },
    },
    {
        "name": "get_demand_assessment",
        "description": (
            "Calculate water/food/medical/hygiene requirements, current stock "
            "and shortages for relief centres using the Phase-2 demand "
            "engine, including priority scores and classifications."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "horizon_hours": {
                    "type": "integer",
                    "enum": [6, 12, 24, 48, 72],
                    "description": "Planning horizon in hours (default 24).",
                },
                "relief_centre_name": {
                    "type": "string",
                    "description": (
                        "Optional relief centre name to scope the assessment "
                        "to a single centre (e.g. 'Thanjavur Relief Centre')."
                    ),
                },
            },
        },
    },
    {
        "name": "get_warehouse_inventory",
        "description": (
            "Retrieve current warehouse stock: total, reserved and available "
            "quantities per supply type. Never treat an unavailable "
            "warehouse as dispatchable."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "warehouse_name": {
                    "type": "string",
                    "description": (
                        "Optional warehouse name to scope to one warehouse "
                        "(e.g. 'Chennai Relief Hub'). Omit for all."
                    ),
                },
            },
        },
    },
    {
        "name": "compute_resource_allocation",
        "description": (
            "Compute an optimised multi-warehouse allocation plan with the "
            "Phase-2 greedy allocator. Creates a persisted planning snapshot. "
            "Proposed plan only: no inventory is reserved or deducted."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "horizon_hours": {
                    "type": "integer",
                    "enum": [6, 12, 24, 48, 72],
                    "description": "Planning horizon in hours (default 24).",
                },
            },
        },
    },
    {
        "name": "calculate_safe_route",
        "description": (
            "Calculate the safest reachable route between named endpoints "
            "(warehouses, relief centres or junctions) using the NetworkX "
            "routing engine on the current road network, excluding blocked "
            "segments. Returns distance, travel time, risk and reachability."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "origin_name": {
                    "type": "string",
                    "description": (
                        "Origin endpoint name, e.g. 'Chennai Relief Hub'."
                    ),
                },
                "destination_name": {
                    "type": "string",
                    "description": (
                        "Destination endpoint name, e.g. 'Thanjavur Relief "
                        "Centre'."
                    ),
                },
            },
            "required": ["origin_name", "destination_name"],
        },
    },
    {
        "name": "get_latest_allocation_plan",
        "description": (
            "Retrieve the latest persisted allocation plan snapshot. Does NOT "
            "compute a new plan. Reports clearly when no plan exists."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "explain_relief_centre_priority",
        "description": (
            "Explain the factual factors behind a relief centre's computed "
            "priority: affected population, shortages, stored priority, "
            "operational status, score and classification."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "relief_centre_name": {
                    "type": "string",
                    "description": "Relief centre name, e.g. 'Thanjavur'.",
                },
            },
            "required": ["relief_centre_name"],
        },
    },
]