"""Live data ingestion service for Tamil Nadu (Cauvery Delta Region).

Integrates:
1. Open-Meteo Weather API - Real-time temperature, precipitation, wind, weather codes.
2. Open-Meteo Flood API - Real-time river discharge (m^3/s) along the Cauvery and Kollidam rivers.
3. NASA EONET v3 API - Real-time Bay of Bengal tropical storms and severe flood events.
4. GDACS API - Active regional disaster alerts (floods / tropical cyclones).
5. OpenStreetMap Nominatim API - Real hospital & relief facility coordinates in Tamil Nadu.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.models.enums import (
    IncidentSource,
    IncidentStatus,
    IncidentType,
    Priority,
    Severity,
)
from app.models.incident import Incident
from app.models.relief_centre import ReliefCentre
from app.models.road import RoadNode, RoadSegment

logger = logging.getLogger("reliefmesh.live")

# How often a periodic live refresh runs (background task started in app.main).
LIVE_REFRESH_INTERVAL_SECONDS = 300
# A live layer is flagged stale in the map payload when older than this.
LIVE_STALE_AFTER = timedelta(minutes=30)

# Key monitoring stations across Tamil Nadu Cauvery Delta
CAUVERY_DELTA_STATIONS = [
    {
        "name": "Tiruchirappalli (Trichy)",
        "district": "Tiruchirappalli",
        "latitude": 10.7905,
        "longitude": 78.7047,
        "population": 1020000,
        "river": "Upper Cauvery / Grand Anicut",
    },
    {
        "name": "Thanjavur Central",
        "district": "Thanjavur",
        "latitude": 10.7870,
        "longitude": 79.1378,
        "population": 290000,
        "river": "Vennar / Cauvery Delta",
    },
    {
        "name": "Kumbakonam",
        "district": "Thanjavur",
        "latitude": 10.9601,
        "longitude": 79.3845,
        "population": 140000,
        "river": "Kollidam & Arasalar",
    },
    {
        "name": "Nagapattinam Coast",
        "district": "Nagapattinam",
        "latitude": 10.7656,
        "longitude": 79.8424,
        "population": 102000,
        "river": "Cauvery Sea Mouth / Coastal Zone",
    },
    {
        "name": "Mayiladuthurai",
        "district": "Mayiladuthurai",
        "latitude": 11.1075,
        "longitude": 79.6523,
        "population": 90000,
        "river": "Cauvery Lower Basin",
    },
    {
        "name": "Tiruvarur",
        "district": "Tiruvarur",
        "latitude": 10.7720,
        "longitude": 79.4160,
        "population": 60000,
        "river": "Odamambokki / Vennar",
    },
    {
        "name": "Pattukkottai",
        "district": "Thanjavur",
        "latitude": 10.4310,
        "longitude": 79.3190,
        "population": 75000,
        "river": "Agniyar Basin",
    },
    {
        "name": "Orathanadu",
        "district": "Thanjavur",
        "latitude": 10.6280,
        "longitude": 79.2610,
        "population": 30000,
        "river": "Grand Anicut Canal",
    },
]

# In-memory cache for live status
_LIVE_CACHE: dict[str, Any] = {
    "last_sync_utc": None,
    "status": "initialising",
    "stations": [],
    "nasa_events": [],
    "incidents_synced": 0,
    "roads_updated": 0,
    "gdacs": {"alerts": [], "fetched_at": None, "status": "unavailable"},
    "hospitals": {"items": [], "fetched_at": None, "status": "unavailable"},
}

# GDACS: active disaster alerts relevant to the Cauvery delta scenario
# (floods and tropical cyclones only). The SEARCH endpoint returns a GeoJSON
# FeatureCollection with point coordinates.
GDACS_EVENTS_URL = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH"
GDACS_TRACKED_TYPES = {"FL", "TC"}
GDACS_DAYS_BACK = 90
GDACS_STALE_AFTER = timedelta(minutes=60)

# Bay of Bengal / wider Indian Ocean basin (same region filter as EONET).
REGION_LAT_MAX, REGION_LAT_MIN = 25.0, 0.0
REGION_LON_MAX, REGION_LON_MIN = 95.0, 60.0

# OSM Nominatim (hospitals / medical facilities).
# Usage policy (https://operations.osmfoundation.org/policies/nominatim/):
# max 1 request/second, a descriptive User-Agent, and aggressive caching.
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_USER_AGENT = (
    "ReliefMesh/0.5 (hackathon emergency-response demo; browser map display; "
    "contact: ops@reliefmesh.example)"
)
NOMINATIM_REQUEST_GAP_SECONDS = 1.1
NOMINATIM_RESULTS_PER_TOWN = 4
NOMINATIM_BBOX_MARGIN_DEG = 0.35
HOSPITAL_CACHE_TTL = timedelta(hours=24)          # result cache (usage policy)
HOSPITAL_RETRY_BACKOFF = timedelta(minutes=30)    # failed fetch retry backoff

_HOSPITAL_CACHE: dict[str, Any] = {
    "items": [],
    "fetched_at": None,
    "status": "unavailable",
    "failed_at": None,
}

# Town search query used for each weather station (Nominatim has friendlier
# town queries than the padded station names below).
HOSPITAL_QUERY_TOWNS = [
    {"town": "Tiruchirappalli", "latitude": 10.7905, "longitude": 78.7047},
    {"town": "Thanjavur", "latitude": 10.7870, "longitude": 79.1378},
    {"town": "Kumbakonam", "latitude": 10.9601, "longitude": 79.3845},
    {"town": "Nagapattinam", "latitude": 10.7656, "longitude": 79.8424},
    {"town": "Mayiladuthurai", "latitude": 11.1075, "longitude": 79.6523},
    {"town": "Tiruvarur", "latitude": 10.7720, "longitude": 79.4160},
    {"town": "Pattukkottai", "latitude": 10.4310, "longitude": 79.3190},
    {"town": "Orathanadu", "latitude": 10.6280, "longitude": 79.2610},
]


def fetch_station_weather_and_flood(
    lat: float, lon: float, client: httpx.Client
) -> dict[str, Any]:
    """Fetch live weather and river discharge for a coordinate in Tamil Nadu."""
    result: dict[str, Any] = {
        "temperature_c": 26.0,
        "precipitation_mm": 0.0,
        "daily_precipitation_mm": 0.0,
        "wind_speed_kmh": 10.0,
        "wind_gusts_kmh": 15.0,
        "weather_code": 0,
        "river_discharge_m3s": 1.5,
        "forecast_time": None,
    }

    # 1. Weather forecast & current conditions
    try:
        url_weather = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&current=temperature_2m,relative_humidity_2m,precipitation,rain,weather_code,wind_speed_10m,wind_gusts_10m"
            f"&daily=precipitation_sum&timezone=auto"
        )
        resp = client.get(url_weather, timeout=8.0)
        if resp.status_code == 200:
            data = resp.json()
            curr = data.get("current", {})
            daily = data.get("daily", {})
            result["temperature_c"] = float(curr.get("temperature_2m", 26.0))
            result["precipitation_mm"] = float(curr.get("precipitation", 0.0))
            result["wind_speed_kmh"] = float(curr.get("wind_speed_10m", 10.0))
            result["wind_gusts_kmh"] = float(curr.get("wind_gusts_10m", 15.0))
            result["weather_code"] = int(curr.get("weather_code", 0))
            result["forecast_time"] = curr.get("time")

            precip_sums = daily.get("precipitation_sum", [])
            if precip_sums:
                result["daily_precipitation_mm"] = float(precip_sums[0] or 0.0)
    except Exception as exc:
        logger.warning("Failed to fetch Open-Meteo weather for (%s, %s): %s", lat, lon, exc)

    # 2. River discharge / flood risk
    try:
        url_flood = (
            f"https://flood-api.open-meteo.com/v1/flood"
            f"?latitude={lat}&longitude={lon}"
            f"&daily=river_discharge,river_discharge_mean&forecast_days=1"
        )
        resp_flood = client.get(url_flood, timeout=8.0)
        if resp_flood.status_code == 200:
            fdata = resp_flood.json().get("daily", {})
            discharges = fdata.get("river_discharge", [])
            if discharges and discharges[0] is not None:
                result["river_discharge_m3s"] = float(discharges[0])
    except Exception as exc:
        logger.warning("Failed to fetch Open-Meteo flood for (%s, %s): %s", lat, lon, exc)

    return result


def fetch_bay_of_bengal_events(client: httpx.Client) -> list[dict[str, Any]]:
    """Fetch live severe storm / flood events from NASA EONET near Tamil Nadu."""
    events: list[dict[str, Any]] = []
    try:
        url = "https://eonet.gsfc.nasa.gov/api/v3/events?status=open&category=severeStorms,floods"
        resp = client.get(url, timeout=8.0)
        if resp.status_code == 200:
            data = resp.json().get("events", [])
            for item in data:
                geoms = item.get("geometry", [])
                if not geoms:
                    continue
                last_geom = geoms[-1]
                coords = last_geom.get("coordinates")
                if not coords or len(coords) < 2:
                    continue
                lon, lat = float(coords[0]), float(coords[1])
                # Check if event is in the wider Indian Ocean / Bay of Bengal basin
                # (Lat: 0 to 25 N, Lon: 70 to 95 E)
                if 0.0 <= lat <= 25.0 and 70.0 <= lon <= 95.0:
                    categories = item.get("categories", [])
                    category = (
                        str(categories[-1].get("title", "")) if categories else ""
                    )
                    events.append(
                        {
                            "id": item.get("id"),
                            "title": item.get("title"),
                            "category": category,
                            "latitude": lat,
                            "longitude": lon,
                            "date": last_geom.get("date"),
                            "link": item.get("link"),
                        }
                    )
    except Exception as exc:
        logger.warning("Failed to fetch NASA EONET events: %s", exc)
    return events


def _gdacs_point(feature: dict[str, Any]) -> tuple[float, float] | None:
    """Extract (lat, lon) from a GDACS feature (point centroid geometry)."""
    geometry = feature.get("geometry") or {}
    coords = geometry.get("coordinates") or []
    if isinstance(coords, (list, tuple)) and len(coords) >= 2:
        try:
            lon, lat = float(coords[0]), float(coords[1])
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                return lat, lon
        except (TypeError, ValueError):
            return None
    return None


def severity_from_gdacs_alert(alert_level: str) -> Severity | None:
    """Map a GDACS alert level (red/orange/green) to ReliefMesh severity."""
    level = (alert_level or "").strip().lower()
    if level == "red":
        return Severity.CRITICAL
    if level == "orange":
        return Severity.HIGH
    if level == "green":
        return Severity.MEDIUM
    return None


def fetch_gdacs_alerts(client: httpx.Client) -> dict[str, Any]:
    """Fetch active GDACS flood / tropical-cyclone alerts near the Bay of Bengal.

    Returns a cache entry: {"alerts": [...], "fetched_at": iso, "status":
    "ok" | "unavailable"}. Never raises: external failures degrade to
    "unavailable" so the map can show a stale/unavailable state instead.
    """
    fetched_at = utcnow().isoformat()
    try:
        from_date = (datetime.now(timezone.utc) - timedelta(days=GDACS_DAYS_BACK)).strftime(
            "%Y-%m-%d"
        )
        resp = client.get(GDACS_EVENTS_URL, params={"fromDate": from_date}, timeout=10.0)
        resp.raise_for_status()
        features = resp.json().get("features", []) or []
        alerts: list[dict[str, Any]] = []
        for feature in features:
            properties = feature.get("properties") or {}
            event_type = str(properties.get("eventtype", "")).upper()
            if event_type not in GDACS_TRACKED_TYPES:
                continue
            point = _gdacs_point(feature)
            if point is None:
                continue  # missing coordinates -> skip, never invent one
            lat, lon = point
            if not (REGION_LAT_MIN <= lat <= REGION_LAT_MAX and REGION_LON_MIN <= lon <= REGION_LON_MAX):
                continue
            severity_data = properties.get("severitydata") or {}
            links = properties.get("url") if isinstance(properties.get("url"), dict) else {}
            alerts.append(
                {
                    "id": (
                        f"gdacs-{properties.get('eventid')}-e{properties.get('episodeid')}"
                        or f"gdacs-{properties.get('eventname')}"
                    ),
                    "title": properties.get("eventname")
                    or properties.get("name")
                    or "GDACS alert",
                    "eventtype": event_type.lower(),
                    "alert_level": str(properties.get("alertlevel", "")).lower() or None,
                    "severity_text": severity_data.get("severitytext"),
                    "latitude": lat,
                    "longitude": lon,
                    "occurred_at": properties.get("fromdate"),
                    "last_updated_at": properties.get("datemodified"),
                    "link": links.get("report"),
                }
            )
        return {"alerts": alerts, "fetched_at": fetched_at, "status": "ok"}
    except Exception as exc:
        logger.warning("Failed to fetch GDACS alerts: %s", exc)
        return {"alerts": [], "fetched_at": fetched_at, "status": "unavailable"}


def _nominatim_viewbox(lat: float, lon: float) -> str:
    """Bounding box for hospital search around a town (left,top,right,bottom)."""
    m = NOMINATIM_BBOX_MARGIN_DEG
    return f"{lon - m:.3f},{lat + m:.3f},{lon + m:.3f},{lat - m:.3f}"


def fetch_hospitals_if_needed() -> dict[str, Any]:
    """Fetch real hospital coordinates from OSM Nominatim (cached 24h).

    Compliance with the Nominatim usage policy:
    - server-side requests only, with a descriptive User-Agent;
    - at most one request per second (sequential loop);
    - GET-only search; results are cached with a 24h TTL; failed fetches
      retry at most every 30 minutes.
    """
    fetched_at = _HOSPITAL_CACHE.get("fetched_at")
    now = utcnow()

    def _age(ts: str | None) -> timedelta | None:
        if not ts:
            return None
        try:
            return now - datetime.fromisoformat(ts)
        except ValueError:
            return None

    ok_age = _age(fetched_at)
    if _HOSPITAL_CACHE.get("status") == "ok" and ok_age and ok_age < HOSPITAL_CACHE_TTL:
        return _cache_snapshot(_HOSPITAL_CACHE)
    failed_age = _age(_HOSPITAL_CACHE.get("failed_at"))
    if (
        _HOSPITAL_CACHE.get("status") == "unavailable"
        and failed_age
        and failed_age < HOSPITAL_RETRY_BACKOFF
    ):
        return _cache_snapshot(_HOSPITAL_CACHE)

    items: list[dict[str, Any]] = []
    seen_osm_ids: set[str] = set()
    searches_attempted = 0
    searches_succeeded = 0
    with httpx.Client(timeout=10.0) as client:
        headers = {"User-Agent": NOMINATIM_USER_AGENT, "Accept": "application/json"}
        for index, town in enumerate(HOSPITAL_QUERY_TOWNS):
            if index > 0:
                time.sleep(NOMINATIM_REQUEST_GAP_SECONDS)  # max 1 req/s
            searches_attempted += 1
            try:
                resp = client.get(
                    NOMINATIM_URL,
                    params={
                        "q": "hospital",
                        "format": "jsonv2",
                        "limit": NOMINATIM_RESULTS_PER_TOWN,
                        "viewbox": _nominatim_viewbox(town["latitude"], town["longitude"]),
                        "bounded": "1",
                    },
                    headers=headers,
                )
                resp.raise_for_status()
                for place in resp.json() or []:
                    lat, lon = place.get("lat"), place.get("lon")
                    if lat is None or lon is None:
                        continue  # never manufacture coordinates
                    try:
                        lat_f, lon_f = float(lat), float(lon)
                    except (TypeError, ValueError):
                        continue
                    # Overlapping town viewboxes can return the same facility;
                    # deduplicate by OSM place id so each marker is unique.
                    osm_key = f"{place.get('osm_type')}/{place.get('osm_id')}"
                    if osm_key in seen_osm_ids:
                        continue
                    seen_osm_ids.add(osm_key)
                    items.append(
                        {
                            "name": place.get("name") or (place.get("display_name") or "").split(",")[0],
                            "display_name": place.get("display_name"),
                            "town": town["town"],
                            "latitude": lat_f,
                            "longitude": lon_f,
                            "osm_id": str(place.get("osm_id")) if place.get("osm_id") else None,
                            "osm_type": place.get("osm_type"),
                        }
                    )
                searches_succeeded += 1
            except Exception as exc:
                logger.warning("Nominatim hospital search failed for %s: %s", town["town"], exc)
                continue

    status = "ok" if searches_succeeded > 0 else "unavailable"
    _HOSPITAL_CACHE.update(
        items=items,
        fetched_at=now.isoformat(),
        status=status,
        failed_at=None if status == "ok" else now.isoformat(),
    )
    logger.info(
        "Nominatim hospitals refreshed: %d facilities (%d/%d town searches ok)",
        len(items),
        searches_succeeded,
        searches_attempted,
    )
    return _cache_snapshot(_HOSPITAL_CACHE)


def _cache_snapshot(cache: dict[str, Any]) -> dict[str, Any]:
    return {
        "items": cache.get("items", []),
        "fetched_at": cache.get("fetched_at"),
        "status": cache.get("status", "unavailable"),
    }


def weather_severity_from_metrics(
    precipitation_mm: float,
    daily_precip_mm: float,
    wind_kmh: float,
    discharge_m3s: float,
    weather_code: int,
) -> tuple[Severity, str]:
    """Classify severity level based on real meteorological thresholds."""
    # Extreme / Critical: severe thunderstorm, torrential rain (>60mm/day), or severe flood discharge (>50m3/s)
    if daily_precip_mm >= 60.0 or precipitation_mm >= 20.0 or discharge_m3s >= 50.0 or weather_code in (95, 96, 99):
        return Severity.CRITICAL, "Torrential precipitation / high river inundation"
    if daily_precip_mm >= 30.0 or precipitation_mm >= 10.0 or discharge_m3s >= 25.0 or wind_kmh >= 50.0:
        return Severity.HIGH, "Heavy rainfall / elevated discharge advisory"
    if daily_precip_mm >= 10.0 or precipitation_mm >= 2.0 or discharge_m3s >= 10.0 or wind_kmh >= 35.0:
        return Severity.MEDIUM, "Moderate precipitation / localized water accumulation"
    return Severity.LOW, "Normal seasonal conditions"


def sync_live_disaster_data(db: Session) -> dict[str, Any]:
    """Sync live data for Tamil Nadu Cauvery Delta into the active database.

    1. Queries Open-Meteo for live weather and river discharge at 8 Delta stations.
    2. Queries NASA EONET for Bay of Bengal storm / cyclone activity.
    3. Updates or creates active `Incident` records with `source=WEATHER_API`.
    4. Dynamically adjusts `RoadSegment` risk factors and travel times.
    5. Updates cached metrics for the UI and dashboard.
    """
    logger.info("Starting live disaster data sync for Tamil Nadu (Cauvery Delta)...")
    synced_at = utcnow()
    station_readings: list[dict[str, Any]] = []

    with httpx.Client(timeout=10.0) as client:
        # 1. Fetch live metrics for all Tamil Nadu Delta monitoring stations
        for station in CAUVERY_DELTA_STATIONS:
            metrics = fetch_station_weather_and_flood(
                station["latitude"], station["longitude"], client
            )
            station_info = {**station, **metrics, "synced_at": synced_at.isoformat()}
            station_readings.append(station_info)

        # 2. Fetch NASA EONET Bay of Bengal severe weather events
        nasa_events = fetch_bay_of_bengal_events(client)

        # 3. Fetch active GDACS disaster alerts (floods / cyclones)
        gdacs_result = fetch_gdacs_alerts(client)

    # 3. Synchronise live incidents in the database
    incidents_updated_or_created = 0

    # Handle NASA Bay of Bengal events if present
    for event in nasa_events:
        existing = db.execute(
            select(Incident).where(
                Incident.source == IncidentSource.WEATHER_API,
                Incident.title.like(f"%{event['title']}%"),
            )
        ).scalar_one_or_none()

        if existing is None:
            new_inc = Incident(
                incident_type=IncidentType.CYCLONE if "cyclone" in event["title"].lower() else IncidentType.FLOOD,
                title=f"LIVE ALERT: {event['title']} (Bay of Bengal)",
                description=(
                    f"Live tracking from NASA EONET: {event['title']} located at coordinates "
                    f"({event['latitude']:.2f}N, {event['longitude']:.2f}E) influencing coastal Tamil Nadu."
                ),
                source=IncidentSource.WEATHER_API,
                severity=Severity.HIGH,
                status=IncidentStatus.ACTIVE,
                location_name="Coastal Tamil Nadu / Bay of Bengal",
                latitude=event["latitude"],
                longitude=event["longitude"],
                affected_population=150000,
                is_demo=False,
                metadata_json={"live_source": "NASA_EONET", "event_id": event["id"], "updated_at": synced_at.isoformat()},
            )
            db.add(new_inc)
            incidents_updated_or_created += 1

    # Ingest / update live weather & flood incidents for Tamil Nadu stations
    for st in station_readings:
        sev, reason = weather_severity_from_metrics(
            st["precipitation_mm"],
            st["daily_precipitation_mm"],
            st["wind_speed_kmh"],
            st["river_discharge_m3s"],
            st["weather_code"],
        )

        title = f"Live Weather & River Monitor: {st['name']}"
        existing = db.execute(
            select(Incident).where(
                Incident.source == IncidentSource.WEATHER_API,
                Incident.location_name == st["name"],
            )
        ).scalar_one_or_none()

        desc = (
            f"Live readings from Open-Meteo for {st['name']}, Tamil Nadu: "
            f"Temperature: {st['temperature_c']}°C, Precip: {st['precipitation_mm']} mm (24h sum: {st['daily_precipitation_mm']} mm), "
            f"Wind: {st['wind_speed_kmh']} km/h (gusts {st['wind_gusts_kmh']} km/h), "
            f"River Discharge ({st['river']}): {st['river_discharge_m3s']} m³/s. "
            f"Assessment: {reason}."
        )

        if existing:
            existing.description = desc
            existing.severity = sev
            existing.status = IncidentStatus.ACTIVE
            existing.latitude = st["latitude"]
            existing.longitude = st["longitude"]
            existing.metadata_json = {
                "live_source": "OPEN_METEO",
                "temperature_c": st["temperature_c"],
                "precip_mm": st["precipitation_mm"],
                "daily_precip_mm": st["daily_precipitation_mm"],
                "wind_kmh": st["wind_speed_kmh"],
                "river_discharge_m3s": st["river_discharge_m3s"],
                "synced_at": synced_at.isoformat(),
            }
            incidents_updated_or_created += 1
        else:
            new_inc = Incident(
                incident_type=IncidentType.FLOOD,
                title=title,
                description=desc,
                source=IncidentSource.WEATHER_API,
                severity=sev,
                status=IncidentStatus.ACTIVE,
                location_name=st["name"],
                latitude=st["latitude"],
                longitude=st["longitude"],
                affected_population=int(st["population"] * 0.05),
                is_demo=False,
                metadata_json={
                    "live_source": "OPEN_METEO",
                    "temperature_c": st["temperature_c"],
                    "precip_mm": st["precipitation_mm"],
                    "daily_precip_mm": st["daily_precipitation_mm"],
                    "wind_kmh": st["wind_speed_kmh"],
                    "river_discharge_m3s": st["river_discharge_m3s"],
                    "synced_at": synced_at.isoformat(),
                },
            )
            db.add(new_inc)
            incidents_updated_or_created += 1

    # 4. Dynamically adjust road risks based on live river discharge and precipitation
    roads_updated = 0
    all_segments = db.execute(select(RoadSegment)).scalars().all()
    # Map station name keywords to readings
    station_lookup = {s["name"].lower(): s for s in station_readings}

    for segment in all_segments:
        # Determine if road is in a high-risk flood zone (e.g. Cauvery river crossings)
        # Check if near Trichy (Grand Anicut) or Kumbakonam
        from_node = segment.from_node
        to_node = segment.to_node
        node_names = f"{from_node.node_name if from_node else ''} {to_node.node_name if to_node else ''}".lower()

        weather_risk = 0.05  # baseline nominal risk
        for name_key, s_data in station_lookup.items():
            if name_key in node_names:
                precip = s_data["daily_precipitation_mm"]
                discharge = s_data["river_discharge_m3s"]
                if discharge > 30.0 or precip > 40.0:
                    weather_risk = max(weather_risk, 0.45)
                elif discharge > 10.0 or precip > 15.0:
                    weather_risk = max(weather_risk, 0.25)
                elif precip > 5.0:
                    weather_risk = max(weather_risk, 0.15)

        # Update segment risk factor if not manually blocked by an operator
        if not segment.is_blocked:
            segment.risk_factor = min(1.0, max(segment.risk_factor, weather_risk))
            roads_updated += 1

    db.commit()

    # Update cache
    _LIVE_CACHE["last_sync_utc"] = synced_at.isoformat()
    _LIVE_CACHE["status"] = "active"
    _LIVE_CACHE["stations"] = station_readings
    _LIVE_CACHE["nasa_events"] = nasa_events
    _LIVE_CACHE["incidents_synced"] = incidents_updated_or_created
    _LIVE_CACHE["roads_updated"] = roads_updated
    _LIVE_CACHE["gdacs"] = gdacs_result

    # Hospitals: cached OSM Nominatim fetch (no-op while cache is fresh).
    # Never raises; on failure the map layer surfaces "unavailable".
    try:
        hospital_result = fetch_hospitals_if_needed()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Hospital facility fetch failed (continuing): %s", exc)
        hospital_result = {
            "items": [],
            "fetched_at": synced_at.isoformat(),
            "status": "unavailable",
        }
    _LIVE_CACHE["hospitals"] = hospital_result

    logger.info(
        "Live sync complete: %d incidents synced, %d road segments updated with live weather risks.",
        incidents_updated_or_created,
        roads_updated,
    )

    return dict(_LIVE_CACHE)


def get_live_status() -> dict[str, Any]:
    """Return the current cached live data status and readings."""
    return dict(_LIVE_CACHE)
