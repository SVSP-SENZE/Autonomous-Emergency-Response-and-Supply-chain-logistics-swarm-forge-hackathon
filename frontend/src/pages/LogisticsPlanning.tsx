import { useMemo, useState } from 'react';
import { AlertTriangle, BarChart3, Route as RouteIcon, Warehouse as WarehouseIcon } from 'lucide-react';
import { useBackendData } from '../hooks/useBackendData';
import {
  computeAllocation,
  computeDemand,
  getPlanningRunDetail,
  listPlanningRuns,
  recalculateRoute,
  routeBetweenEntities,
} from '../api/logistics';
import { getMapOverview, listReliefCentres, listWarehouses } from '../api/resources';
import { EmptyState } from '../components/common/EmptyState';
import { StatusBadge } from '../components/common/StatusBadge';
import { ShortageBar } from '../components/common/ProgressBar';
import { ConfirmDialog } from '../components/common/ConfirmDialog';
import { useToast } from '../components/common/Toast';
import {
  PRIORITY_CLASS,
  formatDateTime,
  formatNumber,
  formatPercent,
  titleCase,
} from '../utils/format';
import { DisasterMap, type RouteOverlay } from '../components/map/DisasterMap';
import {
  AllocationPanel,
  RouteResult,
  TotalDemandStrip,
  mapDataToRouteOverlay,
} from './_logisticsHelpers';
import type {
  AllocationPlanResponse,
  DemandAssessmentResponse,
  RouteEntitiesPayload,
  ReliefCentre,
  Warehouse,
} from '../types';

const HORIZONS = [6, 12, 24, 48, 72];

export function LogisticsPlanningPage() {
  const [horizon, setHorizon] = useState(24);
  const [demand, setDemand] = useState<DemandAssessmentResponse | null>(null);
  const [allocation, setAllocation] = useState<AllocationPlanResponse | null>(null);
  const [busy, setBusy] = useState<'demand' | 'allocation' | 'route' | 'recalc' | null>(null);
  const [confirmAllocation, setConfirmAllocation] = useState(false);
  const [confirmRecalc, setConfirmRecalc] = useState(false);
  const [demandError, setDemandError] = useState<string | null>(null);
  const [allocationError, setAllocationError] = useState<string | null>(null);
  const [routeError, setRouteError] = useState<string | null>(null);
  const { push } = useToast();

  const centres = useBackendData((signal) => listReliefCentres(signal), [], 30000);
  const warehouses = useBackendData((signal) => listWarehouses(signal), [], 30000);
  const mapOverview = useBackendData((signal) => getMapOverview(signal), [], 10000);
  const runHistory = useBackendData((signal) => listPlanningRuns(undefined, 25, signal), [], 30000);
  const [inspectedRunId, setInspectedRunId] = useState<number | null>(null);
  const inspectedRun = useBackendData(
    async (signal) => (inspectedRunId === null ? null : getPlanningRunDetail(inspectedRunId, signal)),
    [inspectedRunId],
  );

  // Route planning state
  const [originId, setOriginId] = useState<string>('');
  const [destinationId, setDestinationId] = useState<string>('');
  const [route, setRoute] = useState<Awaited<ReturnType<typeof routeBetweenEntities>> | null>(null);
  const [recalcResult, setRecalcResult] = useState<Awaited<ReturnType<typeof recalculateRoute>> | null>(null);

  const computeDemandNow = async (persist = true) => {
    setBusy('demand');
    setDemandError(null);
    try {
      setDemand(await computeDemand(horizon, persist));
      push(`Demand assessment computed for a ${horizon}h horizon (simulated scenario).`, 'success');
    } catch (err) {
      setDemandError(err instanceof Error ? err.message : 'Demand estimation failed');
    } finally {
      setBusy(null);
    }
  };

  const computeAllocationNow = async () => {
    setConfirmAllocation(false);
    setBusy('allocation');
    setAllocationError(null);
    try {
      const plan = await computeAllocation(horizon);
      setAllocation(plan);
      push(`Allocation plan #${plan.planning_run_id} computed (${formatPercent(plan.summary.fulfilment_percentage)} fulfilment).`, 'success');
    } catch (err) {
      setAllocationError(err instanceof Error ? err.message : 'Allocation computation failed');
    } finally {
      setBusy(null);
    }
  };

  const computeRoute = async () => {
    if (!originId || !destinationId) {
      setRouteError('Select both an origin warehouse and a destination relief centre.');
      return;
    }
    setBusy('route');
    setRouteError(null);
    setRecalcResult(null);
    try {
      const payload: RouteEntitiesPayload = {
        origin_type: 'warehouse',
        origin_id: Number(originId),
        destination_type: 'relief_centre',
        destination_id: Number(destinationId),
      };
      const result = await routeBetweenEntities(payload);
      setRoute(result);
      push(result.reachable ? 'Safe route calculated.' : 'No reachable route found with current roads.', result.reachable ? 'success' : 'info');
    } catch (err) {
      setRouteError(err instanceof Error ? err.message : 'Route calculation failed');
      setRoute(null);
    } finally {
      setBusy(null);
    }
  };

  const recalculateNow = async () => {
    setConfirmRecalc(false);
    setBusy('recalc');
    try {
      const result = await routeBetweenEntities({
        origin_type: 'warehouse',
        origin_id: Number(originId),
        destination_type: 'relief_centre',
        destination_id: Number(destinationId),
      });
      setRoute(result);
      const originNode = result.origin_node_id;
      const destinationNode = result.destination_node_id;
      const comparison = await recalculateRoute(originNode, destinationNode);
      setRecalcResult(comparison);
      push(comparison.alternative_route_available
        ? 'Recalculation complete: current route compared with previous plan.'
        : comparison.historical_route_available
          ? 'Recalculation complete — no alternative route is available.'
          : 'Recalculation complete — first recorded calculation for this pair.', 'info');
    } catch (err) {
      setRouteError(err instanceof Error ? err.message : 'Recalculation failed');
    } finally {
      setBusy(null);
    }
  };

  const mapData = mapOverview.data;
  const routeOverlays = useMemo(() => {
    const overlays: { nodes: number[]; label: string; color?: string; dashed?: boolean }[] = [];
    if (route?.reachable && route.route_nodes?.length > 0) {
      overlays.push({ nodes: route.route_nodes, label: 'Selected safe route', color: '#35e0ff' });
    }
    if (recalcResult?.previous_route?.reachable) {
      overlays.push({
        nodes: recalcResult.previous_route.route_nodes,
        label: 'Previous persisted route',
        color: '#ff963d',
        dashed: true,
      });
    }
    return overlays
      .map((overlay) => mapDataToRouteOverlay(overlay, mapData))
      .filter((overlay): overlay is RouteOverlay => overlay !== null);
  }, [route, recalcResult, mapData]);

  return (
    <div className="stack-16">
      {/* Demand estimation */}
      <div className="card">
        <div className="card-header">
          <AlertTriangle size={15} className="header-icon" />
          <h3>Demand assessment</h3>
          <div className="card-header-right row-8">
            {HORIZONS.map((h) => (
              <button
                key={h}
                className={`btn small ${horizon === h ? 'primary' : 'ghost'}`}
                onClick={() => setHorizon(h)}
              >
                {h}h
              </button>
            ))}
            <button className="btn success" disabled={busy !== null} onClick={() => void computeDemandNow(true)}>
              {busy === 'demand' ? 'Calculating…' : 'Calculate demand'}
            </button>
          </div>
        </div>
        <div className="card-body">
          {demandError && (
            <div style={{ color: 'var(--accent-red)', fontSize: 12.5, marginBottom: 10 }}>{demandError}</div>
          )}
          {demand ? (
            <>
              {demand.planning_run_id ? (
                <div className="muted" style={{ marginBottom: 10 }}>
                  Persisted planning run #{demand.planning_run_id} · horizon {demand.horizon_hours}h ·{' '}
                  {demand.summary.centres_assessed} centres assessed, {demand.summary.centres_eligible} allocation-eligible
                </div>
              ) : null}
              <TotalDemandStrip demand={demand} />
              <div className="table-wrap" style={{ marginTop: 14 }}>
                <table className="op-table">
                  <thead>
                    <tr>
                      <th>Relief centre</th>
                      <th>Population</th>
                      <th>Water shortage</th>
                      <th>Food shortage</th>
                      <th>Medical shortage</th>
                      <th>Hygiene shortage</th>
                      <th>Priority</th>
                    </tr>
                  </thead>
                  <tbody>
                    {demand.centres.map((centre) => (
                      <tr key={centre.relief_centre_id}>
                        <td>
                          {centre.name}
                          <div className="muted">{centre.district} · score {centre.priority_score.toFixed(1)}</div>
                        </td>
                        <td className="num">{formatNumber(centre.affected_population)}</td>
                        {(['water_litre', 'food_kit', 'medical_kit', 'hygiene_kit'] as const).map((key) => {
                          const item = centre.items.find((i) => i.supply_type === key);
                          const pct = item ? item.shortage_percentage : 0;
                          return (
                            <td key={key}>
                              <div className="row-8" style={{ gap: 6, flexWrap: 'nowrap' }}>
                                <ShortageBar percent={pct} />
                                <span className="muted" style={{ fontVariantNumeric: 'tabular-nums', minWidth: 76 }}>
                                  {item ? formatNumber(item.shortage_quantity) + ' ' + item.unit : '—'}
                                  {pct > 0 ? ` (${pct.toFixed(0)}%)` : ''}
                                </span>
                              </div>
                            </td>
                          );
                        })}
                        <td>
                          <StatusBadge
                            value={centre.centre_priority}
                            className={PRIORITY_CLASS[centre.centre_priority]}
                            label={centre.priority_classification}
                          />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="muted" style={{ marginTop: 8 }}>
                {demand.assumptions.note} Shortage bars are computed by the backend demand engine per{' '}
                {demand.assumptions.consumption_rates_per_person_per_day?.water_litre ?? '—'} L/person/day water{' '}
                (backend-documented demo assumptions).
              </div>
            </>
          ) : (
            <EmptyState message="No demand assessment loaded for this session yet. Pick a horizon and press “Calculate demand”." />
          )}
        </div>
      </div>

      {/* Allocation */}
      <div className="card">
        <div className="card-header">
          <BarChart3 size={15} className="header-icon" />
          <h3>Resource allocation plan</h3>
          <div className="card-header-right">
            <button className="btn success" disabled={busy !== null} onClick={() => setConfirmAllocation(true)}>
              {busy === 'allocation' ? 'Computing…' : 'Compute allocation'}
            </button>
          </div>
        </div>
        <div className="card-body">
          {allocationError && (
            <div style={{ color: 'var(--accent-red)', fontSize: 12.5, marginBottom: 10 }}>{allocationError}</div>
          )}
          {allocation ? (
            <AllocationPanel plan={allocation} />
          ) : (
            <EmptyState message="No allocation computed in this session. Press “Compute allocation” to plan against current warehouse stock." />
          )}
        </div>
      </div>

      {/* Route planning + map */}
      <div className="grid-2-1">
        <div className="card">
          <div className="card-header">
            <RouteIcon size={15} className="header-icon" />
            <h3>Route planning</h3>
          </div>
          <div className="card-body stack-12">
            <div className="form-grid">
              <div className="field">
                <label>Origin warehouse</label>
                <select value={originId} onChange={(e) => setOriginId(e.target.value)} aria-label="Origin warehouse">
                  <option value="">Select warehouse…</option>
                  {(warehouses.data?.items ?? []).map((warehouse: Warehouse) => (
                    <option key={warehouse.id} value={warehouse.id}>{warehouse.name}</option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label>Destination relief centre</label>
                <select value={destinationId} onChange={(e) => setDestinationId(e.target.value)} aria-label="Destination relief centre">
                  <option value="">Select relief centre…</option>
                  {(centres.data?.items ?? []).map((centre: ReliefCentre) => (
                    <option key={centre.id} value={centre.id}>{centre.name}</option>
                  ))}
                </select>
              </div>
            </div>
            <div className="row-8">
              <button className="btn primary" disabled={busy !== null} onClick={() => void computeRoute()}>
                {busy === 'route' ? 'Calculating…' : 'Calculate safe route'}
              </button>
              <button
                className="btn ghost"
                disabled={busy !== null || !route}
                onClick={() => setConfirmRecalc(true)}
                title="Persisted route required — recalculates and compares against the last persisted version"
              >
                Recalculate after disruption
              </button>
              <span className="muted">Routes run on the backend road network, excluding blocked segments.</span>
            </div>
            {routeError && (
              <div style={{ color: 'var(--accent-red)', fontSize: 12.5 }}>{routeError}</div>
            )}
            {route && <RouteResult route={route} recalc={recalcResult} />}
          </div>
        </div>

        <div style={{ minHeight: 460 }}>
          <DisasterMap overview={mapData} height={460} routeOverlays={routeOverlays} />
        </div>
      </div>

      {/* Plan history */}
      <div className="card">
        <div className="card-header">
          <WarehouseIcon size={15} className="header-icon" />
          <h3>Planning run history (persisted snapshots)</h3>
          <div className="card-header-right muted">historical snapshots are immutable</div>
        </div>
        <div className="card-body">
          <div className="grid-2">
            <div className="table-wrap">
              <table className="op-table">
                <thead>
                  <tr>
                    <th>Run</th>
                    <th>Type</th>
                    <th>Horizon</th>
                    <th>Status</th>
                    <th>Created</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {(runHistory.data?.items ?? []).map((run) => (
                    <tr key={run.id}>
                      <td className="num">#{run.id}</td>
                      <td>{titleCase(run.planning_type)}</td>
                      <td>{run.planning_horizon_hours ? `${run.planning_horizon_hours}h` : '—'}</td>
                      <td><StatusBadge value={run.status} className="badge-plain" /></td>
                      <td className="muted">{formatDateTime(run.created_at)}</td>
                      <td>
                        <button className="btn ghost small" onClick={() => setInspectedRunId(run.id)}>Inspect</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="card card-body" style={{ maxHeight: 400, overflowY: 'auto' }}>
              {inspectedRun.data ? (
                <>
                  <strong>Snapshotted summary — run #{inspectedRun.data.id} ({titleCase(inspectedRun.data.planning_type)})</strong>
                  <pre className="muted" style={{ whiteSpace: 'pre-wrap', fontSize: 11, marginTop: 8 }}>
                    {JSON.stringify(inspectedRun.data.summary, null, 2)}
                  </pre>
                </>
              ) : (
                <EmptyState message="Press Inspect on a planning run to view its persisted summary snapshot." />
              )}
            </div>
          </div>
        </div>
      </div>
      <ConfirmDialog
        open={confirmAllocation}
        title="Compute an allocation plan?"
        body={`This uses the backend allocator on current warehouse stock for the ${horizon}h horizon. It creates a persisted planning snapshot but NEVER reserves, deducts or moves any inventory.`}
        bullets={["Proposed plan only — dispatch happens later under operator approval."]}
        confirmLabel="Compute plan"
        busy={busy === 'allocation'}
        onConfirm={() => void computeAllocationNow()}
        onCancel={() => setConfirmAllocation(false)}
      />
      <ConfirmDialog
        open={confirmRecalc}
        title="Recalculate this route after disruption?"
        body="The backend compares the recalculated route with the last persisted one for the pair (origin → destination). A new planning snapshot is recorded."
        confirmLabel="Recalculate"
        busy={busy === 'recalc'}
        onConfirm={() => void recalculateNow()}
        onCancel={() => setConfirmRecalc(false)}
      />
    </div>
  );
}
