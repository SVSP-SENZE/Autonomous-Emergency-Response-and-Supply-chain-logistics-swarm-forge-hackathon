/**
 * Disaster-aware safety assessment for a planned route.
 *
 * This is deliberately SEPARATE from Google's directions engine: Google does
 * not know about ReliefMesh verified road closures or the live disaster layers
 * shown on this map. After a route is computed, its geometry is checked against
 * every confirmed / live hazard available here.
 *
 * Hard rules:
 *  - A route that passes a CONFIRMED closure (blocked road segment) is NEVER
 *    safe, whatever Google says about it.
 *  - Live hazard proximity (flood risk, severe disaster events, high/critical
 *    active verified incidents near the path) is reported as a caution — the
 *    operator is told exactly what lies near the route; nothing is invented.
 */
import type { MapOverviewResponse } from '../../types';

export interface RouteHazardHit {
  /** Hazard kind. */
  kind: 'blocked-road' | 'flood-risk' | 'severe-event' | 'risky-road' | 'verified-incident';
  /** Human-readable hazard label for the directions panel. */
  label: string;
  /** Distance from the route geometry to the hazard, in meters (approx). */
  distanceMeters: number;
  /** Distance display helper. */
  distanceText: string;
}

export interface RouteSafetyAssessment {
  /** False when a confirmed closure (or an equivalent hard hazard) affects the route. */
  safe: boolean;
  /** True when no closure affects the route but live hazards are nearby. */
  caution: boolean;
  hits: RouteHazardHit[];
  /** Operator-facing one-line status, e.g. "NO_SAFE_ROUTE_AVAILABLE". */
  status: 'ROUTE_SAFE' | 'ROUTE_CAUTION' | 'NO_SAFE_ROUTE_AVAILABLE';
}

/** Confirmed-closure proximity threshold (meters). Blocked segment geometry is a straight chord
 * between its two road nodes, so this isolates "actually crosses the blocked section". */
const BLOCKED_ROAD_THRESHOLD_M = 120;
/** High-risk open road segment proximity — advisory only. */
const RISKY_ROAD_THRESHOLD_M = 80;
/** Distance from route geometry to a reported disaster hotspot for caution (meters). */
const INCIDENT_THRESHOLD_M = 300;
/** Flood-risk / severe event caution radius around the route (meters). */
const EVENT_CAUTION_RADIUS_M = 12000;
/** Maximum sample points checked per distance computation (performance bound). */
const MAX_SAMPLES = 700;
const EARTH_RADIUS_M = 6378137;

/** "350 m" / "3.2 km" distance text. */
function fmtDistance(meters: number): string {
  if (!Number.isFinite(meters)) return '—';
  if (meters >= 1000) return `${(meters / 1000).toFixed(1)} km`;
  return `${Math.round(meters)} m`;
}

/** Equirectangular point-to-segment distance, accurate enough at city scale. */
function metersToSegment(
  point: { lat: number; lng: number },
  a: { lat: number; lng: number },
  b: { lat: number; lng: number },
): number {
  const latRef = ((a.lat + b.lat) / 2) * (Math.PI / 180);
  const cosLat = Math.cos(latRef);
  const ax = a.lng * cosLat;
  const ay = a.lat;
  const bx = b.lng * cosLat;
  const by = b.lat;
  const px = point.lng * cosLat;
  const py = point.lat;
  const dx = bx - ax;
  const dy = by - ay;
  const lengthSq = dx * dx + dy * dy;
  if (lengthSq === 0) {
    const rx = px - ax;
    const ry = py - ay;
    return Math.sqrt(rx * rx + ry * ry) * (Math.PI / 180) * EARTH_RADIUS_M;
  }
  let t = ((px - ax) * dx + (py - ay) * dy) / lengthSq;
  t = Math.max(0, Math.min(1, t));
  const cx = ax + t * dx;
  const cy = ay + t * dy;
  const rx = px - cx;
  const ry = py - cy;
  return Math.sqrt(rx * rx + ry * ry) * (Math.PI / 180) * EARTH_RADIUS_M;
}

/** Point-to-point equirectangular distance in meters. */
function metersBetween(
  point: { lat: number; lng: number },
  other: { lat: number; lng: number },
): number {
  const dLat = ((other.lat - point.lat) * Math.PI) / 180;
  const dLng = ((other.lng - point.lng) * Math.PI) / 180;
  const latRef = ((other.lat + point.lat) / 2) * (Math.PI / 180);
  const x = dLng * Math.cos(latRef);
  return Math.sqrt(x * x + dLat * dLat) * EARTH_RADIUS_M;
}

function metersToPoints(
  point: { lat: number; lng: number },
  points: { lat: number; lng: number }[],
): number | null {
  let best: number | null = null;
  for (const other of points) {
    const d = metersBetween(point, other);
    if (best === null || d < best) best = d;
  }
  return best;
}

/** Sample every Nth point so large polylines stay cheap to verify. */
function sample<T>(items: T[]): T[] {
  if (items.length <= MAX_SAMPLES) return items;
  const stride = Math.ceil(items.length / MAX_SAMPLES);
  const out: T[] = [];
  for (let i = 0; i < items.length; i += stride) out.push(items[i]);
  if (out[out.length - 1] !== items[items.length - 1]) out.push(items[items.length - 1]);
  return out;
}

export function assessRouteSafety(
  path: { lat: number; lng: number }[],
  overview: MapOverviewResponse,
): RouteSafetyAssessment {
  const hits: RouteHazardHit[] = [];
  if (path.length < 2) {
    return { safe: false, caution: false, hits, status: 'NO_SAFE_ROUTE_AVAILABLE' };
  }
  const samples = sample(path);

  // --- 1. Confirmed closures: verified blocked road segments (hard constraint) ---
  const coordinates = new Map(overview.road_nodes.map((node) => [node.id, node]));
  for (const segment of overview.road_segments) {
    if (!segment.is_blocked) continue;
    const from = coordinates.get(segment.from_node_id);
    const to = coordinates.get(segment.to_node_id);
    if (!from || !to) continue;
    const fromPoint = { lat: from.latitude, lng: from.longitude };
    const toPoint = { lat: to.latitude, lng: to.longitude };
    let closest = Infinity;
    for (const point of samples) {
      const d = metersToSegment(point, fromPoint, toPoint);
      if (d < closest) closest = d;
    }
    if (closest <= BLOCKED_ROAD_THRESHOLD_M) {
      hits.push({
        kind: 'blocked-road',
        label: `Confirmed closure: ${segment.from_node_name} → ${segment.to_node_name}${
          segment.blockage_reason ? ` (${segment.blockage_reason})` : ''
        }`,
        distanceMeters: Math.round(closest),
        distanceText: fmtDistance(closest),
      });
    }
  }

  // --- 2. Advisor layers: flood risk + severe events near the path ---
  const events = overview.live_layers?.disaster_events ?? [];
  for (const event of events) {
    if (!Number.isFinite(event.latitude) || !Number.isFinite(event.longitude)) continue;
    const eventPoint = { lat: event.latitude, lng: event.longitude };
    let closest: number | null = null;
    for (const point of samples) {
      const d = metersToPoints(point, [eventPoint]);
      if (d !== null && (closest === null || d < closest)) closest = d;
    }
    if (closest === null || closest > EVENT_CAUTION_RADIUS_M) continue;
    const severe =
      event.alert_level === 'red' ||
      event.alert_level === 'orange' ||
      event.severity === 'critical' ||
      event.severity === 'high';
    const kind = severe ? 'severe-event' : 'flood-risk';
    hits.push({
      kind,
      label: `${severe ? 'Severe event' : 'Flood risk'} near route — ${event.title} (${kind === 'severe-event' ? event.source : event.source}: alert ${event.alert_level ?? 'n/a'})`,
      distanceMeters: Math.round(closest),
      distanceText: fmtDistance(closest),
    });
  }

  // --- 3. Verified, non-weather incidents reported on the route itself ---
  for (const incident of overview.incidents) {
    if (incident.is_demo !== false || incident.source === 'weather_api') continue;
    if (incident.status === 'resolved') continue;
    if (incident.severity !== 'critical' && incident.severity !== 'high') continue;
    if (!Number.isFinite(incident.latitude) || !Number.isFinite(incident.longitude)) continue;
    let closest: number | null = null;
    for (const point of samples) {
      const d = metersToPoints(point, [{ lat: incident.latitude, lng: incident.longitude }]);
      if (d !== null && (closest === null || d < closest)) closest = d;
    }
    if (closest !== null && closest <= INCIDENT_THRESHOLD_M) {
      hits.push({
        kind: 'verified-incident',
        label: `Active ${incident.severity} incident near route — ${incident.title} (${incident.location_name})`,
        distanceMeters: Math.round(closest),
        distanceText: fmtDistance(closest),
      });
    }
  }

  // --- 4. Open high-risk road segments used by the route (advisory) ---
  const nodeById = new Map(overview.road_nodes.map((node) => [node.id, node]));
  for (const segment of overview.road_segments) {
    if (segment.is_blocked) continue; // already covered above
    if (segment.risk_factor < 0.6) continue;
    const from = nodeById.get(segment.from_node_id);
    const to = nodeById.get(segment.to_node_id);
    if (!from || !to) continue;
    const fromPoint = { lat: from.latitude, lng: from.longitude };
    const toPoint = { lat: to.latitude, lng: to.longitude };
    let closest = Infinity;
    for (const point of samples) {
      const d = metersToSegment(point, fromPoint, toPoint);
      if (d < closest) closest = d;
    }
    if (closest <= RISKY_ROAD_THRESHOLD_M) {
      hits.push({
        kind: 'risky-road',
        label: `High-risk open road section encountered — ${segment.from_node_name} → ${segment.to_node_name} (risk factor ${segment.risk_factor})`,
        distanceMeters: Math.round(closest),
        distanceText: fmtDistance(closest),
      });
    }
  }

  const unsafeHits = hits.filter((hit) => hit.kind === 'blocked-road');
  const safe = unsafeHits.length === 0;
  return {
    safe,
    caution: safe && hits.length > 0,
    hits,
    status: safe ? (hits.length > 0 ? 'ROUTE_CAUTION' : 'ROUTE_SAFE') : 'NO_SAFE_ROUTE_AVAILABLE',
  };
}
