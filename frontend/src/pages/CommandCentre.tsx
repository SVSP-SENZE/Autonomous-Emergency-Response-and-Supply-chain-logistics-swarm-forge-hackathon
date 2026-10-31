import { useMemo } from 'react';
import { Link } from 'react-router-dom';
import {
  Activity,
  AlertOctagon,
  Boxes,
  Bot,
  ClipboardList,
  MapPin,
  PackageCheck,
  Truck,
  Users,
} from 'lucide-react';
import { useScenario } from '../hooks/useScenario';
import { useBackendData } from '../hooks/useBackendData';
import { getDashboardSummary } from '../api/dashboard';
import { getDispatchSummary } from '../api/dispatch';
import { getMapOverview } from '../api/resources';
import { listPlanningRuns } from '../api/logistics';
import { listReliefCentres } from '../api/resources';
import { listSimulationEvents } from '../api/simulation';
import { listAgentSessions } from '../api/agent';
import { MetricCard } from '../components/common/MetricCard';
import { StatusBadge } from '../components/common/StatusBadge';
import { EmptyState } from '../components/common/EmptyState';
import { ErrorState } from '../components/common/ErrorState';
import { LoadingSkeleton } from '../components/common/LoadingSkeleton';
import { ProgressBar } from '../components/common/ProgressBar';
import { ResponsePipeline, type PipelineStage } from '../components/common/ResponsePipeline';
import { DisasterMap } from '../components/map/DisasterMap';
import { AIOperationsCopilot } from '../components/copilot/AIOperationsCopilot';
import {
  PRIORITY_CLASS,
  SEVERITY_CLASS,
  formatNumber,
  formatPercent,
  formatTime,
  titleCase,
} from '../utils/format';
import type { DispatchSummaryResponse } from '../types';

export function CommandCentrePage() {
  const scenario = useScenario();
  const dashboard = useBackendData(() => getDashboardSummary(), [], 10000);  const dispatchSummary = useBackendData(() => getDispatchSummary(), [], 10000);
  const mapOverview = useBackendData((signal) => getMapOverview(signal), [], 10000);
  const demandRuns = useBackendData(() => listPlanningRuns('demand', 1), [], 0);
  const allocationRuns = useBackendData(() => listPlanningRuns('allocation', 1), [], 0);
  const recalcRuns = useBackendData(() => listPlanningRuns('route_recalculation', 5), [], 0);
  const centres = useBackendData((signal) => listReliefCentres(signal), [], 30000);
  const simEvents = useBackendData((signal) => listSimulationEvents(50, signal), [], 10000);
  const agentSessions = useBackendData((signal) => listAgentSessions(3, signal), [], 0);

  const kpis = dashboard.data?.summary;
  const inventory = dashboard.data?.inventory ?? [];
  const totalAvailableSupplies = inventory.reduce((sum, item) => sum + item.available_quantity, 0);
  const dispatch = dispatchSummary.data;

  const criticalCentres = useMemo(
    () =>
      (centres.data?.items ?? [])
        .filter((centre) => centre.priority === 'critical' || centre.priority === 'high')
        .sort((a, b) => (a.priority === b.priority ? b.affected_population - a.affected_population : a.priority === 'critical' ? -1 : 1))
        .slice(0, 6),
    [centres.data],
  );

  const recentEvents = useMemo(
    () => [...(simEvents.data?.items ?? [])].reverse().slice(0, 5),
    [simEvents.data],
  );

  const pipelineStages = buildPipelineStages(
    scenario.activeCount,
    demandRuns.data?.items?.length ?? 0,
    allocationRuns.data?.items?.length ?? 0,
    dispatchSummary.data,
    recalcRuns.data?.items?.length ?? 0,
    (dispatchSummary.data?.delayed ?? 0) > 0,
  );

  const primary = scenario.primary;

  return (
    <div className="stack-16">
      {/* Incident banner (real incident record, highest priority first) */}
      <div className="card" style={{ borderLeft: '3px solid var(--accent-red)' }}>
        <div className="card-body">
          {primary ? (
            <>
              <div className="spread" style={{ marginBottom: 10 }}>
                <div className="row-8">
                  <span className="sim-note">
                    <AlertOctagon size={13} /> Simulation active
                  </span>
                  <StatusBadge value={primary.incident_type} className="badge-plain" label={titleCase(primary.incident_type)} />
                  <StatusBadge value={primary.status} className="badge-plain" label={titleCase(primary.status)} />
                </div>
                <span className="muted">Source: {titleCase(primary.source)}</span>
              </div>
              <div className="spread">
                <div>
                  <h2 style={{ fontSize: 20 }}>{primary.title}</h2>
                  <div className="row-12" style={{ marginTop: 8, fontSize: 12.5, color: 'var(--text-secondary)' }}>
                    <span className="row-8" style={{ gap: 5 }}>
                      <MapPin size={13} /> {primary.location_name}
                    </span>
                    <span>{formatNumber(primary.affected_population)} affected</span>
                    <span>Reported {formatTime(primary.created_at)}</span>
                  </div>
                </div>
                <Link to="/incidents" className="btn ghost small">
                  <ClipboardList size={13} /> Incident intelligence
                </Link>
              </div>
            </>
          ) : (
            <EmptyState message="No active incidents recorded in the simulated scenario." />
          )}
        </div>
      </div>

      {/* KPI row */}
      {dashboard.error ? (
        <ErrorState error={dashboard.error} onRetry={dashboard.refresh} title="Dashboard summary failed" />
      ) : dashboard.loading ? (
        <LoadingSkeleton variant="table" />
      ) : kpis ? (
        <div className="metric-row">
          <MetricCard label="Affected population" value={formatNumber(kpis.affected_population)} icon={Users} accent="var(--accent-red)" />
          <MetricCard label="Active incidents" value={kpis.active_disasters} icon={AlertOctagon} accent="var(--accent-orange)" />
          <MetricCard label="Critical centres" value={kpis.critical_centres} icon={MapPin} accent="var(--accent-red)" />
          <MetricCard label="Available vehicles" value={kpis.available_vehicles} sub={`of ${kpis.total_vehicles} total`} icon={Truck} accent="var(--accent-green)" />
          <MetricCard label="Vehicles in transit" value={kpis.vehicles_in_transit} icon={Truck} accent="var(--accent-cyan)" />
          <MetricCard label="Pending orders" value={dispatch?.awaiting_approval ?? 0} sub="awaiting approval" icon={ClipboardList} accent="var(--accent-orange)" />
          <MetricCard label="Supplies available" value={formatNumber(totalAvailableSupplies)} sub={`${kpis.warehouses} warehouses`} icon={Boxes} accent="var(--accent-blue)" />
        </div>
      ) : null}

      {/* Map + copilot */}
      <div className="grid-2-1" style={{ alignItems: 'stretch' }}>
        <div style={{ minHeight: 560 }}>
          {mapOverview.error ? (
            <ErrorState error={mapOverview.error} onRetry={mapOverview.refresh} title="Map data failed to load" />
          ) : (
            <DisasterMap
              overview={mapOverview.data}
              height={560}
              onSelect={() => undefined}
            />
          )}
        </div>
        <div style={{ minHeight: 560 }}>
          <AIOperationsCopilot height={560} />
        </div>
      </div>

      {/* Response pipeline */}
      <div className="card">
        <div className="card-header">
          <Activity size={15} className="header-icon" />
          <h3>End-to-end response pipeline</h3>
          <div className="card-header-right muted">derived from live backend records</div>
        </div>
        <div className="card-body">
          <ResponsePipeline stages={pipelineStages} />
        </div>
      </div>

      <div className="grid-2">
        {/* Dispatch overview */}
        <div className="card">
          <div className="card-header">
            <ClipboardList size={15} className="header-icon" />
            <h3>Dispatch overview</h3>
            <div className="card-header-right">
              <Link to="/dispatch" className="btn ghost small">Open dispatch console</Link>
            </div>
          </div>
          <div className="card-body">
            {dispatch ? (
              <>
                <div className="grid-4" style={{ marginBottom: 14 }}>
                  {(
                    [
                      ['Awaiting approval', dispatch.awaiting_approval, 'var(--accent-orange)'],
                      ['Approved', dispatch.approved, 'var(--accent-blue)'],
                      ['In transit', dispatch.in_transit + dispatch.dispatched, 'var(--accent-cyan)'],
                      ['Delivered', dispatch.delivered, 'var(--accent-green)'],
                    ] as const
                  ).map(([label, value, color]) => (
                    <div key={label} style={{ textAlign: 'center' }}>
                      <div style={{ fontSize: 22, fontWeight: 650, color }}>{value}</div>
                      <div className="muted">{label}</div>
                    </div>
                  ))}
                </div>
                <ProgressBar percent={dispatch.delivery_completion_percent} tone="primary" />
                <div className="muted" style={{ marginTop: 8 }}>
                  Delivery completion {formatPercent(dispatch.delivery_completion_percent)} ·{' '}
                  {formatNumber(dispatch.total_cargo_weight_dispatched_kg, 1)} kg delivered cargo ·{' '}
                  {formatNumber(dispatch.total_inventory_reserved)} units reserved
                </div>
              </>
            ) : (
              <EmptyState message="No dispatch summary available yet." />
            )}
          </div>
        </div>

        {/* Critical centres */}
        <div className="card">
          <div className="card-header">
            <AlertOctagon size={15} className="header-icon" />
            <h3>Critical relief centres</h3>
          </div>
          <div className="card-body">
            {criticalCentres.length === 0 ? (
              <EmptyState message="No critical or high-priority relief centres right now." />
            ) : (
              <div className="table-wrap">
                <table className="op-table">
                  <thead>
                    <tr>
                      <th>Centre</th>
                      <th>District</th>
                      <th>Population</th>
                      <th>Priority</th>
                    </tr>
                  </thead>
                  <tbody>
                    {criticalCentres.map((centre) => (
                      <tr key={centre.id}>
                        <td>{centre.name}</td>
                        <td className="muted">{centre.district}</td>
                        <td className="num">{formatNumber(centre.affected_population)}</td>
                        <td>
                          <StatusBadge
                            value={centre.priority}
                            className={PRIORITY_CLASS[centre.priority]}
                            label={titleCase(centre.priority)}
                          />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="grid-2">
        {/* Recent simulated events */}
        <div className="card">
          <div className="card-header">
            <PackageCheck size={15} className="header-icon" />
            <h3>Recent simulation events</h3>
            <div className="card-header-right">
              <Link to="/simulation" className="btn ghost small">Simulation lab</Link>
            </div>
          </div>
          <div className="card-body">
            {recentEvents.length === 0 ? (
              <EmptyState message="No simulation events yet. Trigger one in the Simulation Lab." />
            ) : (
              <div className="stack-8">
                {recentEvents.map((event) => (
                  <div key={event.id} className="timeline-item" style={{ '--tl-color': 'var(--accent-orange)' } as React.CSSProperties}>
                    <div className="tl-title">
                      {event.title}
                      <StatusBadge value={event.severity} className={SEVERITY_CLASS[event.severity]} />
                      <span className="badge sev-critical" style={{ fontSize: 9 }}>Simulated</span>
                    </div>
                    <div className="tl-meta">{titleCase(event.event_type)} · {formatTime(event.created_at)}</div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Recent agent activity */}
        <div className="card">
          <div className="card-header">
            <Bot size={15} className="header-icon" />
            <h3>Recent AI activity</h3>
            <div className="card-header-right">
              <Link to="/ai" className="btn ghost small">Full history</Link>
            </div>
          </div>
          <div className="card-body">
            {(agentSessions.data?.length ?? 0) === 0 ? (
              <EmptyState message="No AI conversation sessions yet — ask the copilot something." />
            ) : (
              <div className="stack-8">
                {agentSessions.data!.slice(0, 3).map((session) => (
                  <div key={session.session_id} className="kv-row">
                    <span className="k">{session.session_title}</span>
                    <span className="v muted">
                      {session.message_count} msgs · {formatTime(session.updated_at)}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

/** Pipeline state derived STRICTLY from real backend records. */
function buildPipelineStages(
  activeIncidents: number,
  demandRunCount: number,
  allocationRunCount: number,
  dispatch: DispatchSummaryResponse | null,
  recalcRunCount: number,
  hasDelayedVehicles: boolean,
): PipelineStage[] {
  const totalOrders = dispatch?.total_orders ?? 0;
  const delivered = dispatch?.delivered ?? 0;
  const inMotion = (dispatch?.dispatched ?? 0) + (dispatch?.in_transit ?? 0);
  const awaiting = dispatch?.awaiting_approval ?? 0;
  const hasOrders = totalOrders > 0;

  let planState: PipelineStage['state'] = 'not_started';
  let planDetail: string | undefined;
  if (hasOrders && delivered > 0) {
    planState = 'completed';
    planDetail = `${formatNumber(totalOrders)} orders generated`;
  } else if (hasOrders && (inMotion > 0 || (dispatch?.approved ?? 0) > 0)) {
    planState = 'in_progress';
    planDetail = 'Orders in execution';
  } else if (hasOrders) {
    planState = 'needs_approval';
    planDetail = `${formatNumber(awaiting)} awaiting operator`;
  }

  let dispatchState: PipelineStage['state'] = 'not_started';
  let dispatchDetail: string | undefined;
  if (delivered > 0 && inMotion === 0) {
    dispatchState = 'completed';
    dispatchDetail = 'All vehicles idle after delivery';
  } else if (inMotion > 0) {
    dispatchState = 'in_progress';
    dispatchDetail = `${formatNumber(inMotion)} vehicles rolling (simulated)`;
  } else if ((dispatch?.approved ?? 0) > 0) {
    dispatchState = 'needs_approval';
    dispatchDetail = `${formatNumber(dispatch!.approved)} approved · dispatch ready`;
  }

  return [
    {
      key: 'detect',
      label: 'Detect',
      hint: 'Active incident exists in the incident registry',
      state: activeIncidents > 0 ? 'completed' : 'not_started',
      detail: activeIncidents > 0 ? `${formatNumber(activeIncidents)} active incident(s)` : undefined,
      records: [{ label: 'Open incident intelligence', href: '/incidents' }],
    },
    {
      key: 'assess',
      label: 'Assess',
      hint: 'A demand assessment planning run has been persisted',
      state: demandRunCount > 0 ? 'completed' : 'not_started',
      detail:
        demandRunCount > 0
          ? 'Demand assessment recorded'
          : 'Run demand estimation in Logistics Planning',
      records: [{ label: 'Logistics planning', href: '/logistics' }],
    },
    {
      key: 'source',
      label: 'Source',
      hint: 'Warehouse inventory exists and an allocation plan has been computed',
      state: allocationRunCount > 0 ? 'completed' : 'not_started',
      detail:
        allocationRunCount > 0
          ? 'Allocation plan recorded'
          : 'Compute an allocation plan',
      records: [{ label: 'Allocation history', href: '/logistics' }],
    },
    {
      key: 'plan',
      label: 'Plan',
      hint: 'Dispatch orders generated from the allocation plan',
      state: planState,
      detail: planDetail,
      records: [{ label: 'Dispatch operations', href: '/dispatch' }],
    },
    {
      key: 'dispatch',
      label: 'Dispatch',
      hint: 'One or more orders dispatched by the operator',
      state: dispatchState,
      detail: dispatchDetail,
      records: [{ label: 'Dispatch tracking', href: '/dispatch' }],
    },
    {
      key: 'deliver',
      label: 'Deliver',
      hint: 'At least one completed delivery recorded',
      state: delivered > 0 ? 'completed' : 'not_started',
      detail: delivered > 0 ? `${formatNumber(delivered)} deliveries completed` : 'No deliveries yet',
      records: [{ label: 'Delivery records', href: '/dispatch' }],
    },
    {
      key: 'adapt',
      label: 'Adapt',
      hint: 'A disruption produced a recalculated route or a delayed handled delivery',
      state: recalcRunCount > 0 || hasDelayedVehicles ? 'in_progress' : 'not_started',
      detail:
        recalcRunCount > 0
          ? `${formatNumber(recalcRunCount)} route recalculation(s)`
          : hasDelayedVehicles
            ? 'Delayed vehicle under replanning'
            : 'No disruptions recorded',
      records: [{ label: 'Simulation lab (trigger disruption)', href: '/simulation' }],
    },
  ];
}
