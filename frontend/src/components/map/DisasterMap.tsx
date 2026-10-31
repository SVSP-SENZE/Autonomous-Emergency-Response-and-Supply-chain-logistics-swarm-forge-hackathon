import { useEffect, useMemo, useState } from 'react';
import L from 'leaflet';
import {
  MapContainer,
  TileLayer,
  Marker,
  Popup,
  Polyline,
  LayerGroup,
  useMap,
} from 'react-leaflet';
import { Expand, Minimize, Crosshair } from 'lucide-react';
import type {
  MapOverviewResponse,
  Priority,
  VehicleStatus,
} from '../../types';
import { titleCase } from '../../utils/format';

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
  color?: string;
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

function pinIcon(color: string, svg: string, size = 20, pulse = false) {
  return L.divIcon({
    className: 'rm-marker',
    html: `<div class="marker-pin ${pulse ? 'pulse' : ''}" style="background:${color};position:relative;color:${color}">${svg}</div>`,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
    popupAnchor: [0, -size / 2],
  });
}

const SVG_WAREHOUSE =
  '<svg viewBox="0 0 24 24" fill="#071321"><path d="M2 20V8l10-5 10 5v12h-6v-7H8v7H2z"/></svg>';
const SVG_PLUS =
  '<svg viewBox="0 0 24 24" fill="#071321"><path d="M10 3h4v7h7v4h-7v7h-4v-7H3v-4h7V3z"/></svg>';
const SVG_TRUCK =
  '<svg viewBox="0 0 24 24" fill="#071321"><path d="M1 5h13v10H1V5zm13 4h5l3 4v2h-8V9zM4 16a1.8 1.8 0 104 0 1.8 1.8 0 10-4 0zM16 16a1.8 1.8 0 104 0 1.8 1.8 0 10-4 0z"/></svg>';
const SVG_ALERT =
  '<svg viewBox="0 0 24 24" fill="#071321"><path d="M12 2 1 21h22L12 2zm1 14h-2v2h2v-2zm0-7h-2v5h2V9z"/></svg>';

function MapController({ center }: { center: [number, number] | null }) {
  const map = useMap();
  useEffect(() => {
    if (center) map.setView(center, map.getZoom() || 9);
  }, [center, map]);
  return null;
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
  });
  const [isFullscreen, setIsFullscreen] = useState(false);
  const fullscreenActive = fullscreen || isFullscreen;
  const [recenter, setRecenter] = useState<[number, number] | null>(null);

  const coordinates = useMemo(() => {
    const byId = new Map<number, [number, number]>();
    overview?.road_nodes.forEach((node) => byId.set(node.id, [node.latitude, node.longitude]));
    return byId;
  }, [overview]);

  const routeLayers = useMemo(() => {
    return routeOverlays.map((overlay, index) => {
      const latlngs: [number, number][] = [];
      for (const nodeId of overlay.nodeIds) {
        const coord = coordinates.get(nodeId);
        if (coord) latlngs.push(coord);
      }
      return { ...overlay, index, latlngs };
    });
  }, [routeOverlays, coordinates]);

  if (!overview) return null;

  const center: [number, number] = [overview.center.latitude, overview.center.longitude];
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
      <MapContainer
        center={center}
        zoom={overview.center.zoom}
        scrollWheelZoom
        style={{ height: '100%', width: '100%' }}
        attributionControl
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
          maxZoom={18}
        />
        <MapController center={recenter} />

        {/* Road network */}
        {visible.roads && (
          <LayerGroup>
            {overview.road_segments
              .filter((segment) => !segment.is_blocked)
              .map((segment) => {
                const from = coordinates.get(segment.from_node_id);
                const to = coordinates.get(segment.to_node_id);
                if (!from || !to) return null;
                const risky = segment.risk_factor >= 0.6;
                return (
                  <Polyline
                    key={`seg-${segment.id}`}
                    positions={[from, to]}
                    pathOptions={{
                      color: risky ? '#ff963d' : '#3d6a95',
                      weight: risky ? 3.5 : 2,
                      opacity: risky ? 0.85 : 0.55,
                    }}
                    eventHandlers={{
                      click: () =>
                        onSelect?.({ kind: 'segment', id: segment.id }),
                    }}
                  >
                    <Popup>
                      <strong>{`Segment #${segment.id}: ${segment.from_node_name} → ${segment.to_node_name}`}</strong>
                      <br />
                      {segment.distance_km} km · {segment.estimated_travel_time_minutes} min · risk{' '}
                      {segment.risk_factor.toFixed(2)}
                    </Popup>
                  </Polyline>
                );
              })}
          </LayerGroup>
        )}

        {/* Blocked roads */}
        {visible.blocked && (
          <LayerGroup>
            {overview.road_segments
              .filter((segment) => segment.is_blocked)
              .map((segment) => {
                const from = coordinates.get(segment.from_node_id);
                const to = coordinates.get(segment.to_node_id);
                if (!from || !to) return null;
                return (
                  <Polyline
                    key={`blocked-${segment.id}`}
                    positions={[from, to]}
                    pathOptions={{
                      color: '#f15b5b',
                      weight: 4.5,
                      opacity: 0.95,
                      dashArray: '7 7',
                    }}
                    eventHandlers={{ click: () => onSelect?.({ kind: 'segment', id: segment.id }) }}
                  >
                    <Popup>
                      <strong style={{ color: '#f15b5b' }}>BLOCKED</strong>
                      <br />
                      {`#${segment.id}: ${segment.from_node_name} → ${segment.to_node_name}`}
                      <br />
                      {segment.blockage_reason ? `Reason: ${segment.blockage_reason}` : null}
                    </Popup>
                  </Polyline>
                );
              })}
          </LayerGroup>
        )}

        {/* Route overlays (backend-computed routes only) */}
        {visible.routes && (
          <LayerGroup>
            {routeLayers.map((route) =>
              route.latlngs.length >= 2 ? (
                <Polyline
                  key={`route-${route.index}`}
                  positions={route.latlngs}
                  pathOptions={{
                    color: route.color ?? '#35e0ff',
                    weight: 5,
                    opacity: 0.92,
                    dashArray: route.dashed ? '4 8' : undefined,
                  }}
                >
                  <Popup>
                    <strong>{route.label}</strong>
                  </Popup>
                </Polyline>
              ) : null,
            )}
          </LayerGroup>
        )}

        {/* Warehouses */}
        {visible.warehouses && (
          <LayerGroup>
            {overview.warehouses.map((warehouse) => (
              <Marker
                key={`wh-${warehouse.id}`}
                position={[warehouse.latitude, warehouse.longitude]}
                icon={pinIcon('#21c5c2', SVG_WAREHOUSE)}
                eventHandlers={{ click: () => onSelect?.({ kind: 'warehouse', id: warehouse.id }) }}
              >
                <Popup>
                  <strong>{warehouse.name}</strong>
                  <br />
                  {warehouse.location_name} · {titleCase(warehouse.operational_status)}
                  <br />
                  <span className="muted">Node-id link: entity {warehouse.id}</span>
                </Popup>
              </Marker>
            ))}
          </LayerGroup>
        )}

        {/* Relief centres */}
        {visible.centres && (
          <LayerGroup>
            {overview.relief_centres.map((centre) => {
              const color = PRIORITY_COLORS[centre.priority];
              const isSelected = isMarkerSelected('centre', centre.id);
              return (
                <Marker
                  key={`rc-${centre.id}`}
                  position={[centre.latitude, centre.longitude]}
                  icon={pinIcon(color, SVG_PLUS, isSelected ? 24 : 20, centre.priority === 'critical' || isSelected)}
                  eventHandlers={{ click: () => onSelect?.({ kind: 'centre', id: centre.id }) }}
                >
                  <Popup>
                    <strong>{centre.name}</strong>
                    <br />
                    {centre.district} · {titleCase(centre.operational_status)}
                    <br />
                    Priority: {titleCase(centre.priority)} · {centre.affected_population.toLocaleString()} affected
                    <br />
                    {centre.water_shortage ? <span style={{ color: '#ff963d' }}>Water shortage reported</span> : 'No water shortage flag'}
                  </Popup>
                </Marker>
              );
            })}
          </LayerGroup>
        )}

        {/* Vehicles (backend positions only — no invented coordinates) */}
        {visible.vehicles && (
          <LayerGroup>
            {overview.vehicles
              .filter((vehicle) => hasVehicleCoords(vehicle.current_latitude, vehicle.current_longitude))
              .map((vehicle) => (
                <Marker
                  key={`veh-${vehicle.id}`}
                  position={[vehicle.current_latitude!, vehicle.current_longitude!]}
                  icon={pinIcon(VEHICLE_COLORS[vehicle.status], SVG_TRUCK, 16)}
                  eventHandlers={{ click: () => onSelect?.({ kind: 'vehicle', id: vehicle.id }) }}
                >
                  <Popup>
                    <strong>{vehicle.vehicle_code}</strong> ({titleCase(vehicle.vehicle_type)})
                    <br />
                    Status: {titleCase(vehicle.status)} · cap {vehicle.capacity.toLocaleString()} kg
                    <br />
                    <span className="muted">Simulated position: {vehicle.current_location}</span>
                  </Popup>
                </Marker>
              ))}
          </LayerGroup>
        )}

        {/* Incidents */}
        {visible.incidents && (
          <LayerGroup>
            {overview.incidents.map((incident) => (
              <Marker
                key={`inc-${incident.id}`}
                position={[incident.latitude, incident.longitude]}
                icon={pinIcon('#f15b5b', SVG_ALERT, 20, incident.severity === 'critical')}
                eventHandlers={{ click: () => onSelect?.({ kind: 'incident', id: incident.id }) }}
              >
                <Popup>
                  <strong>{incident.title}</strong>
                  <br />
                  {titleCase(incident.incident_type)} · {titleCase(incident.severity)} ·{' '}
                  {titleCase(incident.status)}
                  <br />
                  {incident.location_name} · {incident.affected_population.toLocaleString()} affected
                </Popup>
              </Marker>
            ))}
          </LayerGroup>
        )}
      </MapContainer>

      {/* Toolbar */}
      <div className="map-toolbar">
        <button
          className="map-btn"
          title="Reset view"
          aria-label="Reset map view"
          onClick={() => setRecenter(center)}
        >
          <Crosshair size={15} />
        </button>
        <button
          className="map-btn"
          title={fullscreen ? 'Exit fullscreen' : 'Fullscreen map'}
          aria-label="Toggle fullscreen map"
          onClick={() => setIsFullscreen((value) => !value)}
        >
          {fullscreen ? <Minimize size={15} /> : <Expand size={15} />}
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
          ] as const
        ).map(([key, label]) => (
          <label key={key} className="layer-toggle">
            <input type="checkbox" checked={visible[key]} onChange={() => toggle(key)} />
            {label}
          </label>
        ))}
      </div>

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
          <span className="legend-swatch" style={{ background: '#3d6a95' }} /> Road (normal)
        </div>
        <div className="legend-row">
          <span className="legend-swatch" style={{ background: '#ff963d' }} /> High-risk road
        </div>
        <div className="legend-row">
          <span className="legend-swatch" style={{ background: '#f15b5b' }} /> Blocked road
        </div>
        <div className="legend-row">
          <span className="legend-swatch" style={{ background: '#35e0ff' }} /> Active route
        </div>
        <div className="legend-row muted">Vehicle markers: backend simulated positions only</div>
      </div>
    </div>
  );
}
