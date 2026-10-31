import { useEffect, useRef, useState } from 'react';
import {
  fetchRoadRoute,
  routeCacheKey,
  RoadRouteError,
  type LatLng,
  type RoadRouteErrorKind,
} from '../api/googleRoutes';

export interface SnapState {
  status: 'loading' | 'ready' | 'failed';
  path?: LatLng[];
  error?: RoadRouteErrorKind;
}

/**
 * Resolves road-following geometry for each route (one request per distinct route).
 * Returns a map keyed by routeCacheKey(points). Nothing is requested when disabled.
 */
export function useRoadRoutes(routes: LatLng[][], enabled: boolean): Record<string, SnapState> {
  const [states, setStates] = useState<Record<string, SnapState>>({});
  const routesRef = useRef(routes);
  routesRef.current = routes;

  const signature = routes
    .filter((points) => points.length >= 2)
    .map(routeCacheKey)
    .join('|');

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;

    for (const points of routesRef.current) {
      if (points.length < 2) continue;
      const key = routeCacheKey(points);
      setStates((current) => (current[key] ? current : { ...current, [key]: { status: 'loading' } }));
      fetchRoadRoute(points).then(
        (route) => {
          if (!cancelled) setStates((c) => ({ ...c, [key]: { status: 'ready', path: route.path } }));
        },
        (error: unknown) => {
          if (cancelled) return;
          const kind = error instanceof RoadRouteError ? error.kind : 'failed';
          setStates((c) => ({ ...c, [key]: { status: 'failed', error: kind } }));
        },
      );
    }

    return () => {
      cancelled = true;
    };
  }, [signature, enabled]);

  return states;
}
