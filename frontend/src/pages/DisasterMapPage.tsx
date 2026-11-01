import { useMemo, useState } from 'react';
import { AlertTriangle, MapPin, PackageSearch, Truck } from 'lucide-react';
import { useBackendData } from '../hooks/useBackendData';
import { getMapOverview, getReliefCentreDetail, getWarehouseDetail } from '../api/resources';
import { DisasterMap, type EntitySelection, type MapMode, type RouteOverlay } from '../components/map/DisasterMap';
import { RoutePlanner, type PlannedRoute } from '../components/map/RoutePlanner';
import { ErrorState } from '../components/common/ErrorState';
import { LoadingSkeleton } from '../components/common/LoadingSkeleton';
import { EmptyState } from '../components/common/EmptyState';
import { StatusBadge } from '../components/common/StatusBadge';
import {
  OPERATIONAL_STATUS_CLASS,
  PRIORITY_CLASS,
  formatNumber,
  titleCase,
} from '../utils/format';
import type { ReliefCentreDetail, WarehouseDetail } from '../types';

type Detail =
  | { kind: 'centre'; data: ReliefCentreDetail }
  | { kind: 'warehouse'; data: WarehouseDetail }
  | null;

/** Overlay colour per planner safety verdict: unsafe red, caution amber, safe default orange. */
const UNSAFE_ROUTE_COLOR = '#f15b5b';
const CAUTION_ROUTE_COLOR = '#ffb020';

export function DisasterMapPage() {
  const mapOverview = useBackendData((signal) => getMapOverview(signal), [], 10000);
  const [selected, setSelected] = useState<EntitySelection>(null);
  const [detail, setDetail] = useState<Detail>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [mode, setMode] = useState<MapMode>('disaster');
  const [plannerRoute, setPlannerRoute] = useState<PlannedRoute | null>(null);
  const [fitNonce, setFitNonce] = useState(0);

  const loadDetail = async (selection: NonNullable<EntitySelection>) => {
    setSelected(selection);
    setDetail(null);
    setDetailError(null);
    if (selection.kind === 'centre') {
      setDetailLoading(true);
      try {
        setDetail({ kind: 'centre', data: await getReliefCentreDetail(selection.id) });
      } catch (err) {
        setDetailError(err instanceof Error ? err.message : 'Failed to load centre detail');
      } finally {
        setDetailLoading(false);
      }
    } else if (selection.kind === 'warehouse') {
      setDetailLoading(true);
      try {
        setDetail({ kind: 'warehouse', data: await getWarehouseDetail(selection.id) });
      } catch (err) {
        setDetailError(err instanceof Error ? err.message : 'Failed to load warehouse detail');
      } finally {
        setDetailLoading(false);
      }
    }
  };

  const summary = useMemo(() => {
    const overview = mapOverview.data;
    if (!overview) return null;
    return {
      warehouses: overview.warehouses.length,
      centres: overview.relief_centres.length,
      vehicles: overview.vehicles.length,
      blocked: overview.blocked_roads.length,
      critical: overview.relief_centres.filter((c) => c.priority === 'critical').length,
    };
  }, [mapOverview.data]);

  // The planner's Google road route becomes the only planner overlay: drawn
  // after an explicit origin/destination calculation, never a straight line.
  // Unsafe verdicts (verified closure on the geometry) draw red; caution amber.
  const plannerOverlays = useMemo<RouteOverlay[]>(() => {
    if (!plannerRoute) return [];
    return [
      {
        nodeIds: [],
        geometry: plannerRoute.result.path,
        label: plannerRoute.safety.safe
          ? 'Planned navigation route'
          : 'NO_SAFE_ROUTE_AVAILABLE — conflicts a verified closure',
        color: !plannerRoute.safety.safe
          ? UNSAFE_ROUTE_COLOR
          : plannerRoute.safety.caution
            ? CAUTION_ROUTE_COLOR
            : undefined,
        source: 'google-directions',
        safe: plannerRoute.safety.safe,
        plannedAt: plannerRoute.plannedAt,
      },
    ];
  }, [plannerRoute]);

  return (
    <div className="stack-16">
      <div className="row-12">
        <span className="sim-note">Simulation active · simulated map layers</span>
        {summary && (
          <div className="row-8 muted">
            <span><MapPin size={12} /> {summary.centres} relief centres ({summary.critical} critical)</span>
            <span><PackageSearch size={12} /> {summary.warehouses} warehouses</span>
            <span><Truck size={12} /> {summary.vehicles} vehicles</span>
            <span><AlertTriangle size={12} style={{ color: 'var(--accent-red)' }} /> {summary.blocked} blocked segments</span>
          </div>
        )}
      </div>

      <div className="grid-2-1">
        <div style={{ minHeight: 620 }}>
          {mapOverview.error ? (
            <ErrorState error={mapOverview.error} onRetry={mapOverview.refresh} title="Map failed to load" />
          ) : mapOverview.loading ? (
            <LoadingSkeleton variant="block" />
          ) : (
            <DisasterMap
              overview={mapOverview.data}
              height={620}
              routeOverlays={plannerOverlays}
              onSelect={loadDetail}
              selected={selected}
              mode={mode}
              onModeChange={setMode}
              fitNonce={fitNonce}
            />
          )}
        </div>

        <div className="card" style={{ alignSelf: 'start' }}>
          {mode === 'navigation' && mapOverview.data ? (
            <>
              <div className="card-header">
                <h3>Route planner — Emergency Navigation</h3>
              </div>
              <div className="card-body">
                <RoutePlanner
                  overview={mapOverview.data}
                  onRoutePlanned={setPlannerRoute}
                  onClearRoute={() => setPlannerRoute(null)}
                  onFitRoute={() => setFitNonce((n) => n + 1)}
                />
              </div>
            </>
          ) : (
            <>
              <div className="card-header">
                <h3>{detail?.kind === 'centre' ? 'Relief centre' : detail?.kind === 'warehouse' ? 'Warehouse' : 'Selected entity'}</h3>
              </div>
              <div className="card-body">
                {detailLoading ? (
                  <LoadingSkeleton variant="lines" />
                ) : detailError ? (
                  <div className="error-state"><div className="error-message">{detailError}</div></div>
                ) : detail?.kind === 'centre' ? (
                  <CentreDetail data={detail.data} />
                ) : detail?.kind === 'warehouse' ? (
                  <WarehouseDetailPanel data={detail.data} />
                ) : (
                  <EmptyState message="Select a warehouse, relief centre, vehicle, road or incident marker on the map for details." />
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function CentreDetail({ data }: { data: ReliefCentreDetail }) {
  return (
    <div className="stack-12">
      <div className="spread">
        <strong style={{ fontSize: 15 }}>{data.name}</strong>
        <StatusBadge value={data.priority} className={PRIORITY_CLASS[data.priority]} label={titleCase(data.priority)} />
      </div>
      <div className="muted">{data.district}</div>
      <div className="stack-8">
        <div className="kv-row"><span className="k">Affected population</span><span className="v">{formatNumber(data.affected_population)}</span></div>
        <div className="kv-row">
          <span className="k">Operational status</span>
          <span className="v"><StatusBadge value={data.operational_status} className={OPERATIONAL_STATUS_CLASS[data.operational_status]} /></span>
        </div>
        <div className="kv-row">
          <span className="k">Water shortage</span>
          <span className="v">
            {data.water_shortage ? (
              <StatusBadge value="water_shortage" className="sev-high" label="Reported" />
            ) : (
              <span className="muted">No</span>
            )}
          </span>
        </div>
      </div>
      {data.water_shortage_notes && <div className="muted">{data.water_shortage_notes}</div>}
      <div>
        <div className="section-title" style={{ marginBottom: 8 }}>Stock at centre</div>
        {data.inventory.length === 0 ? (
          <div className="muted">No stock held at this centre yet.</div>
        ) : (
          <div className="stack-8">
            {data.inventory.map((line) => (
              <div className="kv-row" key={line.supply_type}>
                <span className="k">{titleCase(line.supply_type)}</span>
                <span className="v">{formatNumber(line.quantity)} {line.unit}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function WarehouseDetailPanel({ data }: { data: WarehouseDetail }) {
  return (
    <div className="stack-12">
      <div className="spread">
        <strong style={{ fontSize: 15 }}>{data.name}</strong>
        <StatusBadge value={data.operational_status} className={OPERATIONAL_STATUS_CLASS[data.operational_status]} />
      </div>
      <div className="muted">{data.location_name}</div>
      <div>
        <div className="section-title" style={{ marginBottom: 8 }}>Inventory</div>
        {data.inventory.length === 0 ? (
          <EmptyState message="No inventory recorded for this warehouse." />
        ) : (
          <div className="stack-8">
            {data.inventory.map((line) => (
              <div className="kv-row" key={line.id}>
                <span className="k">{titleCase(line.supply_type)}</span>
                <span className="v">
                  {formatNumber(line.available_quantity)} {line.unit} available
                  <span className="muted"> (of {formatNumber(line.quantity)})</span>
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
