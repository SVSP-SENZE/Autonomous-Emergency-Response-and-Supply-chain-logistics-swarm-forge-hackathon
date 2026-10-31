"""ORM models for every ReliefMesh domain entity.

Importing this package registers all models on `Base.metadata`, which is
required before `init_db()` creates the schema.
"""

from app.core.database import Base
from app.models.agent import AgentMessage, AgentRun, AgentSession, AgentToolExecution
from app.models.common import TimestampMixin, UTCDateTime, enum_column
from app.models.enums import (
    DispatchEventType,
    IncidentSource,
    IncidentStatus,
    IncidentType,
    InventoryMovementType,
    NodeType,
    OperationalStatus,
    OrderStatus,
    Priority,
    Severity,
    SimulationEventType,
    SupplyType,
    VehicleStatus,
    VehicleType,
)
from app.models.incident import Incident
from app.models.inventory import Inventory, ReliefCentreInventory
from app.models.inventory_movement import InventoryMovement
from app.models.planning import AllocationResult, PlanningRun
from app.models.relief_centre import ReliefCentre
from app.models.relief_order import DispatchEvent, ReliefOrder, ReliefOrderItem
from app.models.road import RoadNode, RoadSegment
from app.models.simulation_event import SimulationEvent
from app.models.vehicle import Vehicle
from app.models.warehouse import Warehouse

__all__ = [
    "Base",
    "AgentMessage",
    "AgentRun",
    "AgentSession",
    "AgentToolExecution",
    "TimestampMixin",
    "UTCDateTime",
    "enum_column",
    "DispatchEvent",
    "DispatchEventType",
    "Incident",
    "IncidentSource",
    "IncidentStatus",
    "IncidentType",
    "Inventory",
    "InventoryMovement",
    "InventoryMovementType",
    "NodeType",
    "OperationalStatus",
    "OrderStatus",
    "AllocationResult",
    "PlanningRun",
    "PlanningStatus",
    "PlanningType",
    "ReliefCentreInventory",
    "Priority",
    "ReliefCentre",
    "ReliefOrder",
    "ReliefOrderItem",
    "RoadNode",
    "RoadSegment",
    "Severity",
    "SimulationEvent",
    "SimulationEventType",
    "SupplyType",
    "Vehicle",
    "VehicleStatus",
    "VehicleType",
    "Warehouse",
]
