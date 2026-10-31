import { useEffect, useMemo, useRef, useState } from 'react';
import {
  APIProvider,
  AdvancedMarker,
  ColorScheme,
  Map,
  Pin,
  Polyline,
  useApiIsLoaded,
  useMap,
} from '@vis.gl/react-google-maps';
import { Expand, Minimize, Crosshair } from 'lucide-react';
import type {
  MapOverviewResponse,
  Priority,
  VehicleStatus,
} from '../../types';
import { titleCase } from '../../utils/format';
import { routeCacheKey, type LatLng } from '../../api/googleRoutes';
import { useRoadRoutes } from '../../hooks/useRoadRoutes';

export type EntitySelection =
  | { kind: 'warehouse'; id: number }
  | { kind: 'centre'; id: number }
  | { kind: 'vehicle'; id: number }
  | { kind: 'incident'; id: number }
  | { kind: 'segment'; id: number }
  | null;

export interface RouteOverlay {
  /** Ordered node ids along the route (from backend route_nodes). */
  nodeIds: number[];
  label: string;
  /** Overrides the base colour. Default for an active route is orange. */
  color?: string;
  /** Dashed = muted "previous / alternative" route (no glow, no stop markers). */
  dashed?: boolean;
}

interface Props {
  overview: MapOverviewResponse | null;
  height?: number;
  routeOverlays?: RouteOverlay[];
  onSelect?: (selection: NonNullable<EntitySelection>) => void;
  selected?: EntitySelection;
  fullscreen?: boolean;
}

const MAP_ID = (import.meta.env.VITE_GOOGLE_MAP_ID as string | undefined) || 'DEMO_MAP_ID';

const ROUTE_ORANGE = '#FF8A1F';
const ROUTE_MUTED = '#8aa4bf';
const START_ORANGE = '#F28C28';
const STOP_TEAL = '#1FA37A';
const ROAD_NORMAL = '#6db3f2';

const PRIORITY_COLORS: Record<Priority, string> = {
  critical: '#f15b5b',
  high: '#ff963d',
  medium: '#ffd740',
  low: '#21b989',
};

const VEHICLE_COLORS: Record<VehicleStatus, string> = {
  available: '#21b989',
  assigned: '#319aff',
  in_transit: '#21c5c2',
  delayed: '#ff963d',
  maintenance: '#f15b5b',
};

const PATH_WAREHOUSE = 'M2 20V8l10-5 10 5v12h-6v-7H8v7H2z';
const PATH_PLUS = 'M10 3h4v7h7v4h-7v7h-4v-7H3v-4h7V3z';
const PATH_TRUCK =
  'M1 5h13v10H1V5zm13 4h5l3 4v2h-8V9zM4 16a1.8 1.8 0 104 0 1.8 1.8 0 10-4 0zM16 16a1.8 1.8 0 104 0 1.8 1.8 0 10-4 0z';
const PATH_ALERT = 'M12 2 1 21h22L12 2zm1 14h-2v2h2v-2zm0-7h-2v5h2V9z';

/** Mix a #rrggbb colour towards white by t (0..1). */
function lighten(hex: string, t: number): string {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex);
  if (!m) return hex;
  const n = parseInt(m[1], 16);
  const channel = (shift: number) => {
    const c = (n >> shift) & 255;
    return Math.round(c + (255 - c) * t)
      .toString(16)
      .padStart(2, '0');
  };
  return `#${channel(16)}${channel(8)}${channel(0)}`;
}

function dashIcons(color: string): google.maps.IconSequence[] {
  return [
    {
      icon: { path: 'M 0,-1 0,1', strokeColor: color, strokeOpacity: 0.8, scale: 3 },
      offset: '0',
      repeat: '14px',
    },
  ];
}

function EntityPin({
  color,
  glyph,
  size,
  ring = false,
}: {
  color: string;
  glyph: string;
  size: number;
  ring?: boolean;
}) {
  return (
    <div
      style={{
        width: size,
        height: size,
        boxSizing: 'border-box',
        borderRadius: '50%',
        background: color,
        border: '1px solid #071321',
        display: 'grid',
        placeItems: 'center',
        boxShadow: ring ? '0 0 0 3px rgba(255,255,255,0.85)' : '0 1px 3px rgba(0,0,0,0.5)',
      }}
    >
      <svg width={size * 0.62} height={size * 0.62} viewBox="0 0 24 24" aria-hidden="true">
        <path d={glyph} fill="#071321" />
      </svg>
    </div>
  );
}

function CircleBadge({
  color,
  children,
}: {
  color: string;
  children?: React.ReactNode;
}) {
  return (
    <div
      style={{
        width: 28,
        height: 28,
        boxSizing: 'border-box',
        borderRadius: '50%',
        background: color,
        border: '3px solid #fff',
        boxShadow: '0 2px 6px rgba(0,0,0,0.45)',
        display: 'grid',
        placeItems: 'center',
        color: '#fff',
        fontSize: 12,
        fontWeight: 700,
        lineHeight: 1,
      }}
    >
      {children}
    </div>
  );
}

/** Imperative map behaviour: reset view and fit-to-route. Renders nothing. */
function MapEffects({
  resetNonce,
  center,
  zoom,
  fitKey,
  fitPath,
}: {
  resetNonce: number;
  center: LatLng;
  zoom: number;
  fitKey: string | null;
  fitPath: LatLng[];
}) {
  const map = useMap();
  const latest = useRef({ center, zoom, fitPath });
  latest.current = { center, zoom, fitPath };

  useEffect(() => {
    if (!map || resetNonce === 0) return;
    map.panTo(latest.current.center);
    map.setZoom(latest.current.zoom);
  }, [map, resetNonce]);

  // Fit only when the route itself changes — never on data polling.
  useEffect(() => {
    if (!map || !fitKey) return;
    const path = latest.current.fitPath;
    if (path.length < 2) return;
    const bounds = new google.maps.LatLngBounds();
    path.forEach((p) => bounds.extend(p));
    map.fitBounds(bounds, 60);
  }, [map, fitKey]);

  return null;
}

function LoadingOverlay() {
  const loaded = useApiIsLoaded();
  if (loaded) return null;
  return (
    <div
      className="loading-skeleton block"
      aria-label="Loading Google Maps"
      style={{ position: 'absolute', inset: 0, zIndex: 1 }}
    />
  );
}

export function DisasterMap({
  overview,
  height,
  routeOverlays = [],
  onSelect,
  selected,
  fullscreen,
}: Props) {
  const [visible, setVisible] = useState<Record<string, boolean>>({
    warehouses: true,
    centres: true,
    vehicles: true,
    roads: true,
    blocked: true,
    incidents: true,
    routes: true,
    snap: true,
  });
  const [isFullscreen, setIsFullscreen] = useState(false);
  const fullscreenActive = fullscreen || isFullscreen;
  const [resetNonce, setResetNonce] = useState(0);
  const [loadFailed, setLoadFailed] = useState(false);
  const [authFailed, setAuthFailed] = useState(false);
  const apiKey = (import.meta.env.VITE_GOOGLE_MAPS_API_KEY as string | undefined) || '';

  // Google calls this global when the key is rejected (invalid / restricted / quota).
  useEffect(() => {
    const w = window as unknown as { gm_authFailure?: () => void };
    w.gm_authFailure = () => setAuthFailed(true);
    return () => {
      delete w.gm_authFailure;
    };
  }, []);

  const coordinates = useMemo(() => {
    const byId = new globalThis.Map<number, LatLng>();
    overview?.road_nodes.forEach((node) =>
      byId.set(node.id, { lat: node.latitude, lng: node.longitude }),
    );
    return byId;
  }, [overview]);

  const nodeNames = useMemo(() => {
    const byId = new globalThis.Map<number, string>();
    overview?.road_nodes.forEach((node) => byId.set(node.id, node.node_name));
    return byId;
  }, [overview]);

  const routeLayers = useMemo(() => {
    return routeOverlays.map((overlay, index) => {
      const points: LatLng[] = [];
      const stops: { id: number; point: LatLng }[] = [];
      for (const nodeId of overlay.nodeIds) {
        const point = coordinates.get(nodeId);
        if (!point) continue;
        points.push(point);
        stops.push({ id: nodeId, point });
      }
      return { ...overlay, index, points, stops, key: routeCacheKey(points) };
    });
  }, [routeOverlays, coordinates]);

  const snapEnabled = visible.routes && visible.snap;
  const snapStates = useRoadRoutes(
    routeLayers.map((layer) => layer.points),
    snapEnabled,
  );

  // Geometry actually drawn for each route (null = still loading, draw nothing yet).
  const drawn = routeLayers.map((layer) => {
    if (layer.points.length < 2) return { layer, path: null as LatLng[] | null, snapped: false, failed: null as string | null };
    if (!snapEnabled) return { layer, path: layer.points, snapped: false, failed: null };
    const state = snapStates[layer.key];
    if (!state || state.status === 'loading') return { layer, path: null, snapped: false, failed: null };
    if (state.status === 'ready' && state.path) return { layer, path: state.path, snapped: true, failed: null };
    return { layer, path: layer.points, snapped: false, failed: state.error ?? 'failed' };
  });

  const primary = drawn.find((d) => !d.layer.dashed && d.path);
  const fitKey = primary ? `${primary.layer.key}:${primary.snapped ? 's' : 'f'}` : null;
  const anySnapped = drawn.some((d) => d.snapped);
  const anyLoading = snapEnabled && drawn.some((d) => d.layer.points.length >= 2 && d.path === null);
  const failure = drawn.find((d) => d.failed)?.failed ?? null;

  if (!overview) return null;
  if (!apiKey) {
    return <div className="error-state"><div className="error-message">Google Maps key missing. Set VITE_GOOGLE_MAPS_API_KEY in frontend/.env.local and restart Vite.</div></div>;
  }
  if (loadFailed) {
    return <div className="error-state"><div className="error-message">Google Maps failed to load. Check VITE_GOOGLE_MAPS_API_KEY, API restrictions and your network.</div></div>;
  }

  const center: LatLng = { lat: overview.center.latitude, lng: overview.center.longitude };
  const hasVehicleCoords = (lat: number | null, lng: number | null) =>
    lat !== null && lng !== null && Number.isFinite(lat) && Number.isFinite(lng);

  const isMarkerSelected = (kind: NonNullable<EntitySelection>['kind'], id: number) =>
    selected?.kind === kind && selected.id === id;

  const toggle = (key: string) => setVisible((current) => ({ ...current, [key]: !current[key] }));

  return (
    <div
      className={
        fullscreenActive
          ? 'map-canvas'
          : 'map-container'
      }
      style={
        fullscreenActive
          ? { position: 'fixed', inset: 10, zIndex: 1500 }
          : height
            ? { height }
            : undefined
      }
    >
      <APIProvider apiKey={apiKey} onError={() => setLoadFailed(true)}>
        <Map
          mapId={MAP_ID}
          colorScheme={ColorScheme.DARK}
          defaultCenter={center}
          defaultZoom={overview.center.zoom}
          style={{ height: '100%', width: '100%' }}
          streetViewControl={false}
          mapTypeControl
          fullscreenControl={false}
          clickableIcons={false}
        >
          <MapEffects
            resetNonce={resetNonce}
            center={center}
            zoom={overview.center.zoom}
            fitKey={fitKey}
            fitPath={primary?.path ?? []}
          />

          {/* Road network (straight segments between simulated nodes) */}
          {visible.roads &&
            overview.road_segments
              .filter((segment) => !segment.is_blocked)
              .map((segment) => {
                const from = coordinates.get(segment.from_node_id);
                const to = coordinates.get(segment.to_node_id);
                if (!from || !to) return null;
                const risky = segment.risk_factor >= 0.6;
                return (
                  <Polyline
                    key={`seg-${segment.id}`}
                    path={[from, to]}
                    strokeColor={risky ? '#ff963d' : ROAD_NORMAL}
                    strokeWeight={risky ? 4 : 3}
                    strokeOpacity={risky ? 0.95 : 0.9}
                    onClick={() => onSelect?.({ kind: 'segment', id: segment.id })}
                  />
                );
              })}

          {/* Blocked roads */}
          {visible.blocked &&
            overview.road_segments
              .filter((segment) => segment.is_blocked)
              .map((segment) => {
                const from = coordinates.get(segment.from_node_id);
                const to = coordinates.get(segment.to_node_id);
                if (!from || !to) return null;
                return (
                  <Polyline
                    key={`blocked-${segment.id}`}
                    path={[from, to]}
                    strokeColor="#f15b5b"
                    strokeWeight={4.5}
                    strokeOpacity={0.95}
                    icons={[{ icon: { path: 'M 0,-1 0,1' }, repeat: '14px' }]}
                    onClick={() => onSelect?.({ kind: 'segment', id: segment.id })}
                  />
                );
              })}

          {/* Route overlays (backend-computed node order; geometry road-snapped for display) */}
          {visible.routes &&
            drawn.map(({ layer, path }) => {
              if (!path || path.length < 2) return null;
              if (layer.dashed) {
                return (
                  <Polyline
                    key={`route-${layer.index}`}
                    path={path}
                    strokeColor={layer.color ?? ROUTE_MUTED}
                    strokeOpacity={0}
                    icons={dashIcons(layer.color ?? ROUTE_MUTED)}
                    zIndex={20}
                  />
                );
              }
              const base = layer.color ?? ROUTE_ORANGE;
              return [
                <Polyline
                  key={`route-${layer.index}-glow`}
                  path={path}
                  strokeColor={base}
                  strokeWeight={14}
                  strokeOpacity={0.22}
                  zIndex={30}
                  clickable={false}
                />,
                <Polyline
                  key={`route-${layer.index}-edge`}
                  path={path}
                  strokeColor={lighten(base, 0.62)}
                  strokeWeight={9}
                  strokeOpacity={0.7}
                  zIndex={31}
                  clickable={false}
                />,
                <Polyline
                  key={`route-${layer.index}-core`}
                  path={path}
                  strokeColor={base}
                  strokeWeight={5}
                  strokeOpacity={1}
                  zIndex={32}
                  clickable={false}
                />,
              ];
            })}

          {/* Warehouses */}
          {visible.warehouses &&
            overview.warehouses.map((warehouse) => (
              <AdvancedMarker
                key={`wh-${warehouse.id}`}
                position={{ lat: warehouse.latitude, lng: warehouse.longitude }}
                title={`${warehouse.name} — ${warehouse.location_name}`}
                anchorTop="-50%"
                clickable
                onClick={() => onSelect?.({ kind: 'warehouse', id: warehouse.id })}
              >
                <EntityPin color="#21c5c2" glyph={PATH_WAREHOUSE} size={20} />
              </AdvancedMarker>
            ))}

          {/* Relief centres */}
          {visible.centres &&
            overview.relief_centres.map((centre) => {
              const isSelected = isMarkerSelected('centre', centre.id);
              return (
                <AdvancedMarker
                  key={`rc-${centre.id}`}
                  position={{ lat: centre.latitude, lng: centre.longitude }}
                  title={`${centre.name} — ${titleCase(centre.priority)} priority`}
                  anchorTop="-50%"
                  clickable
                  onClick={() => onSelect?.({ kind: 'centre', id: centre.id })}
                >
                  <EntityPin
                    color={PRIORITY_COLORS[centre.priority]}
                    glyph={PATH_PLUS}
                    size={isSelected ? 24 : 20}
                    ring={isSelected}
                  />
                </AdvancedMarker>
              );
            })}

          {/* Vehicles (backend positions only — no invented coordinates) */}
          {visible.vehicles &&
            overview.vehicles
              .filter((vehicle) => hasVehicleCoords(vehicle.current_latitude, vehicle.current_longitude))
              .map((vehicle) => (
                <AdvancedMarker
                  key={`veh-${vehicle.id}`}
                  position={{ lat: vehicle.current_latitude!, lng: vehicle.current_longitude! }}
                  title={`${vehicle.vehicle_code} — ${titleCase(vehicle.status)}`}
                  anchorTop="-50%"
                  clickable
                  onClick={() => onSelect?.({ kind: 'vehicle', id: vehicle.id })}
                >
                  <EntityPin color={VEHICLE_COLORS[vehicle.status]} glyph={PATH_TRUCK} size={18} />
                </AdvancedMarker>
              ))}

          {/* Incidents */}
          {visible.incidents &&
            overview.incidents.map((incident) => (
              <AdvancedMarker
                key={`inc-${incident.id}`}
                position={{ lat: incident.latitude, lng: incident.longitude }}
                title={`${incident.title} — ${titleCase(incident.severity)}`}
                anchorTop="-50%"
                clickable
                onClick={() => onSelect?.({ kind: 'incident', id: incident.id })}
              >
                <EntityPin color="#f15b5b" glyph={PATH_ALERT} size={20} />
              </AdvancedMarker>
            ))}

          {/* Active route markers: start pin, numbered stops, end circle */}
          {visible.routes &&
            drawn.flatMap(({ layer, path }) => {
              if (layer.dashed || !path || layer.stops.length < 2) return [];
              const first = layer.stops[0];
              const last = layer.stops[layer.stops.length - 1];
              const middle = layer.stops.slice(1, -1);
              const name = (id: number) => nodeNames.get(id) ?? `Node ${id}`;
              return [
                <AdvancedMarker
                  key={`route-${layer.index}-start`}
                  position={first.point}
                  title={`Route start — ${name(first.id)}`}
                  zIndex={42}
                >
                  <Pin background={START_ORANGE} borderColor="#ffffff" glyphColor="#ffffff" scale={1.25} />
                </AdvancedMarker>,
                ...middle.map((stop, i) => (
                  <AdvancedMarker
                    key={`route-${layer.index}-stop-${stop.id}-${i}`}
                    position={stop.point}
                    title={`Stop ${String(i + 1).padStart(2, '0')} — ${name(stop.id)}`}
                    anchorTop="-50%"
                    zIndex={41}
                  >
                    <CircleBadge color={STOP_TEAL}>{String(i + 1).padStart(2, '0')}</CircleBadge>
                  </AdvancedMarker>
                )),
                <AdvancedMarker
                  key={`route-${layer.index}-end`}
                  position={last.point}
                  title={`Route end — ${name(last.id)}`}
                  anchorTop="-50%"
                  zIndex={43}
                >
                  <CircleBadge color={START_ORANGE} />
                </AdvancedMarker>,
              ];
            })}
          <LoadingOverlay />
        </Map>
      </APIProvider>

      {/* Toolbar */}
      <div className="map-toolbar">
        <button
          className="map-btn"
          title="Reset view"
          aria-label="Reset map view"
          onClick={() => setResetNonce((n) => n + 1)}
        >
          <Crosshair size={15} />
        </button>
        <button
          className="map-btn"
          title={fullscreenActive ? 'Exit fullscreen' : 'Fullscreen map'}
          aria-label="Toggle fullscreen map"
          onClick={() => setIsFullscreen((value) => !value)}
        >
          {fullscreenActive ? <Minimize size={15} /> : <Expand size={15} />}
        </button>
      </div>

      {/* Layer controls */}
      <div className="layer-controls">
        {(
          [
            ['warehouses', 'Warehouses'],
            ['centres', 'Relief centres'],
            ['vehicles', 'Vehicles'],
            ['roads', 'Road network'],
            ['blocked', 'Blocked roads'],
            ['incidents', 'Incidents'],
            ['routes', 'Active routes'],
            ['snap', 'Snap routes to roads'],
          ] as const
        ).map(([key, label]) => (
          <label key={key} className="layer-toggle">
            <input type="checkbox" checked={visible[key]} onChange={() => toggle(key)} />
            {label}
          </label>
        ))}
      </div>

      {/* Key / API problems surface here instead of a silent grey map */}
      {authFailed && (
        <div className="map-overlay map-note" role="alert">
          Google rejected the Maps key (invalid, restricted, or demo quota reached).
        </div>
      )}
      {!authFailed && visible.routes && routeLayers.length > 0 && (
        <div className="map-overlay map-note">
          {anyLoading
            ? 'Snapping route to roads…'
            : failure
              ? `Showing straight-line route; road snapping unavailable${failure === 'quota' ? ' (quota reached)' : ''}.`
              : anySnapped
                ? 'Simulated network — route road-snapped for display only.'
                : null}
        </div>
      )}

      {/* Legend */}
      <div className="map-overlay map-legend">
        <h4>Legend</h4>
        <div className="legend-row">
          <span className="legend-dot" style={{ background: '#21c5c2' }} /> Warehouse
        </div>
        {(['critical', 'high', 'medium', 'low'] as Priority[]).map((priority) => (
          <div className="legend-row" key={priority}>
            <span className="legend-dot" style={{ background: PRIORITY_COLORS[priority] }} />
            Centre priority: {titleCase(priority)}
          </div>
        ))}
        <div className="legend-row">
          <span className="legend-swatch" style={{ background: ROAD_NORMAL }} /> Road (normal)
        </div>
        <div className="legend-row">
          <span className="legend-swatch" style={{ background: '#ff963d' }} /> High-risk road
        </div>
        <div className="legend-row">
          <span className="legend-swatch" style={{ background: '#f15b5b' }} /> Blocked road
        </div>
        <div className="legend-row">
          <span className="legend-swatch" style={{ background: ROUTE_ORANGE, height: 4 }} /> Active route
        </div>
        <div className="legend-row">
          <span className="legend-dot" style={{ background: START_ORANGE }} /> Route start / end
        </div>
        <div className="legend-row">
          <span className="legend-dot" style={{ background: STOP_TEAL }} /> Route stop
        </div>
        <div className="legend-row muted">Vehicle markers: backend simulated positions only</div>
      </div>
    </div>
  );
}
