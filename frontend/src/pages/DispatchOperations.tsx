import { useEffect, useState } from 'react';
import {
  AlertCircle,
  CheckCircle2,
  ClipboardList,
  Crosshair,
  PackageCheck,
  Send,
  Truck,
  UserCheck,
  XCircle,
} from 'lucide-react';
import { useBackendData } from '../hooks/useBackendData';
import {
  advanceOrder,
  approveOrder,
  assignVehicle,
  cancelOrder,
  confirmOrderRoute,
  deliverOrder,
  dispatchOrder,
  generateDispatchOrders,
  getDispatchOrder,
  getDispatchSummary,
  getFleetOverview,
  getOrderTracking,
  listDispatchEvents,
  listDispatchOrders,
} from '../api/dispatch';
import { listPlanningRuns } from '../api/logistics';
import { getWarehouseDetail } from '../api/resources';
import { ErrorState } from '../components/common/ErrorState';
import { EmptyState } from '../components/common/EmptyState';
import { LoadingSkeleton } from '../components/common/LoadingSkeleton';
import { StatusBadge } from '../components/common/StatusBadge';
import { ConfirmDialog } from '../components/common/ConfirmDialog';
import { ProgressBar } from '../components/common/ProgressBar';
import { useToast } from '../components/common/Toast';
import {
  ORDER_STATUS_CLASS,
  formatDateTime,
  formatKg,
  formatNumber,
  formatPercent,
  formatTime,
  supplyLabel,
  titleCase,
} from '../utils/format';
import type {
  AssignVehicleResponse,
  DispatchOrder,
  DispatchOrderDetail,
  DispatchSummaryResponse,
  TrackingResponse,
} from '../types';

const STATUS_TABS: { value: string; label: string }[] = [
  { value: '', label: 'All' },
  { value: 'draft', label: 'Draft' },
  { value: 'awaiting_approval', label: 'Awaiting approval' },
  { value: 'approved', label: 'Approved' },
  { value: 'dispatched', label: 'Dispatched' },
  { value: 'in_transit', label: 'In transit' },
  { value: 'delayed', label: 'Delayed' },
  { value: 'delivered', label: 'Delivered' },
  { value: 'cancelled', label: 'Cancelled' },
];

export function DispatchOperationsPage() {
  const { push } = useToast();
  const [statusFilter, setStatusFilter] = useState('');
  const [selectedOrderId, setSelectedOrderId] = useState<number | null>(null);

  const summary = useBackendData(() => getDispatchSummary(), [], 10000);
  const fleet = useBackendData(() => getFleetOverview(), [], 10000);
  const allocationRuns = useBackendData(
    (signal) => listPlanningRuns('allocation', 25, signal),
    [],
    60000,
  );
  const orders = useBackendData(
    (signal) =>
      listDispatchOrders({ status: statusFilter || undefined, limit: 200 }, signal),
    [statusFilter],
    10000,
  );
  const events = useBackendData((signal) => listDispatchEvents(undefined, 100, signal), [], 10000);

  // Selected order detail + live tracking
  const detail = useBackendData(
    async (signal) =>
      selectedOrderId === null ? null : getDispatchOrder(selectedOrderId, signal),
    [selectedOrderId],
    0,
  );
  const [tracking, setTracking] = useState<TrackingResponse | null>(null);
  const [trackingBusy, setTrackingBusy] = useState(false);
  const [confirmAction, setConfirmAction] = useState<
    { kind: 'approve' | 'dispatch' | 'deliver' | 'cancel' | 'confirm-route'; label: string } | null
  >(null);
  const [actionBusy, setActionBusy] = useState(false);
  const [assignResult, setAssignResult] = useState<AssignVehicleResponse | null>(null);
  const [warehouseReserved, setWarehouseReserved] = useState<{
    name: string;
    lines: { supply: string; unit: string; quantity: number; reserved: number; available: number }[];
  } | null>(null);

  const selectedOrder: DispatchOrder | null =
    detail.data?.order ?? orders.data?.orders.find((order) => order.id === selectedOrderId) ?? null;

  const loadTracking = async (orderId: number) => {
    setTrackingBusy(true);
    try {
      setTracking(await getOrderTracking(orderId));
    } catch (err) {
      setTracking(null);
      push(err instanceof Error ? err.message : 'Tracking failed', 'error');
    } finally {
      setTrackingBusy(false);
    }
  };

  // Poll tracking for moving orders (3-5s per spec); stop when not moving.
  const isMoving = selectedOrder?.status === 'in_transit' || selectedOrder?.status === 'dispatched' || selectedOrder?.status === 'delayed';
  useEffect(() => {
    if (!isMoving || selectedOrderId === null) return;
    const id = setInterval(() => {
      void getOrderTracking(selectedOrderId)
        .then(setTracking)
        .catch(() => undefined);
    }, 4000);
    return () => clearInterval(id);
  }, [isMoving, selectedOrderId]);

  const describeAction =
    (kind: 'approve' | 'dispatch') =>
    async (orderId: number) => {
      setActionBusy(true);
      try {
        const order = orders.data?.orders.find((o) => o.id === orderId);
        if (order) {
          const warehouse = await getWarehouseDetail(order.warehouse_id);
          setWarehouseReserved({
            name: warehouse.name,
            lines: warehouse.inventory.map((line) => ({
              supply: supplyLabel(line.supply_type),
              unit: line.unit,
              quantity: line.quantity,
              reserved: line.reserved_quantity,
              available: line.available_quantity,
            })),
          });
        }
      } catch {
        setWarehouseReserved(null);
      } finally {
        setActionBusy(false);
      }
      setConfirmAction(
        kind === 'approve' ? { kind: 'approve', label: 'APPROVE ORDER' } : { kind: 'dispatch', label: 'DISPATCH VEHICLE' },
      );
    };

  const [planRunId, setPlanRunIdValue] = useState('');
  const [generateConfirm, setGenerateConfirm] = useState(false);
  const [generating, setGenerating] = useState(false);

  const generate = async () => {
    if (!planRunId) {
      push('Select an allocation planning run first.', 'error');
      return;
    }
    setGenerating(true);
    try {
      const result = await generateDispatchOrders(Number(planRunId));
      orders.refresh();
      summary.refresh();
      push(
        `${result.generated.length} order(s) created, ${result.existing.length} already existed, ${result.skipped.length} skipped.`
        + `${result.skipped.length > 0 ? ' Skips: ' + result.skipped.map((skip) => `${skip.relief_centre_name}: ${skip.reason}`).join('; ') : ''}`,
        result.generated.length > 0 ? 'success' : 'info',
      );
    } catch (err) {
      push(err instanceof Error ? err.message : 'Order generation failed', 'error');
    } finally {
      setGenerating(false);
      setGenerateConfirm(false);
    }
  };

  const assign = async (orderId: number, vehicleId: number | null) => {
    setActionBusy(true);
    try {
      const result = await assignVehicle(orderId, vehicleId);
      setAssignResult(result);
      orders.refresh();
      summary.refresh();
      fleet.refresh();
      detail.refresh();
      push(
        result.assigned
          ? `${result.vehicle?.vehicle_code ?? 'Vehicle'} assigned to ${result.order_code}${result.auto_selected ? ' (auto-selected: minimal wastage)' : ''}.`
          : result.reason ?? 'No suitable vehicle available.',
        result.assigned ? 'success' : 'error',
      );
    } catch (err) {
      push(err instanceof Error ? err.message : 'Assignment failed', 'error');
    } finally {
      setActionBusy(false);
    }
  };

  const runAction = async () => {
    if (!confirmAction || selectedOrder === null) return;
    const orderId = selectedOrder.id;
    setActionBusy(true);
    try {
      switch (confirmAction.kind) {
        case 'approve': {
          await approveOrder(orderId);
          push(`Order ${selectedOrder.order_code} approved — inventory reserved at the source warehouse.`, 'success');
          setConfirmAction(null);
          detail.refresh();
          orders.refresh();
          summary.refresh();
          fleet.refresh();
          void refreshWarehousePanel(orderId);
          return;
        }
        case 'dispatch': {
          await dispatchOrder(orderId);
          push(`Vehicle dispatched for ${selectedOrder.order_code} — stock deducted from the warehouse (simulated).`, 'success');
          break;
        }
        case 'deliver': {
          await deliverOrder(orderId);
          push(`Delivery completed for ${selectedOrder.order_code} — relief-centre stock increased, vehicle released.`, 'success');
          break;
        }
        case 'cancel': {
          await cancelOrder(orderId);
          push(`Order ${selectedOrder.order_code} cancelled; releases applied per backend validation.`, 'info');
          break;
        }
        case 'confirm-route': {
          const result = await confirmOrderRoute(orderId);
          push(result.route_updated ? 'Route confirmed after disruption.' : result.message, 'info');
          break;
        }
      }
      detail.refresh();
      orders.refresh();
      summary.refresh();
      fleet.refresh();
      setConfirmAction(null);
    } catch (err) {
      push(err instanceof Error ? err.message : 'Action failed', 'error');
    } finally {
      setActionBusy(false);
    }
  };

  const refreshWarehousePanel = async (orderId: number) => {
    const order = orders.data?.orders.find((o) => o.id === orderId);
    if (!order) return;
    try {
      const warehouse = await getWarehouseDetail(order.warehouse_id);
      setWarehouseReserved({
        name: warehouse.name,
        lines: warehouse.inventory.map((line) => ({
          supply: supplyLabel(line.supply_type),
          unit: line.unit,
          quantity: line.quantity,
          reserved: line.reserved_quantity,
          available: line.available_quantity,
        })),
      });
    } catch {
      setWarehouseReserved(null);
    }
  };

  return (
    <div className="stack-16">
      <SummaryStrip summary={summary} />

      {/* Generation + order table */}
      <div className="card">
        <div className="card-header">
          <ClipboardList size={15} className="header-icon" />
          <h3>Dispatch orders</h3>
          <div className="card-header-right row-8">
            <select
              value={planRunId}
              onChange={(e) => setPlanRunIdValue(e.target.value)}
              aria-label="Allocation planning run"
              style={{ width: 'auto', fontSize: 12 }}
            >
              <option value="">Allocation run…</option>
              {(allocationRuns.data?.items ?? []).map((run) => (
                <option key={run.id} value={run.id}>
                  Run #{run.id} · {run.planning_horizon_hours ? `${run.planning_horizon_hours}h` : 'full'} · {formatDateTime(run.created_at)}
                </option>
              ))}
            </select>
            <button className="btn primary small" disabled={generating || !planRunId} onClick={() => setGenerateConfirm(true)}>
              <Send size={13} /> Generate dispatch orders
            </button>
          </div>
        </div>

        <div className="card-body">
          <div className="filter-row" style={{ marginBottom: 12 }}>
            {STATUS_TABS.map((tab) => (
              <button
                key={tab.value}
                className={`btn small ${statusFilter === tab.value ? 'primary' : 'ghost'}`}
                onClick={() => setStatusFilter(tab.value)}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {orders.error ? (
            <ErrorState error={orders.error} onRetry={orders.refresh} />
          ) : orders.loading ? (
            <LoadingSkeleton variant="table" />
          ) : (orders.data?.orders.length ?? 0) === 0 ? (
            <EmptyState message="No dispatch orders match this filter. Generate orders from a persisted allocation run above." />
          ) : (
            <OrderTable
              orders={orders.data!.orders}
              selectedId={selectedOrderId}
              onSelect={(id) => {
                setSelectedOrderId(id);
                setAssignResult(null);
                setTracking(null);
                void loadTracking(id);
                void refreshWarehousePanel(id);
              }}
            />
          )}
        </div>
      </div>

      <div className="grid-2-1">
        {/* Order detail */}
        <div className="card">
          <div className="card-header">
            <h3>{selectedOrder ? `Order ${selectedOrder.order_code}` : 'Order detail'}</h3>
            <div className="card-header-right">
              {selectedOrder && (
                <StatusBadge value={selectedOrder.status} className={ORDER_STATUS_CLASS[selectedOrder.status]} />
              )}
            </div>
          </div>
          <div className="card-body">
            {!selectedOrder ? (
              <EmptyState message="Select an order row above to operate on it." />
            ) : (
              <OrderDetails
                detail={detail.data}
                selectedOrder={selectedOrder}
                warehouseReserved={warehouseReserved}
                tracking={tracking}
                trackingBusy={trackingBusy}
                assignResult={assignResult}
                actionBusy={actionBusy}
                onAssign={(vehicleId) => void assign(selectedOrder.id, vehicleId)}
                onOpenAction={(kind) => {
                  if (kind === 'approve') void describeAction('approve')(selectedOrder.id);
                  else if (kind === 'dispatch') void describeAction('dispatch')(selectedOrder.id);
                  else
                    setConfirmAction({
                      kind,
                      label:
                        kind === 'deliver'
                          ? 'MARK DELIVERED'
                          : kind === 'cancel'
                            ? 'CANCEL ORDER'
                            : 'CONFIRM RECALCULATED ROUTE',
                    });
                }}
                onAdvance={(minutes) => void advanceNow(minutes)}
                onRefreshWarehouse={() => void refreshWarehousePanel(selectedOrder.id)}
                detailBusy={detail.loading}
              />
            )}
          </div>
        </div>

        {/* Event log */}
        <div className="card">
          <div className="card-header">
            <h3>Dispatch event history (append-only)</h3>
          </div>
          <div className="card-body">
            {events.error ? (
              <ErrorState error={events.error} onRetry={events.refresh} />
            ) : events.loading ? (
              <LoadingSkeleton variant="lines" />
            ) : (events.data?.events.length ?? 0) === 0 ? (
              <EmptyState message="No dispatch events recorded yet." />
            ) : (
              <div className="stack-8" style={{ maxHeight: 420, overflowY: 'auto' }}>
                {[...events.data!.events].reverse().slice(0, 25).map((event) => (
                  <div
                    key={event.id}
                    className="timeline-item"
                    style={{ '--tl-color': event.new_status === 'delivered' ? 'var(--accent-green)' : 'var(--accent-blue)' } as React.CSSProperties}
                  >
                    <div className="tl-title">
                      {titleCase(event.event_type)}
                      {event.new_status && (
                        <span className={`badge ${ORDER_STATUS_CLASS[event.new_status as keyof typeof ORDER_STATUS_CLASS] ?? 'badge-plain'}`}>
                          {titleCase(event.new_status)}
                        </span>
                      )}
                    </div>
                    <div className="tl-meta">
                      Order #{event.relief_order_id} · {formatDateTime(event.created_at)}
                    </div>
                    {event.description && <div className="tl-desc">{event.description}</div>}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      <GenerateConfirmDialog
        open={generateConfirm}
        busy={generating}
        planRunId={planRunId}
        onConfirm={() => void generate()}
        onCancel={() => setGenerateConfirm(false)}
      />
      <ConfirmDialog
        open={confirmAction !== null}
        title={confirmAction?.label ?? ''}
        body={
          confirmAction?.kind === 'cancel'
            ? 'The backend decides what is releaseable based on the current lifecycle stage. Cancelled orders cannot be restored.'
            : confirmAction?.kind === 'approve'
              ? 'Approving reserves inventory atomically at the source warehouse (all-or-nothing).'
              : confirmAction?.kind === 'dispatch'
                ? 'Dispatching deducts the reserved stock exactly once and the vehicle departs. This cannot be undone.'
                : confirmAction?.kind === 'deliver'
                  ? 'Only permitted when the backend confirms arrival. Adds stock to the relief centre and releases the vehicle.'
                  : 'Replaces the stored route with the currently computed safe route. Planning-stage orders only; approval stays disabled while the stored route is blocked.'
        }
        confirmLabel={confirmAction?.label ?? 'Confirm'}
        busy={actionBusy}
        onConfirm={() => void runAction()}
        onCancel={() => {
          setConfirmAction(null);
          setWarehouseReserved(null);
        }}
      />
    </div>
  );

  async function advanceNow(minutes: number | undefined) {
    if (selectedOrderId === null) return;
    setTrackingBusy(true);
    try {
      setTracking(await advanceOrder(selectedOrderId, minutes));
      detail.refresh();
      orders.refresh();
    } catch (err) {
      push(err instanceof Error ? err.message : 'Advance failed', 'error');
    } finally {
      setTrackingBusy(false);
    }
  }
}

// ------------------------------------------------------------------ sub-components

type SummaryState = ReturnType<typeof useBackendData<DispatchSummaryResponse>>;

function SummaryStrip({ summary }: { summary: SummaryState }) {
  const data = summary.data;
  const tiles: [string, number | undefined, string][] = data
    ? [
        ['Total orders', data.total_orders, 'var(--accent-blue)'],
        ['Awaiting approval', data.awaiting_approval, 'var(--accent-orange)'],
        ['Approved', data.approved, 'var(--accent-blue)'],
        ['Dispatched', data.dispatched, 'var(--accent-blue)'],
        ['In transit', data.in_transit, 'var(--accent-cyan)'],
        ['Delivered', data.delivered, 'var(--accent-green)'],
        ['Delayed', data.delayed, 'var(--accent-orange)'],
        ['Cancelled', data.cancelled, 'var(--text-muted)'],
        ['Available vehicles', data.vehicles_available, 'var(--accent-green)'],
        ['Assigned vehicles', data.vehicles_assigned, 'var(--accent-blue)'],
      ]
    : [];
  return (
    <div className="metric-row">
      {tiles.map(([label, value, color]) => (
        <div key={label} className="metric-card" style={{ '--metric-accent': color } as React.CSSProperties}>
          <div className="metric-label">{label}</div>
          <div className="metric-value" style={{ fontSize: 21 }}>{value ?? '···'}</div>
        </div>
      ))}
      {data && (
        <div className="metric-card" style={{ '--metric-accent': 'var(--accent-cyan)' } as React.CSSProperties}>
          <div className="metric-label">Reserved inventory</div>
          <div className="metric-value" style={{ fontSize: 21 }}>{formatNumber(data.total_inventory_reserved)}</div>
          <div className="metric-sub">{formatKg(data.total_cargo_weight_dispatched_kg)} cargo delivered</div>
        </div>
      )}
    </div>
  );
}

function OrderTable({
  orders,
  selectedId,
  onSelect,
}: {
  orders: DispatchOrder[];
  selectedId: number | null;
  onSelect: (id: number) => void;
}) {
  return (
    <div className="table-wrap">
      <table className="op-table">
        <thead>
          <tr>
            <th>Order code</th>
            <th>Status</th>
            <th>Priority</th>
            <th>Cargo</th>
            <th>Route progress</th>
            <th>Vehicle</th>
            <th>Created</th>
          </tr>
        </thead>
        <tbody>
          {orders.map((order) => (
            <tr
              key={order.id}
              className="clickable"
              onClick={() => onSelect(order.id)}
              style={selectedId === order.id ? { background: 'rgba(49,154,255,0.08)' } : undefined}
            >
              <td style={{ fontWeight: selectedId === order.id ? 650 : 400 }}>{order.order_code}</td>
              <td><StatusBadge value={order.status} className={ORDER_STATUS_CLASS[order.status]} /></td>
              <td><span className="badge badge-plain">{titleCase(order.priority)}</span></td>
              <td className="num">{formatKg(order.total_cargo_weight_kg)}</td>
              <td style={{ minWidth: 110 }}>
                {order.status === 'dispatched' || order.status === 'in_transit' || order.status === 'delayed' ? (
                  <ProgressBar percent={order.progress_percent} showLabel={false} />
                ) : (
                  <span className="muted">—</span>
                )}
              </td>
              <td>{order.vehicle_id ? `#${order.vehicle_id}` : <span className="muted">unassigned</span>}</td>
              <td className="muted">{formatDateTime(order.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function GenerateConfirmDialog({
  open,
  busy,
  planRunId,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  busy: boolean;
  planRunId: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <ConfirmDialog
      open={open}
      title="Generate dispatch orders?"
      body={`Creates one draft order per (warehouse, destination) pair from persisted allocation run #${planRunId}. Generation is idempotent — repeats do not duplicate; unreachable or oversized pairs are skipped or rejected by the backend.`}
      bullets={[
        'Draft orders sit at status awaiting approval until an operator acts.',
        'No inventory is reserved and no vehicle moves during generation.',
      ]}
      confirmLabel="Generate orders"
      busy={busy}
      onConfirm={onConfirm}
      onCancel={onCancel}
    />
  );
}

function OrderDetails({
  selectedOrder,
  detail,
  warehouseReserved,
  tracking,
  trackingBusy,
  assignResult,
  actionBusy,
  detailBusy,
  onAssign,
  onOpenAction,
  onAdvance,
  onRefreshWarehouse,
}: {
  selectedOrder: DispatchOrder;
  detail: DispatchOrderDetail | null;
  warehouseReserved: {
    name: string;
    lines: { supply: string; unit: string; quantity: number; reserved: number; available: number }[];
  } | null;
  tracking: TrackingResponse | null;
  trackingBusy: boolean;
  assignResult: AssignVehicleResponse | null;
  actionBusy: boolean;
  detailBusy: boolean;
  onAssign: (vehicleId: number | null) => void;
  onOpenAction: (kind: 'approve' | 'dispatch' | 'deliver' | 'cancel' | 'confirm-route') => void;
  onAdvance: (minutes?: number) => void;
  onRefreshWarehouse: () => void;
}) {
  const status = selectedOrder.status;
  const canAssign = status === 'draft' || status === 'awaiting_approval';
  const canApprove = status === 'awaiting_approval' || status === 'draft';
  const canDispatch = status === 'approved';
  const canTrack = status === 'dispatched' || status === 'in_transit' || status === 'delayed';
  const canDeliver = status === 'in_transit' || status === 'dispatched';
  const canCancel = status === 'draft' || status === 'awaiting_approval' || status === 'approved';
  const canConfirmRoute = status === 'draft' || status === 'awaiting_approval';

  if (detailBusy && !detail) {
    return <LoadingSkeleton variant="table" />;
  }

  return (
    <div className="stack-12">
      {detail && (
        <div className="row-12" style={{ fontSize: 12.5 }}>
          <span>{detail.warehouse_name} → {detail.relief_centre_name}</span>
          {detail.vehicle && (
            <span>
              <Truck size={13} /> {detail.vehicle.vehicle_code} · cap {formatNumber(detail.vehicle.capacity_kg ?? detail.vehicle.capacity)} kg
            </span>
          )}
          {!detail.vehicle && <span className="muted">No vehicle assigned</span>}
        </div>
      )}

      <div className="grid-4">
        <div className="card card-body" style={{ padding: 10 }}>
          <div className="metric-label">Cargo</div>
          <div style={{ fontSize: 17, fontWeight: 650 }}>{formatKg(selectedOrder.total_cargo_weight_kg)}</div>
          {selectedOrder.items.map((item) => (
            <div className="muted" key={item.id}>
              {formatNumber(item.quantity)} {item.unit} · {supplyLabel(item.supply_type)}
            </div>
          ))}
        </div>
        <div className="card card-body" style={{ padding: 10 }}>
          <div className="metric-label">Est. travel time</div>
          <div style={{ fontSize: 17, fontWeight: 650 }}>{selectedOrder.estimated_travel_time_minutes} min</div>
          {selectedOrder.actual_travel_time_minutes !== null && (
            <div className="muted">actual {selectedOrder.actual_travel_time_minutes} min</div>
          )}
        </div>
        <div className="card card-body" style={{ padding: 10 }}>
          <div className="metric-label">Route progress</div>
          <div style={{ fontSize: 17, fontWeight: 650 }}>{formatPercent(selectedOrder.progress_percent)}</div>
          <div className="muted">simulated position only</div>
        </div>
        <div className="card card-body" style={{ padding: 10 }}>
          <div className="metric-label">Lifecycle</div>
          <div className="muted" style={{ lineHeight: 1.6 }}>
            {selectedOrder.approved_at && <>Approved {formatTime(selectedOrder.approved_at)}<br /></>}
            {selectedOrder.dispatched_at && <>Dispatched {formatTime(selectedOrder.dispatched_at)}<br /></>}
            {selectedOrder.delivered_at && <>Delivered {formatTime(selectedOrder.delivered_at)}</>}
            {!selectedOrder.delivered_at && !selectedOrder.dispatched_at && <span>Not dispatched yet</span>}
          </div>
        </div>
      </div>

      {/* Operator actions */}
      <div className="row-8">
        <button className="btn primary small" disabled={!canAssign || actionBusy} title={canAssign ? 'Auto-select the vehicle with minimal cargo wastage' : 'Not permitted at this stage'} onClick={() => onAssign(null)}>
          <UserCheck size={13} /> Auto-assign vehicle
        </button>
        <button className="btn success small" disabled={!canApprove || actionBusy} onClick={() => onOpenAction('approve')}>
          <CheckCircle2 size={13} /> Approve order
        </button>
        <button className="btn primary small" disabled={!canDispatch || actionBusy} onClick={() => onOpenAction('dispatch')}>
          <Send size={13} /> Dispatch vehicle
        </button>
        <button className="btn small" disabled={!canTrack || trackingBusy} onClick={() => onAdvance(undefined)}>
          <Crosshair size={13} /> Advance simulation
        </button>
        <button className="btn success small" disabled={!canDeliver || actionBusy} onClick={() => onOpenAction('deliver')}>
          <PackageCheck size={13} /> Mark delivered
        </button>
        {canConfirmRoute && (
          <button className="btn small" disabled={actionBusy} title="Planning-stage order whose stored route may have been disrupted — replaces it with the currently safe route" onClick={() => onOpenAction('confirm-route')}>
            <AlertCircle size={13} /> Confirm recalculated route
          </button>
        )}
        <button className="btn danger small" disabled={!canCancel || actionBusy} title={canCancel ? undefined : 'Backend prohibits cancelling dispatched, in-transit or delivered orders'} onClick={() => onOpenAction('cancel')}>
          <XCircle size={13} /> Cancel
        </button>
        <button className="btn ghost small" onClick={onRefreshWarehouse}>Refresh warehouse view</button>
      </div>
      {!canAssign && !canApprove && !canDispatch && !canDeliver && (
        <div className="muted">
          Terminal order state ({titleCase(status)}) — actions are disabled accordingly.
        </div>
      )}

      {assignResult && (
        <div className="card card-body" style={{ padding: 10 }}>
          <div className="section-title" style={{ marginBottom: 6 }}>Assignment review</div>
          {assignResult.assigned ? (
            <>
              <div className="muted">
                {assignResult.auto_selected ? 'Auto selection (minimal wastage): ' : 'Manual assignment: '}
                <strong>{assignResult.vehicle?.vehicle_code}</strong> carrying {formatKg(assignResult.cargo_weight_kg)} of{' '}
                {formatNumber(assignResult.vehicle?.capacity_kg ?? 0)} kg capacity
                {assignResult.previous_vehicle_id ? ` · replaced vehicle #${assignResult.previous_vehicle_id}` : ''}
              </div>
              <div className="table-wrap" style={{ marginTop: 6 }}>
                <table className="op-table">
                  <thead>
                    <tr><th>Candidate</th><th>Capacity</th><th>Wastage</th></tr>
                  </thead>
                  <tbody>
                    {assignResult.candidates_considered.map((candidate) => (
                      <tr key={candidate.vehicle_id}>
                        <td>{candidate.vehicle_code} {candidate.vehicle_id === assignResult.vehicle?.id ? '· chosen' : ''}</td>
                        <td className="num">{formatNumber(candidate.capacity_kg)} kg</td>
                        <td className="num">{formatNumber(candidate.capacity_kg - candidate.cargo_weight_kg)} kg</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : (
            <div style={{ color: 'var(--accent-orange)' }}>
              No vehicle assigned. {assignResult.reason ?? 'No candidate vehicle has enough free capacity for this cargo.'}
            </div>
          )}
        </div>
      )}

      {/* Simulated tracking */}
      {(canTrack || tracking) && (
        <div className="card card-body" style={{ padding: 10 }}>
          <div className="spread">
            <div className="section-title">
              <Crosshair size={13} /> Simulated tracking
            </div>
            {tracking?.delayed && <span className="badge sev-high">Delayed</span>}
          </div>
          {tracking ? (
            <div className="stack-8">
              <ProgressBar
                percent={tracking.progress_percent}
                tone={tracking.delayed ? 'warn' : 'primary'}
              />
              <div className="row-12 muted">
                <span>Vehicle {tracking.vehicle_code ?? '—'}</span>
                <span>{formatNumber(tracking.progress_km, 1)} of {formatNumber(tracking.total_distance_km, 1)} km</span>
                <span>
                  ~{tracking.remaining_travel_time_minutes} min remaining (simulated)
                </span>
                {tracking.current_node_name && <span>At: {tracking.current_node_name}</span>}
              </div>
              <div className="table-wrap">
                <table className="op-table">
                  <thead>
                    <tr><th>Segment</th><th>Distance</th><th>Time</th><th>Risk</th><th>Traversed</th></tr>
                  </thead>
                  <tbody>
                    {tracking.segments.map((segment) => (
                      <tr key={segment.segment_id}>
                        <td>{segment.from_node_name} → {segment.to_node_name}</td>
                        <td className="num">{formatNumber(segment.distance_km, 1)} km</td>
                        <td className="num">{segment.estimated_travel_time_minutes} min</td>
                        <td className="num">{segment.risk_factor.toFixed(2)}</td>
                        <td>{segment.traversed ? <CheckCircle2 size={13} style={{ color: 'var(--accent-green)' }} /> : '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : (
            <div className="muted">Press “Advance simulation” to step the simulated vehicle along its route.</div>
          )}
        </div>
      )}

      {/* Warehouse availability at approval/dispatch */}
      {warehouseReserved && (
        <div className="card card-body" style={{ padding: 10 }}>
          <div className="section-title" style={{ marginBottom: 6 }}>
            Warehouse availability — {warehouseReserved.name}
          </div>
          <div className="table-wrap">
            <table className="op-table">
              <thead>
                <tr><th>Supply</th><th>Stock</th><th>Reserved</th><th>Available</th></tr>
              </thead>
              <tbody>
                {warehouseReserved.lines.map((line) => (
                  <tr key={line.supply}>
                    <td>{line.supply}</td>
                    <td className="num">{formatNumber(line.quantity)} {line.unit}</td>
                    <td className="num">{formatNumber(line.reserved)} {line.unit}</td>
                    <td className={`num ${line.available === 0 ? 'negative-value' : 'positive-value'}`}>
                      {formatNumber(line.available)} {line.unit}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="muted" style={{ marginTop: 6 }}>
            Approval reserves stock atomically; the backend is the final authority if availability is insufficient
            (error code inventory_insufficient_stock).
          </div>
        </div>
      )}

      {/* Route + movements from detail */}
      {detail && (
        <div className="grid-2">
          <div>
            <div className="section-title" style={{ marginBottom: 6 }}>Route snapshot</div>
            <RouteSummaryBlock detail={detail} />
          </div>
          <div>
            <div className="section-title" style={{ marginBottom: 6 }}>Inventory movements</div>
            {detail.inventory_movements.length === 0 ? (
              <div className="muted">No inventory movements yet.</div>
            ) : (
              <div className="stack-8">
                {detail.inventory_movements.map((movement) => (
                  <div className="kv-row" key={movement.id}>
                    <span className="k">{titleCase(movement.movement_type)} · {supplyLabel(movement.supply_type)}</span>
                    <span className="v">
                      {formatNumber(movement.quantity)} · {formatTime(movement.created_at)}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Events for this order */}
      {detail && detail.events.length > 0 && (
        <div>
          <div className="section-title" style={{ marginBottom: 6 }}>Order events</div>
          <div className="stack-8">
            {[...detail.events].reverse().slice(0, 8).map((event) => (
              <div
                key={event.id}
                className="timeline-item"
                style={{ '--tl-color': 'var(--accent-blue)' } as React.CSSProperties}
              >
                <div className="tl-title">{titleCase(event.event_type)}</div>
                <div className="tl-meta">{formatDateTime(event.created_at)}</div>
                {event.description && <div className="tl-desc">{event.description}</div>}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function RouteSummaryBlock({ detail }: { detail: DispatchOrderDetail }) {
  const route = detail.route as
    | {
        reachable?: boolean;
        distance_km?: number;
        estimated_travel_time_minutes?: number;
        route_risk?: number;
        route_node_names?: string[];
      }
    | undefined;
  if (!route || Object.keys(route).length === 0) {
    return <div className="muted">No route snapshot stored on this order yet.</div>;
  }
  return (
    <div className="stack-8">
      <div className="kv-row">
        <span className="k">Reachable</span>
        <span className="v">{route.reachable ? 'yes' : 'no'}</span>
      </div>
      <div className="kv-row">
        <span className="k">Distance / time</span>
        <span className="v">
          {formatNumber(route.distance_km ?? 0, 1)} km · {route.estimated_travel_time_minutes ?? 0} min
        </span>
      </div>
      <div className="kv-row">
        <span className="k">Route risk</span>
        <span className="v">{(route.route_risk ?? 0).toFixed(2)}</span>
      </div>
      {route.route_node_names && (
        <div className="muted">{route.route_node_names.join(' → ')}</div>
      )}
    </div>
  );
}

