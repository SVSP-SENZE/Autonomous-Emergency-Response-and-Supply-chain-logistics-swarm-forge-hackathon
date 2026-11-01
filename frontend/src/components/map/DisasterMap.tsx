import { Component, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import {
  APIProvider,
  AdvancedMarker,
  ColorScheme,
  InfoWindow,
  Map,
  Pin,
  Polyline,
  useApiIsLoaded,
  useMap,
} from '@vis.gl/react-google-maps';
import { Expand, Minimize, Crosshair } from 'lucide-react';
import type {
  LiveLayerStatus,
  MapDisasterEvent,
  MapFacility,
  MapLiveLayers,
  MapOverviewResponse,
  MapRiverGauge,
  MapWeatherStation,
  Priority,
  Severity,
  VehicleStatus,
} from '../../types';
import { formatDateTime, titleCase } from '../../utils/format';
import { routeCacheKey, type LatLng } from '../../api/googleRoutes';

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
  /**
   * Backend road geometry (GeoJSON [lng, lat] converted to {lat, lng}).
   * When present this IS the drawn line — actual mapped roads from the OSM
   * routing network. When absent, nothing is drawn (no straight-line
   * fallback); only start/end markers appear.
   */
  geometry?: LatLng[];
  /** Where this route's geometry came from (drives the map footnote). */
  source?: 'osm-network' | 'google-directions';
  /** Disaster-awareness verdict attached by the planner (null when unchecked). */
  safe?: boolean | null;
  /** ISO timestamp attached when the planner laid this route down. */
  plannedAt?: string | null;
}

/** The three functional map layers / modes of the Disaster Map. */
export type MapMode = 'disaster' | 'navigation' | 'logistics';

const MODE_LABELS: Record<MapMode, string> = {
  disaster: 'Disaster Intelligence',
  navigation: 'Emergency Navigation',
  logistics: 'Logistics Operations',
};

/** Which overlay layers each mode shows by default (operator can still change them). */
const MODE_PRESETS: Record<MapMode, { roads: boolean }> = {
  disaster: { roads: false },
  navigation: { roads: false },
  logistics: { roads: true },
};

interface Props {
  overview: MapOverviewResponse | null;
  height?: number;
  routeOverlays?: RouteOverlay[];
  onSelect?: (selection: NonNullable<EntitySelection>) => void;
  selected?: EntitySelection;
  fullscreen?: boolean;
  /** Active functional mode. Default: 'disaster'. */
  mode?: MapMode;
  /** Pass to show the mode switcher; omit for pages fixed to one mode. */
  onModeChange?: (mode: MapMode) => void;
  /** Increment to fit the primary route on the map (Fit Route button). */
  fitNonce?: number;
}

const MAP_ID = (import.meta.env.VITE_GOOGLE_MAP_ID as string | undefined) || 'DEMO_MAP_ID';

const ROUTE_ORANGE = '#FF8A1F';
const ROUTE_MUTED = '#8aa4bf';
const START_ORANGE = '#F28C28';
const STOP_TEAL = '#1FA37A';
const ROAD_NORMAL = '#6db3f2';

// Live external-data layer colours (matched by the legend below).
// Weather: cyan · Flood risk: orange · Severe incidents: red
// Hospitals/facilities: blue · River monitoring: teal
const WEATHER_CYAN = '#21c5c2';
const FLOOD_ORANGE = '#ff963d';
const SEVERE_RED = '#f15b5b';
const FACILITY_BLUE = '#319aff';
const RIVER_TEAL = '#1FA37A';

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
const PATH_CLOUD = 'M7 19a4 4 0 01-.6-7.95A6 6 0 0118.2 9.5 3.75 3.75 0 0117.5 19H7z';
const PATH_WATER =
  'M12 2.5s5.5 6.6 5.5 10.4a5.5 5.5 0 11-11 0C6.5 9.1 12 2.5 12 2.5z';

export type PopupTarget =
  | { kind: 'weather'; station: MapWeatherStation; position: LatLng }
  | { kind: 'river'; gauge: MapRiverGauge; position: LatLng }
  | { kind: 'event'; event: MapDisasterEvent; position: LatLng }
  | { kind: 'facility'; facility: MapFacility; position: LatLng }
  | {
      kind: 'incident-live';
      position: LatLng;
      title: string;
      rows: [string, string][];
      severity: Severity | null;
      source: string;
      updated: string | null;
    }
  | null;

/** Formatting helper for temperature / precipitation / wind values. */
function fmt(value: number | null | undefined, unit: string, decimals = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return `${value.toFixed(decimals)}${unit ? ` ${unit}` : ''}`;
}

/** Strict coordinate guard: markers are never drawn from invented values. */
function hasOrderedCoords(lat: number | null | undefined, lng: number | null | undefined): lat is number {
  return lat !== null && lng !== null && lat !== undefined && lng !== undefined
    && Number.isFinite(lat) && Number.isFinite(lng);
}

/** Severity categories for the flood / severe split of external events. */
function isSevereEvent(event: MapDisasterEvent): boolean {
  if (event.alert_level === 'red' || event.alert_level === 'orange') return true;
  if (event.severity === 'critical' || event.severity === 'high') return true;
  return (event.category ?? '').toLowerCase().includes('storm');
}

function isFloodEvent(event: MapDisasterEvent): boolean {
  if (isSevereEvent(event)) return false;
  const category = (event.category ?? '').toLowerCase();
  return category.includes('flood') || category === 'tc' || category === 'fl' || category.includes('cyclone');
}

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
  sim = false,
}: {
  color: string;
  glyph: string;
  size: number;
  ring?: boolean;
  /** Rendered like a normal pin but dashed-outlined: only for SIMULATED demo records. */
  sim?: boolean;
}) {
  return (
    <div
      style={{
        width: size,
        height: size,
        boxSizing: 'border-box',
        borderRadius: '50%',
        background: color,
        border: sim ? '1px dashed #ffffff' : '1px solid #071321',
        display: 'grid',
        placeItems: 'center',
        boxShadow: ring ? '0 0 0 3px rgba(255,255,255,0.85)' : '0 1px 3px rgba(0,0,0,0.5)',
        opacity: sim ? 0.85 : 1,
      }}
    >
      <svg width={size * 0.62} height={size * 0.62} viewBox="0 0 24 24" aria-hidden="true">
        <path d={glyph} fill="#071321" />
      </svg>
    </div>
  );
}

interface MapErrorBoundaryProps {
  children: ReactNode;
}

interface MapErrorBoundaryState {
  hasError: boolean;
}

class MapErrorBoundary extends Component<MapErrorBoundaryProps, MapErrorBoundaryState> {
  state: MapErrorBoundaryState = { hasError: false };

  static getDerivedStateFromError(): MapErrorBoundaryState {
    return { hasError: true };
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="error-state" role="alert">
          <div className="error-message">
            Google Maps is temporarily unavailable. Check the Maps API quota or billing settings; the rest of the console remains available.
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

export function DisasterMap(props: Props) {
  return (
    <MapErrorBoundary>
      <DisasterMapContent {...props} />
    </MapErrorBoundary>
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

interface PopupInfo {
  title: string;
  source: string;
  updated: string | null;
  severity: Severity | null;
  rows: [string, string][];
  link?: string | null;
}

function buildPopup(target: NonNullable<PopupTarget>): PopupInfo {
  switch (target.kind) {
    case 'weather':
      return {
        title: target.station.name,
        source: `${target.station.source} (Weather API)`,
        updated: target.station.updated_at,
        severity: target.station.severity,
        rows: [
          ['Location', `${target.station.name}${target.station.district ? `, ${target.station.district}` : ''}`],
          ['Temperature', fmt(target.station.temperature_c, '°C')],
          ['Precipitation now', fmt(target.station.precipitation_mm, 'mm')],
          ['Precipitation 24h', fmt(target.station.daily_precipitation_mm, 'mm')],
          ['Wind', `${fmt(target.station.wind_speed_kmh, 'km/h')} (gusts ${fmt(target.station.wind_gusts_kmh, 'km/h')})`],
          ['Assessment', target.station.assessment ?? '—'],
        ],
      };
    case 'river':
      return {
        title: target.gauge.name,
        source: `${target.gauge.source} (Flood API)`,
        updated: target.gauge.updated_at,
        severity: target.gauge.severity,
        rows: [
          ['River basin', target.gauge.river ?? '—'],
          ['Gauge location', fmt(target.gauge.latitude, '\u00B0N') + ', ' + fmt(target.gauge.longitude, '\u00B0E')],
          ['River discharge', fmt(target.gauge.river_discharge_m3s, 'm³/s')],
          ['Precipitation 24h', fmt(target.gauge.daily_precipitation_mm, 'mm')],
          ['Assessment', target.gauge.assessment ?? '—'],
        ],
      };
    case 'event':
      return {
        title: target.event.title,
        source: target.event.source,
        updated: target.event.updated_at ?? target.event.occurred_at,
        severity: target.event.severity,
        rows: [
          ['Category', target.event.category ?? '—'],
          ['Alert level', target.event.alert_level ? titleCase(target.event.alert_level) : 'Not provided'],
          ['Severity', target.event.severity_text ?? (target.event.severity ? titleCase(target.event.severity) : 'Not provided')],
          ['Coordinates', `${fmt(target.event.latitude, '\u00B0N')}, ${fmt(target.event.longitude, '\u00B0E')}`],
        ],
        link: target.event.link,
      };
    case 'facility':
      return {
        title: target.facility.name,
        source: target.facility.source,
        updated: target.facility.updated_at,
        severity: null,
        rows: [
          ['Type', 'Hospital / medical facility'],
          ['Town', target.facility.town ?? '—'],
          ['Address', target.facility.display_name ?? '—'],
          ['OSM ID', target.facility.osm_id ? `${target.facility.osm_type ?? 'osm'}/${target.facility.osm_id}` : '—'],
        ],
      };
    case 'incident-live':
      return {
        title: target.title,
        source: target.source,
        updated: target.updated,
        severity: target.severity,
        rows: target.rows,
      };
  }
}

/** Map a layer toggle to its live-data source(s) availability state. */
const LAYER_SOURCES: Record<string, string[]> = {
  weather: ['open-meteo'],
  rivers: ['open-meteo-flood'],
  floods: ['nasa-eonet', 'gdacs'],
  severe: ['nasa-eonet', 'gdacs'],
  hospitals: ['osm-nominatim'],
};

/** Toggles that reflect verified backend entities (not live sources). */
const ENTITY_LAYERS = new Set(['incidents', 'centres', 'warehouses', 'vehicles']);
/** Overlay toggles that are always controllable (road graph, routes). */
const ALWAYS_AVAILABLE = new Set(['roads', 'blocked', 'routes']);

function liveLayerUnavailable(
  layers: MapLiveLayers | undefined,
  key: string,
  directCount: number,
): boolean {
  if (ALWAYS_AVAILABLE.has(key)) return false;
  if (ENTITY_LAYERS.has(key)) return directCount === 0;
  const sources = LAYER_SOURCES[key];
  if (!sources) return false;
  if (directCount > 0) return false; // markers exist — source states may simply be stale
  const statuses =
    layers?.statuses.filter((status) => sources.includes(status.source)) ?? [];
  if (statuses.length === 0) return true;
  return statuses.some((status) => status.status === 'unavailable');
}

function PopupRows({ info }: { info: PopupInfo }) {
  return (
    <div className="gm-popup">
      <div className="gm-popup-head">
        <strong className="gm-popup-title">{info.title}</strong>
        {info.severity && (
          <span className={`gm-popup-sev sev-${info.severity}`}>{titleCase(info.severity)}</span>
        )}
      </div>
      <div className="gm-popup-rows">
        {info.rows
          .filter(([, value]) => value !== '—' && value !== '')
          .map(([key, value]) => (
            <div className="gm-popup-row" key={key}>
              <span className="k">{key}</span>
              <span className="v">{value}</span>
            </div>
          ))}
      </div>
      <div className="gm-popup-meta">
        <span>Data source: {info.source}</span>
        <span>Last updated: {info.updated ? formatDateTime(info.updated) : 'unavailable'}</span>
        {info.link && (
          <a className="gm-popup-link" href={info.link} target="_blank" rel="noreferrer">
            Event details ↗
          </a>
        )}
      </div>
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
  fitNonce,
}: {
  resetNonce: number;
  center: LatLng;
  zoom: number;
  fitKey: string | null;
  fitPath: LatLng[];
  fitNonce: number;
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

  // Operator-requested explicit refit (planner "Fit route" button).
  useEffect(() => {
    if (!map || fitNonce === 0) return;
    const path = latest.current.fitPath;
    if (path.length < 2) return;
    const bounds = new google.maps.LatLngBounds();
    path.forEach((p) => bounds.extend(p));
    map.fitBounds(bounds, 60);
  }, [map, fitNonce]);

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

function DisasterMapContent({
  overview,
  height,
  routeOverlays = [],
  onSelect,
  selected,
  fullscreen,
  mode = 'disaster',
  onModeChange,
  fitNonce = 0,
}: Props) {
  const [visible, setVisible] = useState<Record<string, boolean>>({
    warehouses: true,
    centres: true,
    vehicles: true,
    roads: MODE_PRESETS[mode].roads,
    blocked: true,
    incidents: true,
    routes: true,
    weather: true,
    floods: true,
    severe: true,
    hospitals: true,
    rivers: true,
  });
  // What-if Simulation: demo (seeded) data stays hidden until explicitly turned
  // on here. It is never shown in normal operational display.
  const [showSim, setShowSim] = useState(false);
  const [popup, setPopup] = useState<PopupTarget>(null);
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
      // Backend road geometry (real OSM road network) when provided.
      const geometry = overlay.geometry ?? null;
      const points: LatLng[] = [];
      const stops: { id: number; point: LatLng }[] = [];
      for (const nodeId of overlay.nodeIds) {
        const point = coordinates.get(nodeId);
        if (!point) continue;
        points.push(point);
        stops.push({ id: nodeId, point });
      }

      // Without node ids (real-network routes), stop markers come from the
      // geometry endpoints — the snapped origin/destination on the road.
      if (stops.length === 0 && geometry && geometry.length >= 2) {
        stops.push({ id: -1, point: geometry[0] });
        stops.push({ id: -2, point: geometry[geometry.length - 1] });
      }
      return { ...overlay, index, geometry, points, stops, key: routeCacheKey(geometry ?? points) };
    });
  }, [routeOverlays, coordinates]);

  // Geometry actually drawn per route: ONLY the backend road geometry. There
  // is no straight-line fallback — a route without geometry draws nothing.
  const drawn = routeLayers.map((layer) => ({
    layer,
    path: layer.geometry && layer.geometry.length >= 2 ? layer.geometry : null,
  }));

  const primary = drawn.find((d) => !d.layer.dashed && d.path);
  const fitKey = primary ? `${primary.layer.key}:g` : null;
  const missingGeometry = drawn.some((d) => d.path === null);

  // --- Live external-data layers (Open-Meteo / Flood API / EONET / GDACS / Nominatim) ---
  const liveLayers = overview?.live_layers;
  const feedStatus = useMemo(() => {
    const bySource = new globalThis.Map<string, LiveLayerStatus>();
    liveLayers?.statuses.forEach((status) => bySource.set(status.source, status));
    return bySource;
  }, [liveLayers]);

  // Demo (seeded) markers never render on the operational map: everything
  // flagged `is_demo` is dropped and its layer reports "no verified records".
  const genuineWarehouses = useMemo(
    () =>
      (overview?.warehouses ?? []).filter(
        (w) => w.is_demo === false && Number.isFinite(w.latitude) && Number.isFinite(w.longitude),
      ),
    [overview],
  );
  const genuineCentres = useMemo(
    () =>
      (overview?.relief_centres ?? []).filter(
        (c) => c.is_demo === false && Number.isFinite(c.latitude) && Number.isFinite(c.longitude),
      ),
    [overview],
  );
  const genuineVehicles = useMemo(
    () =>
      (overview?.vehicles ?? []).filter(
        (v) => v.is_demo === false && hasOrderedCoords(v.current_latitude, v.current_longitude),
      ),
    [overview],
  );
  // Incident markers: genuine, non-weather records. Weather-API monitor
  // incidents are represented by the dedicated live layers instead (Open-Meteo
  // weather / river gauges / EONET events), which avoids duplicated markers.
  const genuineIncidents = useMemo(
    () =>
      (overview?.incidents ?? []).filter(
        (i) => i.is_demo === false && i.source !== 'weather_api',
      ),
    [overview],
  );

  // What-if Simulation lists: seeded demo (unverified) records. These are ONLY
  // rendered while the clearly-labelled simulation toggle is on, and every one
  // is drawn with a dashed outline and a "SIMULATED" marker title.
  const demoWarehouses = useMemo(
    () =>
      (overview?.warehouses ?? []).filter(
        (w) => w.is_demo === true && Number.isFinite(w.latitude) && Number.isFinite(w.longitude),
      ),
    [overview],
  );
  const demoCentres = useMemo(
    () =>
      (overview?.relief_centres ?? []).filter(
        (c) => c.is_demo === true && Number.isFinite(c.latitude) && Number.isFinite(c.longitude),
      ),
    [overview],
  );
  const demoVehicles = useMemo(
    () =>
      (overview?.vehicles ?? []).filter(
        (v) => v.is_demo === true && hasOrderedCoords(v.current_latitude, v.current_longitude),
      ),
    [overview],
  );
  const demoIncidents = useMemo(
    () =>
      (overview?.incidents ?? []).filter(
        (i) => i.is_demo === true && i.source !== 'weather_api',
      ),
    [overview],
  );

  // What the marker layers actually render: verified records always; demo
  // records only while the What-if Simulation toggle is explicitly enabled.
  const displayedWarehouses = showSim ? [...genuineWarehouses, ...demoWarehouses] : genuineWarehouses;
  const displayedCentres = showSim ? [...genuineCentres, ...demoCentres] : genuineCentres;
  const displayedVehicles = showSim ? [...genuineVehicles, ...demoVehicles] : genuineVehicles;
  const displayedIncidents = showSim ? [...genuineIncidents, ...demoIncidents] : genuineIncidents;

  if (!overview) return null;
  if (!apiKey) {
    return <div className="error-state"><div className="error-message">Google Maps key missing. Set VITE_GOOGLE_MAPS_API_KEY in frontend/.env.local and restart Vite.</div></div>;
  }
  if (loadFailed) {
    return <div className="error-state"><div className="error-message">Google Maps failed to load. Check VITE_GOOGLE_MAPS_API_KEY, API restrictions and your network.</div></div>;
  }

  const center: LatLng = { lat: overview.center.latitude, lng: overview.center.longitude };

  const isMarkerSelected = (kind: NonNullable<EntitySelection>['kind'], id: number) =>
    selected?.kind === kind && selected.id === id;

  const toggle = (key: string) => setVisible((current) => ({ ...current, [key]: !current[key] }));

  /** Switching modes also re-applies that mode's default layer visibility preset. */
  const changeMode = (next: MapMode) => {
    setVisible((current) => ({ ...current, roads: MODE_PRESETS[next].roads }));
    onModeChange?.(next);
  };

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
            fitNonce={fitNonce}
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

          {/* Route overlays: the backend real-road geometry IS the drawn line */}
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

          {/* Warehouses — verified records; seeded demo only in What-if Simulation */}
          {visible.warehouses &&
            displayedWarehouses.map((warehouse) => {
              const isSim = warehouse.is_demo === true;
              return (
                <AdvancedMarker
                  key={`wh-${warehouse.id}`}
                  position={{ lat: warehouse.latitude, lng: warehouse.longitude }}
                  title={`${warehouse.name} — ${warehouse.location_name}${isSim ? ' — SIMULATED (What-if demo)' : ''}`}
                  anchorTop="-50%"
                  clickable
                  onClick={() => onSelect?.({ kind: 'warehouse', id: warehouse.id })}
                >
                  <EntityPin color="#21c5c2" glyph={PATH_WAREHOUSE} size={20} sim={isSim} />
                </AdvancedMarker>
              );
            })}

          {/* Relief centres — verified records; seeded demo only in What-if Simulation */}
          {visible.centres &&
            displayedCentres.map((centre) => {
              const isSelected = isMarkerSelected('centre', centre.id);
              const isSim = centre.is_demo === true;
              return (
                <AdvancedMarker
                  key={`rc-${centre.id}`}
                  position={{ lat: centre.latitude, lng: centre.longitude }}
                  title={`${centre.name} — ${titleCase(centre.priority)} priority${isSim ? ' — SIMULATED (What-if demo)' : ''}`}
                  anchorTop="-50%"
                  clickable
                  onClick={() => onSelect?.({ kind: 'centre', id: centre.id })}
                >
                  <EntityPin
                    color={PRIORITY_COLORS[centre.priority]}
                    glyph={PATH_PLUS}
                    size={isSelected ? 24 : 20}
                    ring={isSelected}
                    sim={isSim}
                  />
                </AdvancedMarker>
              );
            })}

          {/* Vehicles (verified positions; seeded demo only in What-if Simulation) */}
          {visible.vehicles &&
            displayedVehicles.map((vehicle) => (
              <AdvancedMarker
                key={`veh-${vehicle.id}`}
                position={{ lat: vehicle.current_latitude!, lng: vehicle.current_longitude! }}
                title={`${vehicle.vehicle_code} — ${titleCase(vehicle.status)}${vehicle.is_demo === true ? ' — SIMULATED (What-if demo)' : ''}`}
                anchorTop="-50%"
                clickable
                onClick={() => onSelect?.({ kind: 'vehicle', id: vehicle.id })}
              >
                <EntityPin color={VEHICLE_COLORS[vehicle.status]} glyph={PATH_TRUCK} size={18} sim={vehicle.is_demo === true} />
              </AdvancedMarker>
            ))}

          {/* Verified incidents — genuine operator/citizen/simulation records only; seeded demo only in What-if Simulation */}
          {visible.incidents &&
            displayedIncidents.map((incident) => {
              const isSim = incident.is_demo === true;
              return (
                <AdvancedMarker
                  key={`inc-${incident.id}`}
                  position={{ lat: incident.latitude, lng: incident.longitude }}
                  title={`${incident.title} — ${titleCase(incident.severity)}${isSim ? ' — SIMULATED (What-if demo)' : ''}`}
                  anchorTop="-50%"
                  clickable
                  onClick={() => setPopup({ kind: 'incident-live', position: { lat: incident.latitude, lng: incident.longitude }, title: incident.title, rows: [['Type', titleCase(incident.incident_type)], ['Status', titleCase(incident.status)], ['Source', incident.source ? titleCase(incident.source) : '—'], ...isSim ? [['Simulation', 'SIMULATED (What-if demo)'] as [string, string]] : []], severity: incident.severity, source: 'ReliefMesh incident register', updated: incident.updated_at ?? null })}
                >
                  <EntityPin color={SEVERE_RED} glyph={PATH_ALERT} size={20} sim={isSim} />
                </AdvancedMarker>
              );
            })}

          {/* ---------------------------------------------------------- Live external data layers */}
          {/* Weather: Open-Meteo current conditions per delta station (cyan) */}
          {visible.weather &&
            liveLayers?.weather_stations
              .filter((station) => hasOrderedCoords(station.latitude, station.longitude))
              .map((station) => (
                <AdvancedMarker
                  key={`weather-${station.name}`}
                  position={{ lat: station.latitude, lng: station.longitude }}
                  title={`Weather — ${station.name} (${titleCase(station.severity ?? 'unknown')} risk)`}
                  anchorTop="-50%"
                  clickable
                  onClick={() =>
                    setPopup({ kind: 'weather', station, position: { lat: station.latitude, lng: station.longitude } })
                  }
                >
                  <EntityPin color={WEATHER_CYAN} glyph={PATH_CLOUD} size={22} />
                </AdvancedMarker>
              ))}

          {/* River monitoring: Open-Meteo Flood API gauges (teal) */}
          {visible.rivers &&
            liveLayers?.river_gauges
              .filter((gauge) => hasOrderedCoords(gauge.latitude, gauge.longitude))
              .map((gauge) => (
                <AdvancedMarker
                  key={`river-${gauge.name}`}
                  position={{ lat: gauge.latitude, lng: gauge.longitude }}
                  title={`River gauge — ${gauge.name} (${fmt(gauge.river_discharge_m3s, 'm³/s')})`}
                  anchorTop="-50%"
                  clickable
                  onClick={() => setPopup({ kind: 'river', gauge, position: { lat: gauge.latitude, lng: gauge.longitude } })}
                >
                  <EntityPin color={RIVER_TEAL} glyph={PATH_WATER} size={22} />
                </AdvancedMarker>
              ))}

          {/* Hospitals: OSM Nominatim real facilities (blue) */}
          {visible.hospitals &&
            liveLayers?.facilities
              .filter((facility) => hasOrderedCoords(facility.latitude, facility.longitude))
              .map((facility, index) => (
                <AdvancedMarker
                  key={`facility-${facility.osm_id ?? `${facility.town}-${index}`}`}
                  position={{ lat: facility.latitude, lng: facility.longitude }}
                  title={`Hospital — ${facility.name}`}
                  anchorTop="-50%"
                  clickable
                  onClick={() => setPopup({ kind: 'facility', facility, position: { lat: facility.latitude, lng: facility.longitude } })}
                >
                  <EntityPin color={FACILITY_BLUE} glyph={PATH_PLUS} size={18} />
                </AdvancedMarker>
              ))}

          {/* Disaster events: NASA EONET + GDACS — flood risk (orange), severe (red) */}
          {visible.floods &&
            (liveLayers?.disaster_events ?? [])
              .filter((event) => isFloodEvent(event) && hasOrderedCoords(event.latitude, event.longitude))
              .map((event, index) => (
                <AdvancedMarker
                  key={`flood-${event.external_id ?? index}`}
                  position={{ lat: event.latitude, lng: event.longitude }}
                  title={`Flood risk — ${event.title} (${event.source})`}
                  anchorTop="-50%"
                  clickable
                  onClick={() => setPopup({ kind: 'event', event, position: { lat: event.latitude, lng: event.longitude } })}
                >
                  <EntityPin color={FLOOD_ORANGE} glyph={PATH_WATER} size={22} />
                </AdvancedMarker>
              ))}
          {visible.severe &&
            (liveLayers?.disaster_events ?? [])
              .filter((event) => isSevereEvent(event) && hasOrderedCoords(event.latitude, event.longitude))
              .map((event, index) => (
                <AdvancedMarker
                  key={`severe-${event.external_id ?? index}`}
                  position={{ lat: event.latitude, lng: event.longitude }}
                  title={`Severe event — ${event.title} (${event.source})`}
                  anchorTop="-50%"
                  clickable
                  onClick={() => setPopup({ kind: 'event', event, position: { lat: event.latitude, lng: event.longitude } })}
                >
                  <EntityPin color={SEVERE_RED} glyph={PATH_ALERT} size={22} />
                </AdvancedMarker>
              ))}

          {/* Marker popup: details, severity, data source and freshness */}
          {popup && (
            <InfoWindow
              position={popup.position}
              onCloseClick={() => setPopup(null)}
              pixelOffset={[0, -22]}
            >
              {popup.kind === 'incident-live' ? (
                <PopupRows
                  info={{
                    title: popup.title,
                    source: popup.source,
                    updated: popup.updated,
                    severity: popup.severity,
                    rows: popup.rows,
                  }}
                />
              ) : (
                <PopupRows info={buildPopup(popup)} />
              )}
            </InfoWindow>
          )}

          {/* Active route markers: start pin, numbered stops, end circle */}
          {visible.routes &&
            drawn.flatMap(({ layer }) => {
              const stops = layer.stops;
              if (layer.dashed || !stops || stops.length < 2) return [];
              const first = stops[0];
              const last = stops[stops.length - 1];
              const middle = stops.slice(1, -1);
              const name = (id: number) =>
                nodeNames.get(id) ?? (id === -1 ? 'Route start' : id === -2 ? 'Route end' : `Node ${id}`);
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
            ['weather', 'Weather (Open-Meteo)'],
            ['floods', 'Flood risk (EONET / GDACS)'],
            ['severe', 'Severe events / alerts'],
            ['hospitals', 'Hospitals (OSM)'],
            ['rivers', 'River monitoring'],
            ['incidents', 'Incidents (verified)'],
            ['centres', 'Relief centres'],
            ['warehouses', 'Warehouses'],
            ['vehicles', 'Vehicles'],
            ['roads', 'Road network'],
            ['blocked', 'Blocked roads'],
            ['routes', 'Active routes'],
          ] as const
        ).map(([key, label]) => {
          const counts: Record<string, number> = {
            weather: liveLayers?.weather_stations.length ?? 0,
            rivers: liveLayers?.river_gauges.length ?? 0,
            floods:
              (liveLayers?.disaster_events ?? []).filter(
                (event) => isFloodEvent(event) && hasOrderedCoords(event.latitude, event.longitude),
              ).length,
            severe:
              (liveLayers?.disaster_events ?? []).filter(
                (event) => isSevereEvent(event) && hasOrderedCoords(event.latitude, event.longitude),
              ).length + displayedIncidents.length,
            hospitals: liveLayers?.facilities.length ?? 0,
            incidents: displayedIncidents.length,
            centres: displayedCentres.length,
            warehouses: displayedWarehouses.length,
            vehicles: displayedVehicles.length,
          };
          const directCount = counts[key] ?? 0;
          const unavailable = liveLayerUnavailable(liveLayers, key, directCount);
          return (
            <label key={key} className={`layer-toggle${unavailable ? ' is-unavailable' : ''}`}>
              <input
                type="checkbox"
                checked={visible[key]}
                onChange={() => toggle(key)}
                disabled={unavailable}
              />
              {label}
              {unavailable && <span className="layer-note">no verified data</span>}
            </label>
          );
        })}
      </div>

      {/* Mode switcher + clearly-labelled What-if Simulation toggle */}
      <div className="map-overlay map-modes">
        {onModeChange ? (
          (Object.keys(MODE_LABELS) as MapMode[]).map((key) => (
            <button
              key={key}
              className={`map-mode-btn${key === mode ? ' is-active' : ''}`}
              onClick={() => changeMode(key)}
            >
              {MODE_LABELS[key]}
            </button>
          ))
        ) : (
          <span className="map-mode-fixed">{MODE_LABELS[mode]}</span>
        )}
        <label
          className="map-sim-toggle"
          title="Show seeded demo records (warehouses, relief centres, vehicles, incidents) marked SIMULATED. Hidden by default in operational display."
        >
          <input
            type="checkbox"
            checked={showSim}
            onChange={(event) => setShowSim(event.target.checked)}
          />
          What-if Simulation
        </label>
      </div>

      {/* Key / API problems surface here instead of a silent grey map */}
      {authFailed && (
        <div className="map-overlay map-note" role="alert">
          Google rejected the Maps key (invalid, restricted, or demo quota reached).
        </div>
      )}
      {feedStatus.size > 0 && (
        <div className="map-overlay map-feed-note">
          {[...feedStatus.values()].map((status) => (
            <span
              key={status.source}
              className={`feed-chip feed-${status.status}`}
              title={`Last updated: ${status.last_updated ? formatDateTime(status.last_updated) : 'never'}`}
            >
              {status.source}: {status.status}
            </span>
          ))}
        </div>
      )}
      {!authFailed && visible.routes && routeLayers.length > 0 && (
        <div className="map-overlay map-note">
          {primary?.path
            ? primary.layer.source === 'google-directions'
              ? primary.layer.safe === false
                ? 'NO_SAFE_ROUTE_AVAILABLE — this Google road route conflicts with a verified blocked road (drawn red).'
                : 'Route follows Google road directions (Routes library). Verified blocked roads and live disaster layers re-checked for this geometry.'
              : 'Route follows actual OpenStreetMap roads (backend routing geometry).'
            : missingGeometry
              ? 'Route line unavailable: no road geometry from the routing backend (no straight-line fallback drawn).'
              : null}
        </div>
      )}
      {!authFailed && mode === 'navigation' && routeLayers.length === 0 && (
        <div className="map-overlay map-note">
          No route drawn yet — select an origin and destination in the Route Planner and press Calculate.
        </div>
      )}

      {/* Legend */}
      <div className="map-overlay map-legend">
        <h4>Legend</h4>
        <div className="legend-row">
          <span className="legend-dot" style={{ background: WEATHER_CYAN }} /> Weather station (Open-Meteo)
        </div>
        <div className="legend-row">
          <span className="legend-dot" style={{ background: RIVER_TEAL }} /> River gauge — discharge (Open-Meteo Flood API)
        </div>
        <div className="legend-row">
          <span className="legend-dot" style={{ background: FLOOD_ORANGE }} /> Flood risk event (EONET / GDACS)
        </div>
        <div className="legend-row">
          <span className="legend-dot" style={{ background: SEVERE_RED }} /> Severe event / alert (EONET / GDACS)
        </div>
        <div className="legend-row">
          <span className="legend-dot" style={{ background: FACILITY_BLUE }} /> Hospital / medical facility (OSM Nominatim)
        </div>
        <div className="legend-row muted">
          {showSim
            ? 'What-if Simulation active — dashed markers are unverified demo records (SIMULATED).'
            : 'Verified incident / entity markers only — seeded demo data hidden'}
        </div>
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
          <span className="legend-swatch" style={{ background: '#ffb020', height: 4 }} /> Planned route — caution (live hazards nearby)
        </div>
        <div className="legend-row">
          <span className="legend-swatch" style={{ background: SEVERE_RED, height: 4 }} /> Planned route — conflicts a verified closure
        </div>
        <div className="legend-row">
          <span className="legend-dot" style={{ background: START_ORANGE }} /> Route start / end
        </div>
        <div className="legend-row">
          <span className="legend-dot" style={{ background: STOP_TEAL }} /> Route stop
        </div>
      </div>
    </div>
  );
}
