"""Map service: builds the full map overview payload for the frontend.

Map overview markers feed two distinct use cases:
1. The operational disaster map (frontend DisastersMap) which renders ONLY
   live/genuine markers and hides seeded demo data (`is_demo=True`).
2. The disaster-risk road network used by logistics/dispatch, which remains
   derived from the simulated `RoadSegment` graph.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

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
    LiveLayerState,
    MapCenter,
    MapDisasterEvent,
    MapFacility,
    MapIncident,
    MapLiveLayerStatus,
    MapLiveLayers,
    MapOverviewResponse,
    MapReliefCentre,
    MapRiverGauge,
    MapRoadNode,
    MapRoadSegment,
    MapVehicle,
    MapWarehouse,
    MapWeatherStation,
)

# Staleness thresholds per live source (minutes). Beyond these the map flag
# shows "stale"; missing data is always "unavailable" — never demo data.
_LIVE_STALE_MINUTES = {
    "open-meteo": 30,
    "open-meteo-flood": 30,
    "nasa-eonet": 30,
    "gdacs": 60,
    "osm-nominatim": 24 * 60 + 60,
}


def _parse_ts(raw: Any) -> datetime | None:
    """Best-effort ISO timestamp parse; returns None for missing/invalid."""
    if not raw:
        return None
    if isinstance(raw, datetime):
        parsed = raw
    else:
        try:
            parsed = datetime.fromisoformat(str(raw))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _layer_state(
    item_count: int, updated: datetime | None, now: datetime, stale_minutes: int
) -> LiveLayerState:
    if item_count == 0:
        return "unavailable"
    if updated is None:
        return "ok"
    if (now - updated).total_seconds() > stale_minutes * 60:
        return "stale"
    return "ok"


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
            source=incident.source,
            is_demo=incident.is_demo,
            updated_at=incident.updated_at,
            metadata=incident.metadata_json or {},
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
                is_demo=centre.is_demo,
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
                is_demo=warehouse.is_demo,
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
                is_demo=vehicle.is_demo,
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
        live_layers=_build_live_layers(),
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


# --------------------------------------------------------------------------- #
# Live external-data layers (read-only view of the live service cache)
# --------------------------------------------------------------------------- #


def _build_live_layers() -> MapLiveLayers:
    """Assemble live layers from the live-data cache.

    Never touches the network: if the live service has not synced yet, every
    layer reports "unavailable" — the frontend shows an explicit unavailable
    note rather than falling back to demo markers.
    """
    from app.services.live_data_service import (  # local import: avoids cycle
        get_live_status,
        severity_from_gdacs_alert,
        weather_severity_from_metrics,
    )

    cached = get_live_status()
    now = utcnow()

    stations_raw: list[dict[str, Any]] = cached.get("stations", []) or []
    last_sync = _parse_ts(cached.get("last_sync_utc"))
    weather_state = _layer_state(
        len(stations_raw), last_sync, now, _LIVE_STALE_MINUTES["open-meteo"]
    )
    flood_state = _layer_state(
        len(stations_raw), last_sync, now, _LIVE_STALE_MINUTES["open-meteo-flood"]
    )

    weather_stations: list[MapWeatherStation] = []
    river_gauges: list[MapRiverGauge] = []
    for station in stations_raw:
        lat = station.get("latitude")
        lon = station.get("longitude")
        if lat is None or lon is None:
            continue  # never infer coordinates
        severity, assessment = weather_severity_from_metrics(
            float(station.get("precipitation_mm") or 0.0),
            float(station.get("daily_precipitation_mm") or 0.0),
            float(station.get("wind_speed_kmh") or 0.0),
            float(station.get("river_discharge_m3s") or 0.0),
            int(station.get("weather_code") or 0),
        )
        updated = _parse_ts(station.get("synced_at"))
        weather_stations.append(
            MapWeatherStation(
                name=str(station.get("name", "Monitoring station")),
                district=str(station.get("district", "")),
                latitude=float(lat),
                longitude=float(lon),
                temperature_c=(station.get("temperature_c") if station.get("temperature_c") is not None else None),
                precipitation_mm=(station.get("precipitation_mm") if station.get("precipitation_mm") is not None else None),
                daily_precipitation_mm=(station.get("daily_precipitation_mm") if station.get("daily_precipitation_mm") is not None else None),
                wind_speed_kmh=(station.get("wind_speed_kmh") if station.get("wind_speed_kmh") is not None else None),
                wind_gusts_kmh=(station.get("wind_gusts_kmh") if station.get("wind_gusts_kmh") is not None else None),
                weather_code=(station.get("weather_code") if station.get("weather_code") is not None else None),
                river=station.get("river"),
                severity=severity,
                assessment=assessment,
                updated_at=updated,
            )
        )
        river_gauges.append(
            MapRiverGauge(
                name=str(station.get("name", "River gauge")),
                river=station.get("river"),
                latitude=float(lat),
                longitude=float(lon),
                river_discharge_m3s=(station.get("river_discharge_m3s") if station.get("river_discharge_m3s") is not None else None),
                daily_precipitation_mm=(station.get("daily_precipitation_mm") if station.get("daily_precipitation_mm") is not None else None),
                severity=severity,
                assessment=assessment,
                updated_at=updated,
            )
        )

    disaster_events: list[MapDisasterEvent] = []
    eonet_state: LiveLayerState = "unavailable"
    if cached.get("nasa_events"):
        eonet_state = _layer_state(
            len(cached["nasa_events"]), last_sync, now, _LIVE_STALE_MINUTES["nasa-eonet"]
        )
        for event in cached["nasa_events"]:
            lat = event.get("latitude")
            lon = event.get("longitude")
            if lat is None or lon is None:
                continue
            category = str(event.get("category") or "").lower()
            disaster_events.append(
                MapDisasterEvent(
                    external_id=str(event.get("id")) if event.get("id") else None,
                    title=str(event.get("title", "Untitled event")),
                    category=category or None,
                    severity=None,  # EONET does not provide severity
                    severity_text=None,
                    latitude=float(lat),
                    longitude=float(lon),
                    source="NASA EONET",
                    link=event.get("link"),
                    occurred_at=_parse_ts(event.get("date")),
                    updated_at=last_sync,
                )
            )

    gdacs = cached.get("gdacs") or {}
    gdacs_state: LiveLayerState = "unavailable"
    if gdacs.get("alerts"):
        gdacs_state = _layer_state(
            len(gdacs["alerts"]),
            _parse_ts(gdacs.get("fetched_at")),
            now,
            _LIVE_STALE_MINUTES["gdacs"],
        )
        for alert in gdacs["alerts"]:
            lat = alert.get("latitude")
            lon = alert.get("longitude")
            if lat is None or lon is None:
                continue
            disaster_events.append(
                MapDisasterEvent(
                    external_id=alert.get("id"),
                    title=str(alert.get("title", "GDACS alert")),
                    category=alert.get("eventtype"),
                    alert_level=alert.get("alert_level"),
                    severity=severity_from_gdacs_alert(alert.get("alert_level")),
                    severity_text=alert.get("severity_text"),
                    latitude=float(lat),
                    longitude=float(lon),
                    source="GDACS",
                    link=alert.get("link"),
                    occurred_at=_parse_ts(alert.get("occurred_at")),
                    updated_at=_parse_ts(alert.get("last_updated_at")),
                )
            )

    hospitals = cached.get("hospitals") or {}
    hospital_state: LiveLayerState = "unavailable"
    facilities: list[MapFacility] = []
    if hospitals.get("items"):
        hospital_updated = _parse_ts(hospitals.get("fetched_at"))
        hospital_state = _layer_state(
            len(hospitals["items"]),
            hospital_updated,
            now,
            _LIVE_STALE_MINUTES["osm-nominatim"],
        )
        for item in hospitals["items"]:
            lat = item.get("latitude")
            lon = item.get("longitude")
            if lat is None or lon is None:
                continue
            facilities.append(
                MapFacility(
                    name=str(item.get("name", "Medical facility")),
                    display_name=item.get("display_name"),
                    town=item.get("town"),
                    latitude=float(lat),
                    longitude=float(lon),
                    osm_id=item.get("osm_id"),
                    osm_type=item.get("osm_type"),
                    updated_at=hospital_updated,
                )
            )

    return MapLiveLayers(
        weather_stations=weather_stations,
        river_gauges=river_gauges,
        disaster_events=disaster_events,
        facilities=facilities,
        statuses=[
            MapLiveLayerStatus(
                source="open-meteo",
                status=weather_state,
                last_updated=last_sync,
                detail="Weather current conditions (8 delta stations)" if weather_state == "ok" else None,
            ),
            MapLiveLayerStatus(
                source="open-meteo-flood",
                status=flood_state,
                last_updated=last_sync,
                detail="River discharge gauge readings" if flood_state == "ok" else None,
            ),
            MapLiveLayerStatus(source="nasa-eonet", status=eonet_state, last_updated=last_sync),
            MapLiveLayerStatus(
                source="gdacs",
                status=gdacs_state,
                last_updated=_parse_ts(gdacs.get("fetched_at")),
            ),
            MapLiveLayerStatus(
                source="osm-nominatim",
                status=hospital_state,
                last_updated=_parse_ts(hospitals.get("fetched_at")),
            ),
        ],
    )
