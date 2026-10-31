import { useEffect, useMemo, useState } from 'react';
import {
  Truck,
  Wrench,
  Gauge,
  LocateFixed,
} from 'lucide-react';
import { useBackendData } from '../hooks/useBackendData';
import { getFleetOverview, getOrderTracking } from '../api/dispatch';
import { getMapOverview } from '../api/resources';
import { ErrorState } from '../components/common/ErrorState';
import { EmptyState } from '../components/common/EmptyState';
import { LoadingSkeleton } from '../components/common/LoadingSkeleton';
import { StatusBadge } from '../components/common/StatusBadge';
import { ProgressBar } from '../components/common/ProgressBar';
import {
  VEHICLE_STATUS_CLASS,
  formatKg,
  formatNumber,
  formatTime,
  titleCase,
} from '../utils/format';
import type { TrackingResponse } from '../types';

const STATUS_FILTERS = [
  '',
  'available',
  'assigned',
  'in_transit',
  'maintenance',
  'delayed',
] as const;

export function FleetManagementPage() {
  const fleet = useBackendData((signal) => getFleetOverview(signal), [], 8000);
  const overview = useBackendData((signal) => getMapOverview(signal), [], 10000);
  const [statusFilter, setStatusFilter] = useState('');
  const [search, setSearch] = useState('');
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const vehicles = fleet.data?.vehicles ?? [];
  const coordsById = useMemo(() => {
    const map = new Map<number, { lat: number | null; lng: number | null }>();
    (overview.data?.vehicles ?? []).forEach((v) => map.set(v.id, { lat: v.current_latitude, lng: v.current_longitude }));
    return map;
  }, [overview.data]);

  const filtered = vehicles.filter((vehicle) => {
    if (statusFilter && vehicle.status !== statusFilter) return false;
    if (search && !vehicle.vehicle_code.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  const selected =
    vehicles.find((vehicle) => vehicle.id === selectedId) ?? filtered[0] ?? null;

  // Live simulated tracking for the selected vehicle's active order.
  const [tracking, setTracking] = useState<TrackingResponse | null>(null);
  const activeOrderId = selected?.active_order_id ?? null;
  useEffect(() => {
    if (activeOrderId === null) {
      setTracking(null);
      return;
    }
    let cancelled = false;
    let stopped = false;
    const load = async () => {
      try {
        const result = await getOrderTracking(activeOrderId);
        if (!cancelled && !stopped) setTracking(result);
      } catch {
        if (!cancelled) setTracking(null);
      }
    };
    void load();
    const id = setInterval(() => {
      if (document.visibilityState === 'visible' && !stopped) void load();
    }, 4000);
    return () => {
      cancelled = true;
      stopped = true;
      clearInterval(id);
    };
  }, [activeOrderId, selected?.id]);

  return (
    <div className="stack-16">
      {/* Fleet KPIs — straight from GET /dispatch/fleet/overview */}
      {fleet.error ? (
        <ErrorState error={fleet.error} onRetry={fleet.refresh} />
      ) : fleet.loading ? (
        <LoadingSkeleton variant="table" />
      ) : (
        fleet.data && (
          <div className="metric-row">
            <Metric label="Total fleet" value={fleet.data.total_vehicles} accent="var(--accent-blue)" sub="registered vehicles" />
            <Metric label="Available" value={fleet.data.available} accent="var(--accent-green)" sub="ready for assignment" />
            <Metric label="Assigned" value={fleet.data.assigned} accent="var(--accent-blue)" sub="have a draft/active order" />
            <Metric label="In transit" value={fleet.data.in_transit} accent="var(--accent-cyan)" sub="actively moving (simulated)" />
            <Metric label="Delayed" value={fleet.data.delayed} accent="var(--accent-orange)" sub="route disrupted" />
            <Metric label="Maintenance" value={fleet.data.under_maintenance} accent="var(--text-muted)" sub="unavailable" />
            <Metric label="Free capacity" value={`${formatKg(fleet.data.total_capacity_kg_available)}`} accent="var(--accent-green)" sub="across available vehicles" />
          </div>
        )
      )}

      <div className="grid-2-1" style={{ alignItems: 'stretch' }}>
        {/* Vehicle table */}
        <div className="card">
          <div className="card-header">
            <Truck size={15} className="header-icon" />
            <h3>Vehicles</h3>
            <div className="card-header-right row-8">
              <input
                placeholder="Search code…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                style={{ width: 130, fontSize: 12 }}
              />
            </div>
          </div>
          <div className="card-body">
            <div className="filter-row" style={{ marginBottom: 10 }}>
              {STATUS_FILTERS.map((status) => (
                <button
                  key={status}
                  className={`btn small ${statusFilter === status ? 'primary' : 'ghost'}`}
                  onClick={() => setStatusFilter(status)}
                >
                  {status === '' ? 'All' : titleCase(status)}
                </button>
              ))}
            </div>
            {fleet.error ? (
              <ErrorState error={fleet.error} onRetry={fleet.refresh} />
            ) : fleet.loading ? (
              <LoadingSkeleton variant="table" />
            ) : filtered.length === 0 ? (
              <EmptyState message="No vehicles match this filter." />
            ) : (
              <div className="table-wrap">
                <table className="op-table">
                  <thead>
                    <tr>
                      <th>Code</th>
                      <th>Type</th>
                      <th>Capacity</th>
                      <th>Status</th>
                      <th>Location</th>
                      <th>Active order</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.map((vehicle) => (
                      <tr
                        key={vehicle.id}
                        className="clickable"
                        onClick={() => setSelectedId(vehicle.id)}
                        style={selected?.id === vehicle.id ? { background: 'rgba(49,154,255,0.08)' } : undefined}
                      >
                        <td style={{ fontWeight: selected?.id === vehicle.id ? 650 : 400 }}>{vehicle.vehicle_code}</td>
                        <td>{titleCase(vehicle.vehicle_type)}</td>
                        <td className="num">{formatNumber(vehicle.capacity_kg ?? vehicle.capacity)} kg</td>
                        <td>
                          <StatusBadge value={vehicle.status} className={VEHICLE_STATUS_CLASS[vehicle.status]} />
                        </td>
                        <td className="muted">{vehicle.current_location || '—'}</td>
                        <td>{vehicle.active_order_code ?? <span className="muted">—</span>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>

        {/* Vehicle detail panel */}
        <div className="card">
          <div className="card-header">
            <h3>{selected ? `Vehicle ${selected.vehicle_code}` : 'Vehicle detail'}</h3>
            {selected && (
              <div className="card-header-right">
                <StatusBadge value={selected.status} className={VEHICLE_STATUS_CLASS[selected.status]} />
              </div>
            )}
          </div>
          <div className="card-body">
            {!selected ? (
              <EmptyState message="Select a vehicle row to inspect it." />
            ) : (
              <div className="stack-12">
                <div className="kv-row">
                  <span className="k">Type / capacity</span>
                  <span className="v">
                    {titleCase(selected.vehicle_type)} · {formatNumber(selected.capacity_kg ?? selected.capacity)} kg
                  </span>
                </div>
                <div className="kv-row">
                  <span className="k">Home location</span>
                  <span className="v">{selected.current_location || '—'}</span>
                </div>
                <div className="kv-row">
                  <span className="k">Active order</span>
                  <span className="v">
                    {selected.active_order_code
                      ? `${selected.active_order_code} (#${selected.active_order_id})`
                      : 'none'}
                  </span>
                </div>
                <div className="kv-row">
                  <span className="k">Last known position</span>
                  <span className="v">
                    {(() => {
                      const coords = coordsById.get(selected.id);
                      if (coords && coords.lat !== null && coords.lng !== null) {
                        return `${coords.lat.toFixed(4)}, ${coords.lng.toFixed(4)} (simulated)`;
                      }
                      return 'not moving — at base';
                    })()}
                  </span>
                </div>

                {selected.active_order_code && tracking ? (
                  <div className="card card-body" style={{ padding: 10 }}>
                    <div className="spread">
                      <div className="section-title">
                        <LocateFixed size={13} /> Simulated tracking — {tracking.order_code}
                      </div>
                      <div className="muted" style={{ fontSize: 11 }}>
                        updated {formatTime(tracking.last_updated_at)}
                      </div>
                    </div>
                    <ProgressBar percent={tracking.progress_percent} tone={tracking.delayed ? 'warn' : 'primary'} />
                    <div className="row-12 muted" style={{ fontSize: 12 }}>
                      <span>Origin {tracking.origin}</span>
                      <span>→ {tracking.destination}</span>
                    </div>
                    <div className="row-12 muted" style={{ fontSize: 12 }}>
                      <span>{formatNumber(tracking.progress_km, 1)} / {formatNumber(tracking.total_distance_km, 1)} km</span>
                      <span>~{tracking.remaining_travel_time_minutes} min remaining (simulated)</span>
                    </div>
                    {tracking.current_node_name && (
                      <div className="muted" style={{ fontSize: 12 }}>
                        Last node: {tracking.current_node_name}
                        {tracking.current_latitude !== null && tracking.current_longitude !== null && (
                          <> · position {tracking.current_latitude.toFixed(4)}, {tracking.current_longitude.toFixed(4)}</>
                        )}
                      </div>
                    )}
                  </div>
                ) : selected.active_order_code ? (
                  <div className="muted">Loading live tracking…</div>
                ) : (
                  <div className="card card-body" style={{ padding: 10, color: 'var(--text-muted)' }}>
                    No active dispatch order — this vehicle is idle at its home location. Positions come from the
                    simulated movement engine only while an order is in transit.
                  </div>
                )}

                {selected.status === 'maintenance' && (
                  <div className="muted" id="fleet-note-maintenance">
                    <Wrench size={13} style={{ verticalAlign: -2 }} /> Vehicle is under maintenance and cannot be
                    assigned; the auto-assignment engine skips it.
                  </div>
                )}
                <div className="muted" style={{ fontSize: 11, display: 'flex', gap: 6, alignItems: 'center' }}>
                  <Gauge size={12} /> Positions and travel times are SIMULATED by the backend movement engine — never real GPS.
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function Metric({
  label,
  value,
  accent,
  sub,
}: {
  label: string;
  value: number | string;
  accent: string;
  sub: string;
}) {
  return (
    <div className="metric-card" style={{ '--metric-accent': accent } as React.CSSProperties}>
      <div className="metric-label">{label}</div>
      <div className="metric-value" style={{ fontSize: 21 }}>{value}</div>
      <div className="metric-sub">{sub}</div>
    </div>
  );
}
