"""Domain enumeration types shared by models and API schemas."""

from __future__ import annotations

from enum import StrEnum


class Severity(StrEnum):
    """Incident / event severity levels."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Priority(StrEnum):
    """Relief centre response priority (shares the severity scale)."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class IncidentType(StrEnum):
    """Broad classification of incidents."""

    FLOOD = "flood"
    CYCLONE = "cyclone"
    LANDSLIDE = "landslide"
    INFRASTRUCTURE_DAMAGE = "infrastructure_damage"
    WATER_SHORTAGE = "water_shortage"
    FIRE = "fire"
    OTHER = "other"


class IncidentSource(StrEnum):
    """Where an incident record originated."""

    WEATHER_API = "weather_api"
    CITIZEN_REPORT = "citizen_report"
    OPERATOR = "operator"
    SIMULATION = "simulation"


class IncidentStatus(StrEnum):
    """Lifecycle of an incident."""

    REPORTED = "reported"
    INVESTIGATING = "investigating"
    ACTIVE = "active"
    RESOLVED = "resolved"


class OperationalStatus(StrEnum):
    """Operational state of warehouses / relief centres."""

    OPERATIONAL = "operational"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class SupplyType(StrEnum):
    """Relief supply categories."""

    FOOD_KIT = "food_kit"
    WATER_LITRE = "water_litre"
    MEDICAL_KIT = "medical_kit"
    HYGIENE_KIT = "hygiene_kit"


class VehicleType(StrEnum):
    TRUCK = "truck"
    VAN = "van"
    DRONE = "drone"


class VehicleStatus(StrEnum):
    AVAILABLE = "available"
    ASSIGNED = "assigned"
    IN_TRANSIT = "in_transit"
    DELAYED = "delayed"
    MAINTENANCE = "maintenance"


class NodeType(StrEnum):
    WAREHOUSE = "warehouse"
    JUNCTION = "junction"
    RELIEF_CENTRE = "relief_centre"


class OrderStatus(StrEnum):
    """Lifecycle of a relief/dispatch order (Phase 4 adds `delayed`)."""

    DRAFT = "draft"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    DISPATCHED = "dispatched"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    DELAYED = "delayed"


class SimulationEventType(StrEnum):
    """Supported simulated event types for `/simulation/events`."""

    BRIDGE_COLLAPSE = "bridge_collapse"
    ROAD_BLOCKED = "road_blocked"
    WAREHOUSE_UNAVAILABLE = "warehouse_unavailable"
    RELIEF_CENTRE_WATER_SHORTAGE = "relief_centre_water_shortage"
    NEW_FLOOD_REPORT = "new_flood_report"
    RAINFALL_ESCALATION = "rainfall_escalation"
    VEHICLE_BREAKDOWN = "vehicle_breakdown"


class PlanningType(StrEnum):
    """Type of persisted planning run (audit trail for planning operations)."""

    DEMAND = "demand"
    ALLOCATION = "allocation"
    ROUTE_CALCULATION = "route_calculation"
    ROUTE_RECALCULATION = "route_recalculation"


class PlanningStatus(StrEnum):
    """Lifecycle of a planning run."""

    COMPLETED = "completed"
    FAILED = "failed"


class DispatchEventType(StrEnum):
    """Historical dispatch lifecycle events (append-only DispatchEvent rows)."""

    ORDER_GENERATED = "order_generated"
    ORDER_REGENERATED = "order_regenerated"
    VEHICLE_ASSIGNED = "vehicle_assigned"
    ORDER_APPROVED = "order_approved"
    INVENTORY_RESERVED = "inventory_reserved"
    VEHICLE_DISPATCHED = "vehicle_dispatched"
    DELIVERY_STARTED = "delivery_started"
    PROGRESS_ADVANCED = "progress_advanced"
    ROUTE_RECALCULATED = "route_recalculated"
    VEHICLE_DELAYED = "vehicle_delayed"
    VEHICLE_REASSIGNED = "vehicle_reassigned"
    DELIVERY_COMPLETED = "delivery_completed"
    ORDER_CANCELLED = "order_cancelled"


class InventoryMovementType(StrEnum):
    """Inventory movement ledger entry types (Phase 4 auditability)."""

    RESERVED = "reserved"
    DISPATCHED = "dispatched"
    DELIVERED = "delivered"
    RESERVATION_RELEASED = "reservation_released"


__all__ = [
    "DispatchEventType",
    "IncidentSource",
    "IncidentStatus",
    "IncidentType",
    "InventoryMovementType",
    "NodeType",
    "OperationalStatus",
    "OrderStatus",
    "PlanningStatus",
    "PlanningType",
    "Priority",
    "Severity",
    "SimulationEventType",
    "SupplyType",
    "VehicleStatus",
    "VehicleType",
]
