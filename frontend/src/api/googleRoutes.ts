/**
 * Google Routes API (Compute Routes) helper — DISPLAY ONLY.
 *
 * The backend remains the source of truth for which nodes a route uses. This module
 * only asks Google for road-following geometry through those same points so the
 * overlay can be drawn along real streets. Distance/ETA from Google are never used
 * by planning logic.
 *
 * Demo Key quota is per API per day, so: one request per route, results cached in
 * memory and sessionStorage, failures never retried in a tight loop.
 */

export interface LatLng {
  lat: number;
  lng: number;
}

export interface RoadRoute {
  path: LatLng[];
  distanceMeters: number | null;
  durationSeconds: number | null;
}

export type RoadRouteErrorKind = 'no-key' | 'quota' | 'denied' | 'failed';

export class RoadRouteError extends Error {
  kind: RoadRouteErrorKind;
  constructor(kind: RoadRouteErrorKind, message: string) {
    super(message);
    this.kind = kind;
  }
}

const ENDPOINT = 'https://routes.googleapis.com/directions/v2:computeRoutes';
const FIELD_MASK = 'routes.polyline.geoJsonLinestring,routes.distanceMeters,routes.duration';
const STORAGE_PREFIX = 'roadroute:v1:';
const MAX_INTERMEDIATES = 25;
const RETRY_AFTER_MS = 60_000;

const inFlight = new Map<string, Promise<RoadRoute>>();

/** Stable cache key derived from the actual coordinates. */
export function routeCacheKey(points: LatLng[]): string {
  return points.map((p) => `${p.lat.toFixed(5)},${p.lng.toFixed(5)}`).join(';');
}

function waypoint(point: LatLng, via = false) {
  return {
    location: { latLng: { latitude: point.lat, longitude: point.lng } },
    ...(via ? { via: true } : {}),
  };
}

function dedupe(points: LatLng[]): LatLng[] {
  return points.filter(
    (p, i) => i === 0 || p.lat !== points[i - 1].lat || p.lng !== points[i - 1].lng,
  );
}

function readStored(key: string): RoadRoute | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_PREFIX + key);
    return raw ? (JSON.parse(raw) as RoadRoute) : null;
  } catch {
    return null;
  }
}

function writeStored(key: string, route: RoadRoute) {
  try {
    sessionStorage.setItem(STORAGE_PREFIX + key, JSON.stringify(route));
  } catch {
    /* storage unavailable or full — memory cache still works */
  }
}

async function request(points: LatLng[]): Promise<RoadRoute> {
  const apiKey = import.meta.env.VITE_GOOGLE_MAPS_API_KEY as string | undefined;
  if (!apiKey) throw new RoadRouteError('no-key', 'VITE_GOOGLE_MAPS_API_KEY is not set');

  const pts = dedupe(points);
  if (pts.length < 2) throw new RoadRouteError('failed', 'Need at least two distinct points');

  let middle = pts.slice(1, -1);
  if (middle.length > MAX_INTERMEDIATES) {
    const step = middle.length / MAX_INTERMEDIATES;
    middle = Array.from({ length: MAX_INTERMEDIATES }, (_, i) => middle[Math.floor(i * step)]);
  }

  let response: Response;
  try {
    response = await fetch(ENDPOINT, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Goog-Api-Key': apiKey,
        'X-Goog-FieldMask': FIELD_MASK,
      },
      body: JSON.stringify({
        origin: waypoint(pts[0]),
        destination: waypoint(pts[pts.length - 1]),
        // Pass-through waypoints: shape the route without forcing stops.
        intermediates: middle.map((p) => waypoint(p, true)),
        travelMode: 'DRIVE',
        polylineEncoding: 'GEO_JSON_LINESTRING',
      }),
    });
  } catch {
    throw new RoadRouteError('failed', 'Network error calling Routes API');
  }

  if (!response.ok) {
    if (response.status === 429) throw new RoadRouteError('quota', 'Routes API quota reached');
    if (response.status === 401 || response.status === 403) {
      throw new RoadRouteError('denied', 'Routes API rejected the key');
    }
    throw new RoadRouteError('failed', `Routes API returned ${response.status}`);
  }

  const data = (await response.json()) as {
    routes?: {
      distanceMeters?: number;
      duration?: string;
      polyline?: { geoJsonLinestring?: { coordinates?: [number, number][] } };
    }[];
  };
  const first = data.routes?.[0];
  const coords = first?.polyline?.geoJsonLinestring?.coordinates;
  if (!coords || coords.length < 2) throw new RoadRouteError('failed', 'Routes API returned no route');

  return {
    path: coords.map(([lng, lat]) => ({ lat, lng })),
    distanceMeters: first?.distanceMeters ?? null,
    durationSeconds: first?.duration ? parseInt(first.duration, 10) || null : null,
  };
}

/** Fetch (or reuse) road-following geometry through the given ordered points. */
export function fetchRoadRoute(points: LatLng[]): Promise<RoadRoute> {
  const key = routeCacheKey(points);

  const stored = readStored(key);
  if (stored) return Promise.resolve(stored);

  const pending = inFlight.get(key);
  if (pending) return pending;

  const promise = request(points).then(
    (route) => {
      writeStored(key, route);
      inFlight.delete(key);
      return route;
    },
    (error: unknown) => {
      // Keep the failure briefly so re-renders don't hammer a quota-limited API.
      setTimeout(() => inFlight.delete(key), RETRY_AFTER_MS);
      throw error;
    },
  );
  inFlight.set(key, promise);
  return promise;
}
