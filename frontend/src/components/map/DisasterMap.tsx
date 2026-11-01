import { useEffect, useMemo, useState, type ReactNode } from 'react';
import {
  CircleMarker,
  MapContainer,
  Popup,
  Polyline,
  TileLayer,
  useMap,
} from 'react-leaflet';
import type { LatLngBoundsExpression, LatLngExpression } from 'leaflet';
import 'leaflet/dist/leaflet.css';
import type {
  MapDisasterEvent,
  MapOverviewResponse,
  MapRiverGauge,
  MapWeatherStation,
  Priority,
  Severity,
  VehicleStatus,
} from '../../types';
import type { LatLng } from '../../api/googleRoutes';

export type EntitySelection =
  | { kind: 'warehouse'; id: number }
  | { kind: 'centre'; id: number }
  | { kind: 'vehicle'; id: number }
  | { kind: 'incident'; id: number }
  | { kind: 'segment'; id: number }
  | null;

export interface RouteOverlay {
  nodeIds: number[];
  label: string;
  color?: string;
  dashed?: boolean;
  geometry?: LatLng[];
  source?: 'osm-network' | 'google-directions';
  safe?: boolean | null;
  plannedAt?: string | null;
}

export type MapMode = 'disaster' | 'navigation' | 'logistics';

const COLORS = {
  warehouse: '#21c5c2',
  centre: '#319aff',
  vehicle: '#21b989',
  incident: '#f15b5b',
  road: '#6db3f2',
  blocked: '#f15b5b',
  weather: '#21c5c2',
  river: '#1fa37a',
  flood: '#ff963d',
  facility: '#319aff',
  route: '#ff8a1f',
};

interface Props {
  overview: MapOverviewResponse | null;
  height?: number;
  routeOverlays?: RouteOverlay[];
  onSelect?: (selection: NonNullable<EntitySelection>) => void;
  selected?: EntitySelection;
  fullscreen?: boolean;
  mode?: MapMode;
  onModeChange?: (mode: MapMode) => void;
  fitNonce?: number;
}

export type PopupTarget =
  | { kind: 'weather'; station: MapWeatherStation; position: LatLng }
  | { kind: 'river'; gauge: MapRiverGauge; position: LatLng }
  | { kind: 'event'; event: MapDisasterEvent; position: LatLng }
  | { kind: 'facility'; facility: { name: string }; position: LatLng }
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

function FitMap({
  overview,
  fitNonce,
  routeOverlays,
}: {
  overview: MapOverviewResponse;
  fitNonce: number;
  routeOverlays: RouteOverlay[];
}) {
  const map = useMap();
  useEffect(() => {
    if (!fitNonce) return;
    const route = routeOverlays.find((item) => item.geometry?.length);
    if (route?.geometry) {
      map.fitBounds(route.geometry.map(({ lat, lng }) => [lat, lng]) as LatLngBoundsExpression, {
        padding: [30, 30],
      });
    } else {
      map.setView([overview.center.latitude, overview.center.longitude], overview.center.zoom);
    }
  }, [fitNonce, map, overview, routeOverlays]);
  return null;
}

function Marker({
  position,
  color,
  title,
  selected,
  onClick,
  children,
}: {
  position: LatLngExpression;
  color: string;
  title: string;
  selected?: boolean;
  onClick?: () => void;
  children?: ReactNode;
}) {
  return (
    <CircleMarker
      center={position}
      radius={selected ? 10 : 7}
      pathOptions={{ color: '#071321', weight: 2, fillColor: color, fillOpacity: 0.9 }}
      eventHandlers={onClick ? { click: onClick } : undefined}
    >
      <Popup>
        <strong>{title}</strong>
        {children}
      </Popup>
    </CircleMarker>
  );
}

export function DisasterMap({
  overview,
  height = 620,
  routeOverlays = [],
  onSelect,
  selected,
  mode = 'disaster',
  onModeChange,
  fitNonce = 0,
}: Props) {
  const [visible, setVisible] = useState({
    roads: mode === 'logistics',
    blocked: true,
    incidents: true,
    centres: true,
    warehouses: true,
    vehicles: true,
    weather: true,
    rivers: true,
    floods: true,
    facilities: true,
    routes: true,
  });

  useEffect(() => {
    setVisible((current) => ({ ...current, roads: mode === 'logistics' }));
  }, [mode]);

  const nodes = useMemo(
    () => new Map(overview?.road_nodes.map((node) => [node.id, [node.latitude, node.longitude] as LatLngExpression])),
    [overview],
  );
  if (!overview) return null;

  const live = overview.live_layers;
  const toggle = (key: keyof typeof visible) => setVisible((current) => ({ ...current, [key]: !current[key] }));
  const point = (lat: number, lng: number): LatLngExpression => [lat, lng];
  const entityClick = (selection: NonNullable<EntitySelection>) => onSelect?.(selection);
  const roads = overview.road_segments
    .map((segment) => {
      const from = nodes.get(segment.from_node_id);
      const to = nodes.get(segment.to_node_id);
      return from && to ? { segment, positions: [from, to] as LatLngExpression[] } : null;
    })
    .filter((item): item is { segment: (typeof overview.road_segments)[number]; positions: LatLngExpression[] } => item !== null);

  return (
    <div className={mode === 'navigation' ? 'map-canvas' : 'map-container'} style={{ height }}>
      <MapContainer
        center={[overview.center.latitude, overview.center.longitude]}
        zoom={overview.center.zoom}
        style={{ height: '100%', width: '100%' }}
        scrollWheelZoom
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <FitMap overview={overview} fitNonce={fitNonce} routeOverlays={routeOverlays} />

        {visible.roads &&
          roads.filter(({ segment }) => visible.blocked || !segment.is_blocked).map(({ segment, positions }) => (
            <Polyline
              key={`road-${segment.id}`}
              positions={positions}
              pathOptions={{ color: segment.is_blocked ? COLORS.blocked : COLORS.road, weight: segment.is_blocked ? 4 : 2, opacity: 0.7 }}
              eventHandlers={{ click: () => entityClick({ kind: 'segment', id: segment.id }) }}
            />
          ))}

        {visible.routes &&
          routeOverlays.map((route, index) =>
            route.geometry?.length ? (
              <Polyline
                key={`route-${index}`}
                positions={route.geometry.map(({ lat, lng }) => [lat, lng])}
                pathOptions={{ color: route.color ?? COLORS.route, weight: 5, dashArray: route.dashed ? '8 8' : undefined }}
              >
                <Popup><strong>{route.label}</strong></Popup>
              </Polyline>
            ) : null,
          )}

        {visible.warehouses &&
          overview.warehouses.filter((item) => Number.isFinite(item.latitude) && Number.isFinite(item.longitude)).map((item) => (
            <Marker key={`warehouse-${item.id}`} position={point(item.latitude, item.longitude)} color={COLORS.warehouse} title={item.name} selected={selected?.kind === 'warehouse' && selected.id === item.id} onClick={() => entityClick({ kind: 'warehouse', id: item.id })}>
              <div>{item.location_name}</div>
            </Marker>
          ))}
        {visible.centres &&
          overview.relief_centres.map((item) => (
            <Marker key={`centre-${item.id}`} position={point(item.latitude, item.longitude)} color={priorityColor(item.priority)} title={item.name} selected={selected?.kind === 'centre' && selected.id === item.id} onClick={() => entityClick({ kind: 'centre', id: item.id })}>
              <div>{item.district} · {item.priority}</div>
            </Marker>
          ))}
        {visible.vehicles &&
          overview.vehicles.filter((item) => item.current_latitude !== null && item.current_longitude !== null).map((item) => (
            <Marker key={`vehicle-${item.id}`} position={point(item.current_latitude!, item.current_longitude!)} color={vehicleColor(item.status)} title={item.vehicle_code} />
          ))}
        {visible.incidents &&
          overview.incidents.map((item) => (
            <Marker key={`incident-${item.id}`} position={point(item.latitude, item.longitude)} color={COLORS.incident} title={item.title} selected={selected?.kind === 'incident' && selected.id === item.id} onClick={() => entityClick({ kind: 'incident', id: item.id })}>
              <div>{item.location_name} · {item.severity}</div>
            </Marker>
          ))}
        {visible.weather &&
          live?.weather_stations.map((item) => (
            <Marker key={`weather-${item.name}`} position={point(item.latitude, item.longitude)} color={COLORS.weather} title={item.name}>
              <div>{item.temperature_c ?? '—'}°C · {item.assessment ?? 'Weather monitor'}</div>
            </Marker>
          ))}
        {visible.rivers &&
          live?.river_gauges.map((item) => (
            <Marker key={`river-${item.name}`} position={point(item.latitude, item.longitude)} color={COLORS.river} title={item.name}>
              <div>{item.river ?? 'River gauge'} · {item.river_discharge_m3s ?? '—'} m³/s</div>
            </Marker>
          ))}
        {visible.floods &&
          live?.disaster_events.map((item) => (
            <Marker key={`event-${item.external_id ?? item.title}`} position={point(item.latitude, item.longitude)} color={item.severity === 'critical' || item.severity === 'high' ? COLORS.incident : COLORS.flood} title={item.title}>
              <div>{item.category ?? 'Disaster event'} · {item.source}</div>
            </Marker>
          ))}
        {visible.facilities &&
          live?.facilities.map((item) => (
            <Marker key={`facility-${item.osm_id ?? item.name}`} position={point(item.latitude, item.longitude)} color={COLORS.facility} title={item.name}>
              <div>{item.category}</div>
            </Marker>
          ))}
      </MapContainer>
      <div className="layer-controls">
        {(['disaster', 'navigation', 'logistics'] as MapMode[]).map((value) => (
          <button key={value} type="button" className={`map-mode-btn ${mode === value ? 'is-active' : ''}`} onClick={() => onModeChange?.(value)}>
            {value}
          </button>
        ))}
        {Object.keys(visible).map((key) => (
          <label key={key} className="layer-toggle">
            <input
              type="checkbox"
              checked={visible[key as keyof typeof visible]}
              onChange={() => toggle(key as keyof typeof visible)}
            />
            {key}
          </label>
        ))}
      </div>
      <div className="map-overlay map-note">OpenStreetMap data · no map key required</div>
      <div className="map-overlay map-legend">
        <h4>Map legend</h4>
        <LegendRow color={COLORS.incident} label="Incidents / severe events" />
        <LegendRow color={COLORS.centre} label="Relief centres" />
        <LegendRow color={COLORS.warehouse} label="Warehouses" />
        <LegendRow color={COLORS.vehicle} label="Vehicles" />
        <LegendRow color={COLORS.weather} label="Weather stations" />
        <LegendRow color={COLORS.river} label="River gauges" />
        <LegendRow color={COLORS.facility} label="Hospitals / facilities" />
        <LegendRow color={COLORS.flood} label="Flood events" />
        <div className="legend-row">
          <span className="legend-swatch" style={{ background: COLORS.road }} />
          <span>Road network</span>
        </div>
        <div className="legend-row">
          <span className="legend-swatch" style={{ background: COLORS.blocked, height: 4 }} />
          <span>Blocked road</span>
        </div>
        <div className="legend-row">
          <span className="legend-swatch" style={{ background: COLORS.route, height: 4 }} />
          <span>Planned route</span>
        </div>
      </div>
    </div>
  );
}

function LegendRow({ color, label }: { color: string; label: string }) {
  return (
    <div className="legend-row">
      <span className="legend-dot" style={{ background: color }} />
      <span>{label}</span>
    </div>
  );
}

function priorityColor(priority: Priority): string {
  return priority === 'critical' ? COLORS.incident : priority === 'high' ? COLORS.flood : COLORS.centre;
}

function vehicleColor(status: VehicleStatus): string {
  return status === 'delayed' ? COLORS.flood : status === 'maintenance' ? COLORS.incident : COLORS.vehicle;
}
