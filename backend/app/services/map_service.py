"""Map service: builds the full map overview payload for the frontend."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.clock import utcnow
from app.models import (
    Incident,
    ReliefCentre,
    RoadNode,
    RoadSegment,
    Vehicle,
    Warehouse,
)
from app.models.enums import IncidentStatus
from app.schemas.map import (
    MapCenter,
    MapIncident,
    MapOverviewResponse,
    MapReliefCentre,
    MapRoadNode,
    MapRoadSegment,
    MapVehicle,
    MapWarehouse,
)


def get_map_overview(db: Session) -> MapOverviewResponse:
    """Assemble every marker and network element in one request."""
    incidents: list[Incident] = db.scalars(
        select(Incident).where(Incident.status == IncidentStatus.ACTIVE).order_by(Incident.id)
    ).all()
    centres: list[ReliefCentre] = db.scalars(
        select(ReliefCentre).order_by(ReliefCentre.id)
    ).all()
    warehouses: list[Warehouse] = db.scalars(
        select(Warehouse).order_by(Warehouse.id)
    ).all()
    vehicles: list[Vehicle] = db.scalars(select(Vehicle).order_by(Vehicle.id)).all()
    nodes: list[RoadNode] = db.scalars(select(RoadNode).order_by(RoadNode.id)).all()

    segments: list[RoadSegment] = db.scalars(
        select(RoadSegment)
        .options(
            selectinload(RoadSegment.from_node),
            selectinload(RoadSegment.to_node),
        )
        .order_by(RoadSegment.id)
    ).all()

    incident_markers = [
        MapIncident(
            id=incident.id,
            incident_type=incident.incident_type,
            title=incident.title,
            severity=incident.severity,
            status=incident.status,
            location_name=incident.location_name,
            latitude=incident.latitude,
            longitude=incident.longitude,
            affected_population=incident.affected_population,
        )
        for incident in incidents
        if incident.latitude is not None and incident.longitude is not None
    ]

    blocked_segments = [
        _segment_marker(segment)
        for segment in segments
        if segment.is_blocked
    ]

    return MapOverviewResponse(
        data_mode="SIMULATED",
        generated_at=utcnow(),
        center=_derive_center(incident_markers, centres),
        incidents=incident_markers,
        relief_centres=[
            MapReliefCentre(
                id=centre.id,
                name=centre.name,
                district=centre.district,
                latitude=centre.latitude,
                longitude=centre.longitude,
                affected_population=centre.affected_population,
                priority=centre.priority,
                operational_status=centre.operational_status,
                water_shortage=centre.water_shortage,
            )
            for centre in centres
        ],
        warehouses=[
            MapWarehouse(
                id=warehouse.id,
                name=warehouse.name,
                location_name=warehouse.location_name,
                latitude=warehouse.latitude,
                longitude=warehouse.longitude,
                operational_status=warehouse.operational_status,
            )
            for warehouse in warehouses
        ],
        vehicles=[
            MapVehicle(
                id=vehicle.id,
                vehicle_code=vehicle.vehicle_code,
                vehicle_type=vehicle.vehicle_type,
                status=vehicle.status,
                capacity=vehicle.capacity,
                current_latitude=vehicle.current_latitude,
                current_longitude=vehicle.current_longitude,
                current_location=vehicle.current_location,
            )
            for vehicle in vehicles
        ],
        road_nodes=[
            MapRoadNode(
                id=node.id,
                node_name=node.node_name,
                node_type=node.node_type,
                latitude=node.latitude,
                longitude=node.longitude,
                linked_entity_id=node.linked_entity_id,
            )
            for node in nodes
        ],
        road_segments=[
            _segment_marker(segment) for segment in segments
        ],
        blocked_roads=blocked_segments,
    )


def _segment_marker(segment: RoadSegment) -> MapRoadSegment:
    return MapRoadSegment(
        id=segment.id,
        from_node_id=segment.from_node_id,
        to_node_id=segment.to_node_id,
        from_node_name=segment.from_node.node_name,
        to_node_name=segment.to_node.node_name,
        distance_km=segment.distance_km,
        estimated_travel_time_minutes=segment.estimated_travel_time_minutes,
        risk_factor=segment.risk_factor,
        is_blocked=segment.is_blocked,
        blockage_reason=segment.blockage_reason,
    )


def _derive_center(
    incidents: list[MapIncident], centres: list[ReliefCentre]
) -> MapCenter:
    """Center the viewport on the affected incidents (fallback: relief centres)."""
    lats: list[float] = []
    lngs: list[float] = []
    for incident in incidents:
        if incident.latitude is not None and incident.longitude is not None:
            lats.append(float(incident.latitude))
            lngs.append(float(incident.longitude))
    if not lats:
        for centre in centres:
            lats.append(centre.latitude)
            lngs.append(centre.longitude)
    if not lats:
        # Default: Thanjavur district.
        return MapCenter(latitude=10.787, longitude=79.1378, zoom=9.0)
    return MapCenter(
        latitude=round(sum(lats) / len(lats), 4),
        longitude=round(sum(lngs) / len(lngs), 4),
        zoom=9.0,
    )
