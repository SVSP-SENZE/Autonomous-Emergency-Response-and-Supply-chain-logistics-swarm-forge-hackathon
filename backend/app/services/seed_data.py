"""Deterministic demo dataset: Thanjavur district flood scenario (SIMULATED).

All records below are plausible-looking but fabricated demo data for the Forge
hackathon. Nothing here represents a real emergency. Every seeded row is
flagged `is_demo=True` so the simulation reset can restore the initial
scenario without touching operator-created data.
"""

from __future__ import annotations

from typing import Any, TypedDict, Final

from app.models.enums import (
    IncidentSource,
    SimulationEventType,
    IncidentStatus,
    IncidentType,
    NodeType,
    OperationalStatus,
    OrderStatus,
    Priority,
    Severity,
    SupplyType,
    VehicleStatus,
    VehicleType,
)


class WarehouseSeed(TypedDict):
    name: str
    location_name: str
    latitude: float
    longitude: float
    operational_status: OperationalStatus
    storage_capacity: int


class SupplySeed(TypedDict):
    supply_type: SupplyType
    quantity: int
    reserved_quantity: int
    unit: str


class ReliefCentreSeed(TypedDict):
    name: str
    district: str
    latitude: float
    longitude: float
    affected_population: int
    priority: Priority
    operational_status: OperationalStatus
    water_shortage: bool
    water_shortage_notes: str | None


class VehicleSeed(TypedDict):
    vehicle_code: str
    vehicle_type: VehicleType
    capacity: int
    current_location: str
    current_latitude: float
    current_longitude: float
    status: VehicleStatus
    warehouse: str | None


class NodeSeed(TypedDict):
    node_name: str
    node_type: NodeType
    latitude: float
    longitude: float
    linked: tuple[str, str] | None  # (entity kind, warehouse/centre name)


class SegmentSeed(TypedDict):
    from_node: str
    to_node: str
    distance_km: float
    estimated_travel_time_minutes: int
    risk_factor: float
    is_blocked: bool
    blockage_reason: str | None


class IncidentSeed(TypedDict):
    incident_type: IncidentType
    title: str
    description: str
    source: IncidentSource
    severity: Severity
    status: IncidentStatus
    location_name: str
    latitude: float
    longitude: float
    affected_population: int
    metadata: dict[str, Any]
    hours_ago: float


class OrderSeed(TypedDict):
    order_code: str
    warehouse: str
    relief_centre: str
    vehicle: str | None
    status: OrderStatus
    priority: Priority
    estimated_travel_time_minutes: int
    route_metadata: dict[str, Any]
    items: list[dict[str, Any]]
    hours_ago: float


# --------------------------------------------------------------------------- #
# Warehouses
# --------------------------------------------------------------------------- #

WAREHOUSES: Final[list[WarehouseSeed]] = [
    {
        "name": "Chennai Relief Hub",
        "location_name": "Chennai, Tamil Nadu",
        "latitude": 13.0827,
        "longitude": 80.2707,
        "operational_status": OperationalStatus.OPERATIONAL,
        "storage_capacity": 250000,
    },
    {
        "name": "Tiruchirappalli Regional Warehouse",
        "location_name": "Tiruchirappalli, Tamil Nadu",
        "latitude": 10.7905,
        "longitude": 78.7047,
        "operational_status": OperationalStatus.OPERATIONAL,
        "storage_capacity": 180000,
    },
    {
        "name": "Madurai Distribution Centre",
        "location_name": "Madurai, Tamil Nadu",
        "latitude": 9.9252,
        "longitude": 78.1198,
        "operational_status": OperationalStatus.OPERATIONAL,
        "storage_capacity": 120000,
    },
]

INVENTORY: Final[dict[str, list[SupplySeed]]] = {
    "Chennai Relief Hub": [
        {"supply_type": SupplyType.WATER_LITRE, "quantity": 120000, "reserved_quantity": 3000, "unit": "litres"},
        {"supply_type": SupplyType.FOOD_KIT, "quantity": 15000, "reserved_quantity": 0, "unit": "kits"},
        {"supply_type": SupplyType.MEDICAL_KIT, "quantity": 3200, "reserved_quantity": 0, "unit": "kits"},
        {"supply_type": SupplyType.HYGIENE_KIT, "quantity": 5400, "reserved_quantity": 200, "unit": "kits"},
    ],
    "Tiruchirappalli Regional Warehouse": [
        {"supply_type": SupplyType.WATER_LITRE, "quantity": 65000, "reserved_quantity": 2000, "unit": "litres"},
        {"supply_type": SupplyType.FOOD_KIT, "quantity": 8200, "reserved_quantity": 400, "unit": "kits"},
        {"supply_type": SupplyType.MEDICAL_KIT, "quantity": 1800, "reserved_quantity": 0, "unit": "kits"},
        {"supply_type": SupplyType.HYGIENE_KIT, "quantity": 2600, "reserved_quantity": 0, "unit": "kits"},
    ],
    "Madurai Distribution Centre": [
        {"supply_type": SupplyType.WATER_LITRE, "quantity": 48000, "reserved_quantity": 0, "unit": "litres"},
        {"supply_type": SupplyType.FOOD_KIT, "quantity": 6000, "reserved_quantity": 0, "unit": "kits"},
        {"supply_type": SupplyType.MEDICAL_KIT, "quantity": 1200, "reserved_quantity": 0, "unit": "kits"},
        {"supply_type": SupplyType.HYGIENE_KIT, "quantity": 1900, "reserved_quantity": 0, "unit": "kits"},
    ],
}

# --------------------------------------------------------------------------- #
# Relief centres
# --------------------------------------------------------------------------- #

RELIEF_CENTRES: Final[list[ReliefCentreSeed]] = [
    {
        "name": "Thanjavur Relief Centre",
        "district": "Thanjavur",
        "latitude": 10.787,
        "longitude": 79.1378,
        "affected_population": 52000,
        "priority": Priority.CRITICAL,
        "operational_status": OperationalStatus.OPERATIONAL,
        "water_shortage": False,
        "water_shortage_notes": None,
    },
    {
        "name": "Kumbakonam Relief Centre",
        "district": "Thanjavur",
        "latitude": 10.9601,
        "longitude": 79.3845,
        "affected_population": 38000,
        "priority": Priority.HIGH,
        "operational_status": OperationalStatus.OPERATIONAL,
        "water_shortage": False,
        "water_shortage_notes": None,
    },
    {
        "name": "Orathanadu Relief Centre",
        "district": "Thanjavur",
        "latitude": 10.628,
        "longitude": 79.261,
        "affected_population": 21000,
        "priority": Priority.MEDIUM,
        "operational_status": OperationalStatus.OPERATIONAL,
        "water_shortage": False,
        "water_shortage_notes": None,
    },
    {
        "name": "Pattukkottai Relief Centre",
        "district": "Thanjavur",
        "latitude": 10.431,
        "longitude": 79.319,
        "affected_population": 26000,
        "priority": Priority.HIGH,
        "operational_status": OperationalStatus.DEGRADED,
        "water_shortage": True,
        "water_shortage_notes": "Borewell water contaminated; tanker supply required (simulated).",
    },
    {
        "name": "Needamangalam Relief Centre",
        "district": "Tiruvarur",
        "latitude": 10.772,
        "longitude": 79.416,
        "affected_population": 18000,
        "priority": Priority.MEDIUM,
        "operational_status": OperationalStatus.OPERATIONAL,
        "water_shortage": False,
        "water_shortage_notes": None,
    },
]

# --------------------------------------------------------------------------- #
# Vehicles
# --------------------------------------------------------------------------- #

VEHICLES: Final[list[VehicleSeed]] = [
    {
        "vehicle_code": "TRK-01", "vehicle_type": VehicleType.TRUCK, "capacity": 12000,
        "current_location": "Tiruchirappalli Regional Warehouse", "current_latitude": 10.7905,
        "current_longitude": 78.7047, "status": VehicleStatus.AVAILABLE,
        "warehouse": "Tiruchirappalli Regional Warehouse",
    },
    {
        "vehicle_code": "TRK-02", "vehicle_type": VehicleType.TRUCK, "capacity": 15000,
        "current_location": "Chennai Relief Hub", "current_latitude": 13.0827,
        "current_longitude": 80.2707, "status": VehicleStatus.AVAILABLE,
        "warehouse": "Chennai Relief Hub",
    },
    {
        "vehicle_code": "TRK-03", "vehicle_type": VehicleType.TRUCK, "capacity": 10000,
        "current_location": "En route to Pattukkottai Relief Centre (NH-32)",
        "current_latitude": 11.35, "current_longitude": 79.85,
        "status": VehicleStatus.IN_TRANSIT, "warehouse": "Chennai Relief Hub",
    },
    {
        "vehicle_code": "TRK-04", "vehicle_type": VehicleType.TRUCK, "capacity": 18000,
        "current_location": "Madurai Distribution Centre", "current_latitude": 9.9252,
        "current_longitude": 78.1198, "status": VehicleStatus.AVAILABLE,
        "warehouse": "Madurai Distribution Centre",
    },
    {
        "vehicle_code": "TRK-05", "vehicle_type": VehicleType.TRUCK, "capacity": 9000,
        "current_location": "Tiruchirappalli Regional Warehouse", "current_latitude": 10.7905,
        "current_longitude": 78.7047, "status": VehicleStatus.AVAILABLE,
        "warehouse": "Tiruchirappalli Regional Warehouse",
    },
    {
        "vehicle_code": "VAN-01", "vehicle_type": VehicleType.VAN, "capacity": 3500,
        "current_location": "Thanjavur Relief Centre", "current_latitude": 10.787,
        "current_longitude": 79.1378, "status": VehicleStatus.AVAILABLE, "warehouse": None,
    },
    {
        "vehicle_code": "VAN-02", "vehicle_type": VehicleType.VAN, "capacity": 2500,
        "current_location": "Tiruchirappalli Regional Warehouse", "current_latitude": 10.7905,
        "current_longitude": 78.7047, "status": VehicleStatus.ASSIGNED,
        "warehouse": "Tiruchirappalli Regional Warehouse",
    },
    {
        "vehicle_code": "VAN-03", "vehicle_type": VehicleType.VAN, "capacity": 3000,
        "current_location": "Kumbakonam staging yard", "current_latitude": 10.9601,
        "current_longitude": 79.3845, "status": VehicleStatus.DELAYED, "warehouse": None,
    },
    {
        "vehicle_code": "VAN-04", "vehicle_type": VehicleType.VAN, "capacity": 2200,
        "current_location": "Madurai workshop", "current_latitude": 9.93,
        "current_longitude": 78.14, "status": VehicleStatus.MAINTENANCE,
        "warehouse": "Madurai Distribution Centre",
    },
    {
        "vehicle_code": "VAN-05", "vehicle_type": VehicleType.VAN, "capacity": 2800,
        "current_location": "Chennai Relief Hub", "current_latitude": 13.0827,
        "current_longitude": 80.2707, "status": VehicleStatus.AVAILABLE,
        "warehouse": "Chennai Relief Hub",
    },
    {
        "vehicle_code": "VAN-06", "vehicle_type": VehicleType.VAN, "capacity": 2000,
        "current_location": "Madurai Distribution Centre", "current_latitude": 9.9252,
        "current_longitude": 78.1198, "status": VehicleStatus.AVAILABLE,
        "warehouse": "Madurai Distribution Centre",
    },
    {
        "vehicle_code": "DRN-01", "vehicle_type": VehicleType.DRONE, "capacity": 50,
        "current_location": "Tiruchirappalli Regional Warehouse", "current_latitude": 10.7905,
        "current_longitude": 78.7047, "status": VehicleStatus.AVAILABLE,
        "warehouse": "Tiruchirappalli Regional Warehouse",
    },
    {
        "vehicle_code": "DRN-02", "vehicle_type": VehicleType.DRONE, "capacity": 40,
        "current_location": "Madurai Distribution Centre", "current_latitude": 9.9252,
        "current_longitude": 78.1198, "status": VehicleStatus.AVAILABLE,
        "warehouse": "Madurai Distribution Centre",
    },
    {
        "vehicle_code": "DRN-03", "vehicle_type": VehicleType.DRONE, "capacity": 30,
        "current_location": "Chennai drone pad", "current_latitude": 13.0827,
        "current_longitude": 80.2707, "status": VehicleStatus.MAINTENANCE,
        "warehouse": "Chennai Relief Hub",
    },
]

# --------------------------------------------------------------------------- #
# Simulated road network (graph)
# --------------------------------------------------------------------------- #

ROAD_NODES: Final[list[NodeSeed]] = [
    {"node_name": "Chennai Hub", "node_type": NodeType.WAREHOUSE, "latitude": 13.0827, "longitude": 80.2707, "linked": ("warehouse", "Chennai Relief Hub")},
    {"node_name": "Chennai Bypass", "node_type": NodeType.JUNCTION, "latitude": 13.0, "longitude": 80.2, "linked": None},
    {"node_name": "Trichy Warehouse", "node_type": NodeType.WAREHOUSE, "latitude": 10.7905, "longitude": 78.7047, "linked": ("warehouse", "Tiruchirappalli Regional Warehouse")},
    {"node_name": "Trichy Bypass", "node_type": NodeType.JUNCTION, "latitude": 10.82, "longitude": 78.75, "linked": None},
    {"node_name": "Madurai Warehouse", "node_type": NodeType.WAREHOUSE, "latitude": 9.9252, "longitude": 78.1198, "linked": ("warehouse", "Madurai Distribution Centre")},
    {"node_name": "Madurai Bypass", "node_type": NodeType.JUNCTION, "latitude": 9.95, "longitude": 78.15, "linked": None},
    {"node_name": "Thanjavur Junction", "node_type": NodeType.JUNCTION, "latitude": 10.8, "longitude": 79.15, "linked": None},
    {"node_name": "Kumbakonam Junction", "node_type": NodeType.JUNCTION, "latitude": 10.95, "longitude": 79.38, "linked": None},
    {"node_name": "Orathanadu Junction", "node_type": NodeType.JUNCTION, "latitude": 10.63, "longitude": 79.25, "linked": None},
    {"node_name": "Pattukkottai Junction", "node_type": NodeType.JUNCTION, "latitude": 10.435, "longitude": 79.315, "linked": None},
    {"node_name": "Needamangalam Junction", "node_type": NodeType.JUNCTION, "latitude": 10.77, "longitude": 79.41, "linked": None},
    {"node_name": "Thanjavur Centre Node", "node_type": NodeType.RELIEF_CENTRE, "latitude": 10.787, "longitude": 79.1378, "linked": ("relief_centre", "Thanjavur Relief Centre")},
    {"node_name": "Kumbakonam Centre Node", "node_type": NodeType.RELIEF_CENTRE, "latitude": 10.9601, "longitude": 79.3845, "linked": ("relief_centre", "Kumbakonam Relief Centre")},
    {"node_name": "Orathanadu Centre Node", "node_type": NodeType.RELIEF_CENTRE, "latitude": 10.628, "longitude": 79.261, "linked": ("relief_centre", "Orathanadu Relief Centre")},
    {"node_name": "Pattukkottai Centre Node", "node_type": NodeType.RELIEF_CENTRE, "latitude": 10.431, "longitude": 79.319, "linked": ("relief_centre", "Pattukkottai Relief Centre")},
    {"node_name": "Needamangalam Centre Node", "node_type": NodeType.RELIEF_CENTRE, "latitude": 10.772, "longitude": 79.416, "linked": ("relief_centre", "Needamangalam Relief Centre")},
]

ROAD_SEGMENTS: Final[list[SegmentSeed]] = [
    {"from_node": "Chennai Hub", "to_node": "Chennai Bypass", "distance_km": 18.0, "estimated_travel_time_minutes": 30, "risk_factor": 0.1, "is_blocked": False, "blockage_reason": None},
    {"from_node": "Chennai Bypass", "to_node": "Trichy Bypass", "distance_km": 320.0, "estimated_travel_time_minutes": 345, "risk_factor": 0.25, "is_blocked": False, "blockage_reason": None},
    {"from_node": "Trichy Warehouse", "to_node": "Trichy Bypass", "distance_km": 12.0, "estimated_travel_time_minutes": 20, "risk_factor": 0.15, "is_blocked": False, "blockage_reason": None},
    {"from_node": "Trichy Bypass", "to_node": "Thanjavur Junction", "distance_km": 55.0, "estimated_travel_time_minutes": 65, "risk_factor": 0.2, "is_blocked": False, "blockage_reason": None},
    {"from_node": "Trichy Bypass", "to_node": "Kumbakonam Junction", "distance_km": 85.0, "estimated_travel_time_minutes": 100, "risk_factor": 0.25, "is_blocked": False, "blockage_reason": None},
    {"from_node": "Trichy Bypass", "to_node": "Needamangalam Junction", "distance_km": 70.0, "estimated_travel_time_minutes": 85, "risk_factor": 0.2, "is_blocked": False, "blockage_reason": None},
    {"from_node": "Madurai Warehouse", "to_node": "Madurai Bypass", "distance_km": 10.0, "estimated_travel_time_minutes": 15, "risk_factor": 0.1, "is_blocked": False, "blockage_reason": None},
    {"from_node": "Madurai Bypass", "to_node": "Orathanadu Junction", "distance_km": 150.0, "estimated_travel_time_minutes": 170, "risk_factor": 0.2, "is_blocked": False, "blockage_reason": None},
    {"from_node": "Madurai Bypass", "to_node": "Pattukkottai Junction", "distance_km": 130.0, "estimated_travel_time_minutes": 150, "risk_factor": 0.25, "is_blocked": False, "blockage_reason": None},
    {"from_node": "Thanjavur Junction", "to_node": "Thanjavur Centre Node", "distance_km": 4.0, "estimated_travel_time_minutes": 8, "risk_factor": 0.1, "is_blocked": False, "blockage_reason": None},
    {"from_node": "Thanjavur Junction", "to_node": "Orathanadu Junction", "distance_km": 32.0, "estimated_travel_time_minutes": 40, "risk_factor": 0.15, "is_blocked": False, "blockage_reason": None},
    {"from_node": "Thanjavur Junction", "to_node": "Needamangalam Junction", "distance_km": 36.0, "estimated_travel_time_minutes": 45, "risk_factor": 0.2, "is_blocked": False, "blockage_reason": None},
    {"from_node": "Thanjavur Junction", "to_node": "Kumbakonam Junction", "distance_km": 42.0, "estimated_travel_time_minutes": 50, "risk_factor": 0.35, "is_blocked": True, "blockage_reason": "Ayyampettai causeway submerged after Cauvery overflow (simulated)"},
    {"from_node": "Kumbakonam Junction", "to_node": "Kumbakonam Centre Node", "distance_km": 5.0, "estimated_travel_time_minutes": 9, "risk_factor": 0.1, "is_blocked": False, "blockage_reason": None},
    {"from_node": "Kumbakonam Junction", "to_node": "Needamangalam Junction", "distance_km": 28.0, "estimated_travel_time_minutes": 35, "risk_factor": 0.15, "is_blocked": False, "blockage_reason": None},
    {"from_node": "Needamangalam Junction", "to_node": "Needamangalam Centre Node", "distance_km": 3.0, "estimated_travel_time_minutes": 6, "risk_factor": 0.1, "is_blocked": False, "blockage_reason": None},
    {"from_node": "Needamangalam Junction", "to_node": "Pattukkottai Junction", "distance_km": 55.0, "estimated_travel_time_minutes": 70, "risk_factor": 0.3, "is_blocked": False, "blockage_reason": None},
    {"from_node": "Orathanadu Junction", "to_node": "Orathanadu Centre Node", "distance_km": 6.0, "estimated_travel_time_minutes": 10, "risk_factor": 0.1, "is_blocked": False, "blockage_reason": None},
    {"from_node": "Orathanadu Junction", "to_node": "Pattukkottai Junction", "distance_km": 30.0, "estimated_travel_time_minutes": 38, "risk_factor": 0.2, "is_blocked": False, "blockage_reason": None},
    {"from_node": "Pattukkottai Junction", "to_node": "Pattukkottai Centre Node", "distance_km": 4.0, "estimated_travel_time_minutes": 7, "risk_factor": 0.1, "is_blocked": False, "blockage_reason": None},
]

# --------------------------------------------------------------------------- #
# Incidents
# --------------------------------------------------------------------------- #

INCIDENTS: Final[list[IncidentSeed]] = [
    {
        "incident_type": IncidentType.FLOOD,
        "title": "Thanjavur flood inundation",
        "description": (
            "Simulated flood scenario: Cauvery river water has entered low-lying "
            "localities around Thanjavur town following 210 mm of rainfall in 24 hours."
        ),
        "source": IncidentSource.WEATHER_API,
        "severity": Severity.CRITICAL,
        "status": IncidentStatus.ACTIVE,
        "location_name": "Thanjavur, Tamil Nadu",
        "latitude": 10.787,
        "longitude": 79.1378,
        "affected_population": 52000,
        "metadata": {"rainfall_mm_24h": 210, "river_level_m": 4.82, "simulated": True},
        "hours_ago": 20.0,
    },
    {
        "incident_type": IncidentType.FLOOD,
        "title": "Kumbakonam heavy rainfall warning",
        "description": (
            "Simulated scenario: sustained rainfall over the Kumbakonam belt with "
            "drainage overflow reported in three wards."
        ),
        "source": IncidentSource.WEATHER_API,
        "severity": Severity.HIGH,
        "status": IncidentStatus.ACTIVE,
        "location_name": "Kumbakonam, Tamil Nadu",
        "latitude": 10.9601,
        "longitude": 79.3845,
        "affected_population": 38000,
        "metadata": {"rainfall_mm_24h": 155, "simulated": True},
        "hours_ago": 18.0,
    },
    {
        "incident_type": IncidentType.INFRASTRUCTURE_DAMAGE,
        "title": "Pattukkottai road damage report",
        "description": (
            "Simulated citizen report: culvert on the Pattukkottai-Needamangalam road "
            "weakened by flowing water; heavy vehicles diverted."
        ),
        "source": IncidentSource.CITIZEN_REPORT,
        "severity": Severity.HIGH,
        "status": IncidentStatus.INVESTIGATING,
        "location_name": "Pattukkottai, Tamil Nadu",
        "latitude": 10.431,
        "longitude": 79.319,
        "affected_population": 26000,
        "metadata": {"reported_by": "citizen_demo", "verified": False, "simulated": True},
        "hours_ago": 14.0,
    },
    {
        "incident_type": IncidentType.WATER_SHORTAGE,
        "title": "Orathanadu drinking water shortage",
        "description": (
            "Simulated citizen report: drinking water supply disrupted for two days "
            "in Orathanadu town limits; borewell water unfit for consumption."
        ),
        "source": IncidentSource.CITIZEN_REPORT,
        "severity": Severity.MEDIUM,
        "status": IncidentStatus.REPORTED,
        "location_name": "Orathanadu, Tamil Nadu",
        "latitude": 10.628,
        "longitude": 79.261,
        "affected_population": 21000,
        "metadata": {"reported_by": "citizen_demo", "verified": True, "simulated": True},
        "hours_ago": 11.0,
    },
]

# --------------------------------------------------------------------------- #
# Relief orders (demo allocation state; inventory `reserved_quantity` matches)
# --------------------------------------------------------------------------- #

RELIEF_ORDERS: Final[list[OrderSeed]] = [
    {
        "order_code": "RO-2026-0001",
        "warehouse": "Tiruchirappalli Regional Warehouse",
        "relief_centre": "Thanjavur Relief Centre",
        "vehicle": "VAN-02",
        "status": OrderStatus.APPROVED,
        "priority": Priority.CRITICAL,
        "estimated_travel_time_minutes": 85,
        "route_metadata": {
            "path": [
                "Trichy Warehouse",
                "Trichy Bypass",
                "Thanjavur Junction",
                "Thanjavur Centre Node",
            ],
            "distance_km": 67.0,
            "simulated": True,
        },
        "items": [
            {"supply_type": SupplyType.WATER_LITRE, "quantity": 2000, "unit": "litres"},
            {"supply_type": SupplyType.FOOD_KIT, "quantity": 400, "unit": "kits"},
        ],
        "hours_ago": 6.0,
    },
    {
        "order_code": "RO-2026-0002",
        "warehouse": "Chennai Relief Hub",
        "relief_centre": "Pattukkottai Relief Centre",
        "vehicle": "TRK-03",
        "status": OrderStatus.DISPATCHED,
        "priority": Priority.HIGH,
        "estimated_travel_time_minutes": 400,
        "route_metadata": {
            "path": [
                "Chennai Hub",
                "Chennai Bypass",
                "Trichy Bypass",
                "Needamangalam Junction",
                "Pattukkottai Junction",
                "Pattukkottai Centre Node",
            ],
            "distance_km": 440.0,
            "simulated": True,
        },
        "items": [
            {"supply_type": SupplyType.WATER_LITRE, "quantity": 3000, "unit": "litres"},
            {"supply_type": SupplyType.HYGIENE_KIT, "quantity": 200, "unit": "kits"},
        ],
        "hours_ago": 9.0,
    },
    {
        "order_code": "RO-2026-0003",
        "warehouse": "Madurai Distribution Centre",
        "relief_centre": "Orathanadu Relief Centre",
        "vehicle": None,
        "status": OrderStatus.DRAFT,
        "priority": Priority.MEDIUM,
        "estimated_travel_time_minutes": 175,
        "route_metadata": {
            "path": ["Madurai Warehouse", "Madurai Bypass", "Orathanadu Junction", "Orathanadu Centre Node"],
            "distance_km": 160.0,
            "simulated": True,
        },
        "items": [
            {"supply_type": SupplyType.FOOD_KIT, "quantity": 300, "unit": "kits"},
            {"supply_type": SupplyType.MEDICAL_KIT, "quantity": 40, "unit": "kits"},
        ],
        "hours_ago": 3.0,
    },
]

# Title of the initially blocked segment, used by the seed service when wiring
# the bridge_collapse simulation event to the correct segment.
BLOCKED_SEGMENT_KEY: Final[tuple[str, str]] = (
    "Thanjavur Junction",
    "Kumbakonam Junction",
)


# --------------------------------------------------------------------------- #
# Relief centre existing stock (side of the demand calculation)
# --------------------------------------------------------------------------- #


class CentreSupplySeed(TypedDict):
    supply_type: SupplyType
    quantity: float
    unit: str


RELIEF_CENTRE_INVENTORY: Final[dict[str, list[CentreSupplySeed]]] = {
    "Thanjavur Relief Centre": [
        {"supply_type": SupplyType.WATER_LITRE, "quantity": 6000, "unit": "litres"},
        {"supply_type": SupplyType.FOOD_KIT, "quantity": 500, "unit": "kits"},
        {"supply_type": SupplyType.MEDICAL_KIT, "quantity": 60, "unit": "kits"},
        {"supply_type": SupplyType.HYGIENE_KIT, "quantity": 300, "unit": "kits"},
    ],
    "Kumbakonam Relief Centre": [
        {"supply_type": SupplyType.WATER_LITRE, "quantity": 4200, "unit": "litres"},
        {"supply_type": SupplyType.FOOD_KIT, "quantity": 350, "unit": "kits"},
        {"supply_type": SupplyType.MEDICAL_KIT, "quantity": 40, "unit": "kits"},
        {"supply_type": SupplyType.HYGIENE_KIT, "quantity": 200, "unit": "kits"},
    ],
    "Orathanadu Relief Centre": [
        {"supply_type": SupplyType.WATER_LITRE, "quantity": 1500, "unit": "litres"},
        {"supply_type": SupplyType.FOOD_KIT, "quantity": 100, "unit": "kits"},
        {"supply_type": SupplyType.MEDICAL_KIT, "quantity": 10, "unit": "kits"},
        {"supply_type": SupplyType.HYGIENE_KIT, "quantity": 50, "unit": "kits"},
    ],
    "Pattukkottai Relief Centre": [
        {"supply_type": SupplyType.WATER_LITRE, "quantity": 900, "unit": "litres"},
        {"supply_type": SupplyType.FOOD_KIT, "quantity": 80, "unit": "kits"},
        {"supply_type": SupplyType.MEDICAL_KIT, "quantity": 5, "unit": "kits"},
        {"supply_type": SupplyType.HYGIENE_KIT, "quantity": 30, "unit": "kits"},
    ],
    "Needamangalam Relief Centre": [
        {"supply_type": SupplyType.WATER_LITRE, "quantity": 2000, "unit": "litres"},
        {"supply_type": SupplyType.FOOD_KIT, "quantity": 150, "unit": "kits"},
        {"supply_type": SupplyType.MEDICAL_KIT, "quantity": 20, "unit": "kits"},
        {"supply_type": SupplyType.HYGIENE_KIT, "quantity": 100, "unit": "kits"},
    ],
}

# --------------------------------------------------------------------------- #
# Simulation events (initial event history shown on /simulation/events)
# --------------------------------------------------------------------------- #


class SimEventSeed(TypedDict):
    event_type: SimulationEventType
    title: str
    description: str
    severity: Severity
    location_name: str
    latitude: float
    longitude: float
    target: tuple[str, str] | None  # (entity kind, natural key)
    event_data: dict[str, Any]
    hours_ago: float


SIMULATION_EVENTS: Final[list[SimEventSeed]] = [
    {
        "event_type": SimulationEventType.RAINFALL_ESCALATION,
        "title": "Cauvery river crosses warning level near Thanjavur",
        "description": (
            "Simulated weather escalation: rainfall over the upper Cauvery catchment "
            "raised the river past the warning mark, increasing flood exposure in "
            "Thanjavur town."
        ),
        "severity": Severity.CRITICAL,
        "location_name": "Thanjavur, Tamil Nadu",
        "latitude": 10.787,
        "longitude": 79.1378,
        "target": ("incident", "Thanjavur flood inundation"),
        "event_data": {"rainfall_mm_24h": 210, "river_level_m": 4.82, "simulated": True},
        "hours_ago": 19.0,
    },
    {
        "event_type": SimulationEventType.BRIDGE_COLLAPSE,
        "title": "Ayyampettai causeway submerged",
        "description": (
            "Simulated infrastructure impact: the Thanjavur-Kumbakonam causeway at "
            "Ayyampettai went under water; the segment is unusable for relief convoys."
        ),
        "severity": Severity.HIGH,
        "location_name": "Ayyampettai, Tamil Nadu",
        "latitude": 10.89,
        "longitude": 79.26,
        "target": ("road_segment", "Thanjavur Junction|Kumbakonam Junction"),
        "event_data": {"segment": "Thanjavur Junction -> Kumbakonam Junction", "simulated": True},
        "hours_ago": 16.0,
    },
    {
        "event_type": SimulationEventType.RAINFALL_ESCALATION,
        "title": "Kumbakonam rainfall intensifies",
        "description": (
            "Simulated weather escalation: another band of rain moved over "
            "Kumbakonam, raising the 24-hour total to about 155 mm."
        ),
        "severity": Severity.HIGH,
        "location_name": "Kumbakonam, Tamil Nadu",
        "latitude": 10.9601,
        "longitude": 79.3845,
        "target": ("incident", "Kumbakonam heavy rainfall warning"),
        "event_data": {"rainfall_mm_24h": 155, "simulated": True},
        "hours_ago": 15.0,
    },
    {
        "event_type": SimulationEventType.RELIEF_CENTRE_WATER_SHORTAGE,
        "title": "Pattukkottai centre reports water shortage",
        "description": (
            "Simulated shortage report: Pattukkottai Relief Centre flagged drinking "
            "water stock below one day of requirement."
        ),
        "severity": Severity.HIGH,
        "location_name": "Pattukkottai, Tamil Nadu",
        "latitude": 10.431,
        "longitude": 79.319,
        "target": ("relief_centre", "Pattukkottai Relief Centre"),
        "event_data": {"litres_needed_daily": 26000, "simulated": True},
        "hours_ago": 12.0,
    },
]
