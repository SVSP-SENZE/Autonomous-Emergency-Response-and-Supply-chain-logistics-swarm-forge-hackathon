import { useMemo, useState } from 'react';
import { AlertTriangle, MapPin, PackageSearch, Truck } from 'lucide-react';
import { useBackendData } from '../hooks/useBackendData';
import { getMapOverview, getReliefCentreDetail, getWarehouseDetail } from '../api/resources';
import { DisasterMap, type EntitySelection } from '../components/map/DisasterMap';
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

export function DisasterMapPage() {
  const mapOverview = useBackendData((signal) => getMapOverview(signal), [], 10000);
  const [selected, setSelected] = useState<EntitySelection>(null);
  const [detail, setDetail] = useState<Detail>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

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
            <DisasterMap overview={mapOverview.data} height={620} onSelect={loadDetail} selected={selected} />
          )}
        </div>

        <div className="card" style={{ alignSelf: 'start' }}>
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
