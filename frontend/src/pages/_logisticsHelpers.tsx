import { formatNumber, formatPercent, supplyLabel, titleCase } from '../utils/format';
import type {
  AllocationPlanResponse,
  DemandAssessmentResponse,
  MapOverviewResponse,
  Priority,
  RouteRead,
} from '../types';
import type { RouteOverlay } from '../components/map/DisasterMap';
import { StatusBadge } from '../components/common/StatusBadge';
import { PRIORITY_CLASS } from '../utils/format';

/** Resolve a route (node-id list) into a mappable overlay using real node coordinates. */
export function mapDataToRouteOverlay(
  overlay: { nodes: number[]; label: string; color?: string; dashed?: boolean },
  mapData: MapOverviewResponse | null,
): RouteOverlay | null {
  if (!mapData) return null;
  const coords = new Map(mapData.road_nodes.map((node) => [node.id, { lat: node.latitude, lng: node.longitude }]));
  const resolved = overlay.nodes.filter((nodeId) => coords.has(nodeId));
  if (resolved.length < 2) return null;
  return {
    nodeIds: resolved,
    label: overlay.label,
    color: overlay.color,
    dashed: overlay.dashed,
  };
}

export function TotalDemandStrip({ demand }: { demand: DemandAssessmentResponse }) {
  const supplies = ['water_litre', 'food_kit', 'medical_kit', 'hygiene_kit'];
  return (
    <div className="grid-4">
      {supplies.map((supply) => {
        const required = demand.summary.total_required_by_supply[supply] ?? 0;
        const shortage = demand.summary.total_shortage_by_supply[supply] ?? 0;
        return (
          <div key={supply} className="metric-card" style={{ '--metric-accent': shortage > 0 ? 'var(--accent-orange)' : 'var(--accent-green)' } as React.CSSProperties}>
            <div className="metric-label">{supplyLabel(supply)}</div>
            <div className="metric-value" style={{ fontSize: 19 }}>{formatNumber(required)}</div>
            <div className="metric-sub">
              required in {demand.horizon_hours}h ·{' '}
              {shortage > 0 ? (
                <span style={{ color: 'var(--accent-orange)' }}>{formatNumber(shortage)} short</span>
              ) : (
                <span style={{ color: 'var(--accent-green)' }}>no shortage</span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function AllocationPanel({ plan }: { plan: AllocationPlanResponse }) {
  const summary = plan.summary;
  const supplies = ['water_litre', 'food_kit', 'medical_kit', 'hygiene_kit'];
  return (
    <div className="stack-12">
      <div className="muted">
        Planning run #{plan.planning_run_id ?? '…'} · computed {plan.generated_at ? new Date(plan.generated_at).toLocaleTimeString() : ''} · horizon {plan.horizon_hours}h
      </div>

      <div className="row-12">
        <div className="metric-card" style={{ flex: 1 }}>
          <div className="metric-label">Fulfilment</div>
          <div className="metric-value">{formatPercent(summary.fulfilment_percentage)}</div>
          <div className="metric-sub">
            {summary.centres_served}/{summary.centres_planned} centres served ·{' '}
            {summary.centres_with_unmet_demand} with unmet demand
          </div>
        </div>
        <div className="metric-card" style={{ flex: 1, '--metric-accent': 'var(--accent-red)' } as React.CSSProperties}>
          <div className="metric-label">Unfulfilled demand</div>
          <div className="metric-value" style={{ color: summary.unfulfilled_by_supply && Object.values(summary.unfulfilled_by_supply).some((v) => v > 0) ? 'var(--accent-red)' : undefined }}>
            {supplies.reduce((sum, s) => sum + (summary.unfulfilled_by_supply?.[s] ?? 0), 0).toLocaleString()}
          </div>
          <div className="metric-sub">
            {supplies.map((s) => `${titleCase(supplyLabel(s))}: ${formatNumber(summary.unfulfilled_by_supply?.[s] ?? 0)}`).join(' · ')}
          </div>
        </div>
      </div>

      <div>
        <div className="section-title" style={{ margin: '10px 0 8px' }}>Allocation lines (backend result)</div>
        <div className="table-wrap">
          <table className="op-table">
            <thead>
              <tr>
                <th>Relief centre</th>
                <th>Supply</th>
                <th>Required</th>
                <th>Stock at centre</th>
                <th>Allocated</th>
                <th>Unfulfilled</th>
                <th>Source warehouses</th>
              </tr>
            </thead>
            <tbody>
              {plan.centres.flatMap((centre) =>
                centre.lines
                  .filter((line) => line.required_quantity > 0 || line.allocated_quantity > 0)
                  .map((line) => (
                    <tr key={`${centre.relief_centre_id}-${line.supply_type}`}>
                      <td>
                        {centre.name}
                        <div className="muted">
                          {centre.district} ·{' '}
                          <StatusBadge
                            value={centre.centre_priority}
                            className={PRIORITY_CLASS[centre.centre_priority as Priority]}
                          />
                        </div>
                      </td>
                      <td>{supplyLabel(line.supply_type)}</td>
                      <td className="num">{formatNumber(line.required_quantity)}</td>
                      <td className="num">{formatNumber(line.current_stock)}</td>
                      <td className="num positive-value">{formatNumber(line.allocated_quantity)}</td>
                      <td className={`num ${line.unfulfilled_quantity > 0 ? 'negative-value' : ''}`}>
                        {formatNumber(line.unfulfilled_quantity)}
                      </td>
                      <td>
                        {line.sources.length === 0 ? (
                          <span className="muted">—</span>
                        ) : (
                          line.sources
                            .map(
                              (source) =>
                                `${source.warehouse_name}: ${formatNumber(source.quantity)} (${source.route_distance_km} km, ${source.route_travel_time_minutes} min, risk ${source.route_risk.toFixed(2)})`,
                            )
                            .join(' · ')
                        )}
                      </td>
                    </tr>
                  )),
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div>
        <div className="section-title" style={{ margin: '10px 0 8px' }}>Warehouse stock remaining after plan</div>
        <div className="table-wrap">
          <table className="op-table">
            <thead>
              <tr>
                <th>Warehouse</th>
                {supplies.map((supply) => (
                  <th key={supply} style={{ textAlign: 'right' }}>{supplyLabel(supply)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {summary.warehouse_utilisation.map((warehouse) => (
                <tr key={warehouse.warehouse_id}>
                  <td>{warehouse.warehouse_name}</td>
                  {supplies.map((supply) => {
                    const initial = warehouse.initial_available_by_supply[supply] ?? 0;
                    const allocated = warehouse.allocated_by_supply[supply] ?? 0;
                    const remaining = warehouse.remaining_by_supply[supply] ?? 0;
                    return (
                      <td key={supply} className="num">
                        {formatNumber(allocated)} / {formatNumber(initial)}
                        <div className="muted">{formatNumber(remaining)} remaining</div>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

/** Route summary card for the planning page. */
export function RouteResult({
  route,
  recalc,
}: {
  route: RouteRead;
  recalc: {
    historical_route_available: boolean;
    current_route: RouteRead;
    previous_route: RouteRead | null;
    delay_minutes: number | null;
    distance_delta_km: number | null;
    alternative_route_available: boolean;
    explanation: string;
  } | null;
}) {
  return (
    <div className="stack-8">
      <div className="card card-body">
        <div className="row-12">
          <strong>Route from {route.origin} to {route.destination}</strong>
          {!route.reachable && <span className="badge sev-critical">Unreachable</span>}
        </div>
        {route.reachable ? (
          <div className="stack-8" style={{ marginTop: 8 }}>
            <div className="kv-row"><span className="k">Distance</span><span className="v">{formatNumber(route.distance_km, 1)} km</span></div>
            <div className="kv-row"><span className="k">Estimated travel time</span><span className="v">{route.estimated_travel_time_minutes} min</span></div>
            <div className="kv-row"><span className="k">Route risk</span><span className="v">{route.route_risk.toFixed(2)}</span></div>
            <div className="kv-row"><span className="k">Blocked segments avoided</span><span className="v">{route.blocked_segments_avoided}</span></div>
            <div className="muted">Path: {route.route_node_names.join(' → ')}</div>
          </div>
        ) : (
          <div className="muted" style={{ marginTop: 6 }}>
            {route.message || 'No reachable route exists right now — check road blockages in the Simulation Lab.'}
          </div>
        )}
      </div>
      {recalc && (
        <div className="card card-body">
          <div className="section-title" style={{ marginBottom: 6 }}>Recalculation comparison</div>
          <div className="stack-8">
            {recalc.previous_route ? (
              <>
                <div className="kv-row">
                  <span className="k">Previous route</span>
                  <span className="v">
                    {formatNumber(recalc.previous_route.distance_km, 1)} km · {recalc.previous_route.estimated_travel_time_minutes} min · risk {recalc.previous_route.route_risk.toFixed(2)}
                  </span>
                </div>
                <div className="kv-row">
                  <span className="k">Current route</span>
                  <span className="v">
                    {formatNumber(recalc.current_route.distance_km, 1)} km · {recalc.current_route.estimated_travel_time_minutes} min · risk {recalc.current_route.route_risk.toFixed(2)}
                  </span>
                </div>
                {recalc.delay_minutes !== null && (
                  <div className="kv-row">
                    <span className="k">Delay vs previous</span>
                    <span className="v" style={{ color: recalc.delay_minutes > 0 ? 'var(--accent-orange)' : undefined }}>
                      +{recalc.delay_minutes} min
                    </span>
                  </div>
                )}
              </>
            ) : (
              <div className="muted">No previous persisted route for this pair.</div>
            )}
            <div className="muted">{recalc.explanation}</div>
          </div>
        </div>
      )}
    </div>
  );
}
