/**
 * Route coordinate helpers + Google Maps Routes library client.
 *
 * Two distinct, clearly separated sources of route geometry exist:
 *
 * 1. Backend routing (source of truth for logistics routes): the backend
 *    (`ROUTING_NETWORK=real`) returns full road-following geometry as a GeoJSON
 *    LineString with [longitude, latitude] coordinates, computed on the real
 *    OpenStreetMap drive network (OSMnx + NetworkX). `geoJsonToLatLng` only
 *    converts that payload into Google Maps `{lat, lng}` points.
 *
 * 2. Emergency Navigation route planner (explicit operator request only):
 *    `computeGoogleRoute` calls the Maps JavaScript API Routes library via
 *    `google.maps.importLibrary("routes")` and the static
 *    `Route.computeRoutes(request)`. The legacy DirectionsService is NOT used.
 */

export interface LatLng {
  lat: number;
  lng: number;
}

/** Stable cache key derived from the actual coordinates. */
export function routeCacheKey(points: LatLng[]): string {
  return points.map((p) => `${p.lat.toFixed(5)},${p.lng.toFixed(5)}`).join(';');
}

/**
 * Convert backend GeoJSON LineString coordinates ([lng, lat] pairs) into the
 * ordered LatLng list Google Maps polylines expect. Invalid / non-finite /
 * mis-ordered points are skipped; at least two clean points are required.
 */
export function geoJsonToLatLng(coords: [number, number][] | [number, number][][] | undefined | null): LatLng[] {
  if (!Array.isArray(coords)) return [];
  const points: LatLng[] = [];
  for (const pair of coords) {
    if (!Array.isArray(pair) || pair.length < 2) continue;
    const [lng, lat] = pair;
    if (typeof lng !== 'number' || typeof lat !== 'number') continue;
    if (!Number.isFinite(lat) || !Number.isFinite(lng)) continue;
    const point: LatLng = { lat, lng };
    if (
      points.length === 0 ||
      points[points.length - 1].lat !== lat ||
      points[points.length - 1].lng !== lng
    ) {
      points.push(point);
    }
  }
  return points;
}

// ============================================================================
// Google Maps Routes library client (`importLibrary("routes")`)
// ============================================================================

/** Travel modes the route planner exposes. */
export type PlannerTravelMode = 'DRIVING' | 'WALKING' | 'BICYCLING';

/** A single navigation instruction along a computed Google route. */
export interface PlannerRouteStep {
  instructions: string;
  maneuver: string | null;
  distanceMeters: number;
  distanceText: string | null;
  staticDurationText: string | null;
  startLocation: LatLng | null;
  endLocation: LatLng | null;
}

/** Parsed Route.computeRoutes() result used by the planner UI and map overlay. */
export interface PlannerRouteResult {
  /** Full road-following geometry as {lat, lng} points (Route.path). */
  path: LatLng[];
  distanceMeters: number;
  /** Traffic-aware duration in ms (equals staticDuration when an error, or ∞ if exceeded 2^53). */
  durationMillis: number | null;
  staticDurationMillis: number | null;
  distanceText: string | null;
  durationText: string | null;
  staticDurationText: string | null;
  steps: PlannerRouteStep[];
  warnings: string[];
  routeLabels: string[];
  /** Snapped start / end points as returned by Google (may differ slightly from the input). */
  startLocation: LatLng | null;
  endLocation: LatLng | null;
  fallbackInfo: { routingMode: string | null; reason: string | null } | null;
}

/** Memoised Routes library import — `importLibrary` is idempotent per page load. */
let routesLibraryPromise: Promise<google.maps.RoutesLibrary> | null = null;

export function loadRoutesLibrary(): Promise<google.maps.RoutesLibrary> {
  if (!routesLibraryPromise) {
    routesLibraryPromise = google.maps.importLibrary('routes');
  }
  return routesLibraryPromise;
}

/** Field mask: only fields the planner actually renders. The JS library takes
 * the top-level `legs` field as-is (sub-paths like legs.steps.* are rejected). */
const ROUTE_FIELDS = [
  'distanceMeters',
  'durationMillis',
  'staticDurationMillis',
  'path',
  'legs',
  'localizedValues',
  'viewport',
  'warnings',
  'routeLabels',
];

/**
 * Compute a route with the Routes library and parse it into plain data for the
 * planner. Returns `null` when Google returns no route (surfaced upstream as
 * NO_ROUTE_AVAILABLE — no fallback route is ever invented).
 */
export async function computeGoogleRoute(request: {
  origin: LatLng;
  destination: LatLng;
  travelMode: PlannerTravelMode;
}): Promise<PlannerRouteResult | null> {
  const { Route } = await loadRoutesLibrary();
  const response = await Route.computeRoutes({
    origin: { lat: request.origin.lat, lng: request.origin.lng },
    destination: { lat: request.destination.lat, lng: request.destination.lng },
    travelMode: request.travelMode,
    fields: ROUTE_FIELDS,
  });

  const route = response.routes?.[0];
  if (!route) return null;

  const path: LatLng[] = [];
  for (const point of route.path ?? []) {
    const lat = point.lat;
    const lng = point.lng;
    if (typeof lat !== 'number' || typeof lng !== 'number') continue;
    if (!Number.isFinite(lat) || !Number.isFinite(lng)) continue;
    if (
      path.length === 0 ||
      path[path.length - 1].lat !== lat ||
      path[path.length - 1].lng !== lng
    ) {
      path.push({ lat, lng });
    }
  }
  if (path.length < 2) return null; // cannot draw a meaningful route line

  const steps: PlannerRouteStep[] = [];
  for (const leg of route.legs ?? []) {
    for (const step of leg.steps ?? []) {
      const instructions = step.instructions ?? '';
      if (!instructions) continue;
      steps.push({
        instructions,
        maneuver: step.maneuver ?? null,
        distanceMeters: step.distanceMeters ?? 0,
        distanceText: step.localizedValues?.distance ?? null,
        staticDurationText: step.localizedValues?.staticDuration ?? null,
        startLocation: stepLocation(step.startLocation),
        endLocation: stepLocation(step.endLocation),
      });
    }
  }

  const durationMillis = finiteMs(route.durationMillis);
  const staticDurationMillis = finiteMs(route.staticDurationMillis);

  return {
    path,
    distanceMeters: route.distanceMeters ?? 0,
    durationMillis,
    staticDurationMillis,
    distanceText: route.localizedValues?.distance ?? formatDistanceMeters(route.distanceMeters ?? 0),
    // Traffic-aware duration text; falls back to the static duration wording.
    durationText:
      route.localizedValues?.duration ??
      formatDurationMillis(durationMillis ?? staticDurationMillis),
    staticDurationText: formatDurationMillis(staticDurationMillis),
    steps,
    warnings: route.warnings ?? [],
    routeLabels: (route.routeLabels ?? []) as string[],
    startLocation: stepLocation(route.legs?.[0]?.startLocation ?? null),
    endLocation: stepLocation(route.legs?.[route.legs.length - 1]?.endLocation ?? null),
    fallbackInfo: response.fallbackInfo
      ? {
          routingMode: response.fallbackInfo.routingMode ?? null,
          reason: response.fallbackInfo.reason ?? null,
        }
      : null,
  };
}

function stepLocation(
  location: google.maps.routes.DirectionalLocation | null,
): LatLng | null {
  if (!location) return null;
  const lat = location.lat;
  const lng = location.lng;
  if (typeof lat !== 'number' || typeof lng !== 'number') return null;
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null;
  return { lat, lng };
}

/** HTTP-like infinite / non-finite durations collapse to `null`. */
function finiteMs(value: number | null | undefined): number | null {
  if (value === null || value === undefined) return null;
  return Number.isFinite(value) ? value : null;
}

/** "12.4 km" style formatting from meters. */
export function formatDistanceMeters(meters: number): string {
  if (!Number.isFinite(meters)) return '—';
  if (meters >= 1000) return `${(meters / 1000).toFixed(meters >= 10000 ? 0 : 1)} km`;
  return `${Math.round(meters)} m`;
}

/** "1 h 25 m" style formatting from milliseconds. */
export function formatDurationMillis(ms: number | null): string {
  if (ms === null || !Number.isFinite(ms)) return '—';
  const totalMinutes = Math.round(ms / 60000);
  if (totalMinutes < 1) return '<1 m';
  if (totalMinutes < 60) return `${totalMinutes} m`;
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return minutes === 0 ? `${hours} h` : `${hours} h ${minutes} m`;
}
