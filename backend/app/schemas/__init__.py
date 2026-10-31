"""API schema exports."""

from app.schemas.common import ListResponse
from app.schemas.dashboard import DashboardKPIs, DashboardResponse, InventoryAggregate
from app.schemas.incident import IncidentCreate, IncidentRead, IncidentUpdate
from app.schemas.map import MapOverviewResponse
from app.schemas.relief_centre import ReliefCentreDetail, ReliefCentreSummary
from app.schemas.relief_order import ReliefOrderItemRead, ReliefOrderRead
from app.schemas.road import RoadNodeRead, RoadSegmentRead
from app.schemas.simulation import (
    SimulationEventCreate,
    SimulationEventRead,
    SimulationEventResult,
    SimulationResetResponse,
)
from app.schemas.vehicle import VehicleDetail, VehicleSummary
from app.schemas.warehouse import InventoryItemRead, WarehouseDetail, WarehouseRead, WarehouseSummary

__all__ = [
    "DashboardKPIs",
    "DashboardResponse",
    "IncidentCreate",
    "IncidentRead",
    "IncidentUpdate",
    "InventoryAggregate",
    "InventoryItemRead",
    "ListResponse",
    "MapOverviewResponse",
    "ReliefCentreDetail",
    "ReliefCentreSummary",
    "ReliefOrderItemRead",
    "ReliefOrderRead",
    "RoadNodeRead",
    "RoadSegmentRead",
    "SimulationEventCreate",
    "SimulationEventRead",
    "SimulationEventResult",
    "SimulationResetResponse",
    "VehicleDetail",
    "VehicleSummary",
    "WarehouseDetail",
    "WarehouseRead",
    "WarehouseSummary",
]
