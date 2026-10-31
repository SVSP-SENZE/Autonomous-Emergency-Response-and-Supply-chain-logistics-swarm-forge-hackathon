import { useState } from 'react';
import {
  FlaskConical,
  RotateCcw,
  Zap,
  Download,
} from 'lucide-react';
import { useBackendData } from '../hooks/useBackendData';
import {
  applySimulationEvent,
  listSimulationEvents,
  resetSimulation,
} from '../api/simulation';
import { listIncidents } from '../api/incidents';
import { getMapOverview } from '../api/resources';
import { ErrorState } from '../components/common/ErrorState';
import { EmptyState } from '../components/common/EmptyState';
import { LoadingSkeleton } from '../components/common/LoadingSkeleton';
import { StatusBadge } from '../components/common/StatusBadge';
import { ConfirmDialog } from '../components/common/ConfirmDialog';
import { useToast } from '../components/common/Toast';
import { SEVERITY_CLASS, formatDateTime, titleCase } from '../utils/format';
import type {
  MapOverviewResponse,
  Severity,
  SimulationEventCreatePayload,
  SimulationEventResult,
  SimulationEventType,
} from '../types';

interface EventSpec {
  type: SimulationEventType;
  label: string;
  icon: string;
  impact: string;
  /** Which target selector to render. */
  target: 'road' | 'road_blocked' | 'warehouse' | 'centre' | 'vehicle' | 'incident' | 'flood';
}

const EVENT_SPECS: EventSpec[] = [
  {
    type: 'bridge_collapse',
    label: 'Bridge collapse',
    icon: '⚠',
    impact: 'Blocks the selected road segment (permanent blockage). Vehicles in transit on affected routes get delayed and route recalculation becomes available.',
    target: 'road',
  },
  {
    type: 'road_blocked',
    label: 'Road blockage',
    icon: '⛔',
    impact: 'Blocks the selected road segment with a reason. Orders in transit whose route includes this segment are flagged delayed.',
    target: 'road_blocked',
  },
  {
    type: 'warehouse_unavailable',
    label: 'Warehouse unavailable',
    icon: '🏭',
    impact: 'Marks the warehouse non-operational; freight planning excludes it as a source while the status lasts.',
    target: 'warehouse',
  },
  {
    type: 'relief_centre_water_shortage',
    label: 'Centre water shortage',
    icon: '💧',
    impact: 'Water demand at the selected relief centre escalates and its urgency increases in the next demand assessment.',
    target: 'centre',
  },
  {
    type: 'new_flood_report',
    label: 'New flood report',
    icon: '🌊',
    impact: 'Creates a real incident row (new demand signal). Location coordinates are copied from an existing map node — never invented.',
    target: 'flood',
  },
  {
    type: 'rainfall_escalation',
    label: 'Rainfall escalation',
    icon: '🌧',
    impact: 'Escalates an existing incident: severity and affected population increase, triggering extra demand.',
    target: 'incident',
  },
  {
    type: 'vehicle_breakdown',
    label: 'Vehicle breakdown',
    icon: '🔧',
    impact: 'Removes the vehicle from the available pool; if it is on an active order the backend decides the consequence.',
    target: 'vehicle',
  },
];

export function SimulationLabPage() {
  const { push } = useToast();
  const [spec, setSpec] = useState<EventSpec>(EVENT_SPECS[0]);
  const [targetId, setTargetId] = useState('');
  const [reason, setReason] = useState('');
  const [floodTitle, setFloodTitle] = useState('');
  const [floodPopulation, setFloodPopulation] = useState('');
  const [severity, setSeverity] = useState('');

  const events = useBackendData((signal) => listSimulationEvents(100, signal), [], 10000);
  const overview = useBackendData((signal) => getMapOverview(signal), [], 30000);
  const incidents = useBackendData((signal) => listIncidents({}, signal), [], 30000);

  const [busy, setBusy] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [result, setResult] = useState<SimulationEventResult | null>(null);
  const [resetOpen, setResetOpen] = useState(false);
  const [resetting, setResetting] = useState(false);

  const payload: SimulationEventCreatePayload | null = buildPayload(
    spec,
    targetId,
    reason,
    floodTitle,
    floodPopulation,
    severity,
    overview.data,
  );

  const isReady = (() => {
    if (!payload) return false;
    if (spec.target === 'road' || spec.target === 'road_blocked') return targetId !== '';
    if (spec.target === 'warehouse' || spec.target === 'centre' || spec.target === 'vehicle' || spec.target === 'incident') {
      return targetId !== '';
    }
    if (spec.target === 'flood') return targetId !== '' && floodTitle.trim() !== '';
    return false;
  })();

  const apply = async () => {
    if (!payload) return;
    setBusy(true);
    try {
      const outcome = await applySimulationEvent(payload);
      setResult(outcome);
      events.refresh();
      overview.refresh();
      incidents.refresh();
      push(outcome.message, 'success');
    } catch (err) {
      push(err instanceof Error ? err.message : 'Event application failed', 'error');
    } finally {
      setBusy(false);
      setConfirmOpen(false);
    }
  };

  const doReset = async () => {
    setResetting(true);
    try {
      const response = await resetSimulation();
      setResult(null);
      events.refresh();
      push(
        `${response.message} Reset counts: ${Object.entries(response.counts).map(([k, v]) => `${k}=${v}`).join(', ')}`,
        'success',
      );
    } catch (err) {
      push(err instanceof Error ? err.message : 'Reset failed', 'error');
    } finally {
      setResetting(false);
      setResetOpen(false);
    }
  };

  return (
    <div className="stack-16">
      <div className="callout warn" role="note">
        <strong>SIMULATED environment.</strong> Every action on this page writes auditable demo data through the
        backend's simulation endpoints. Nothing here represents real-world events.
      </div>

      <div className="grid-2-1" style={{ alignItems: 'stretch' }}>
        {/* Event launcher */}
        <div className="card">
          <div className="card-header">
            <FlaskConical size={15} className="header-icon" />
            <h3>Inject simulated event</h3>
            <div className="card-header-right">
              <button
                className="btn small ghost"
                onClick={() => setResetOpen(true)}
                title="Restore the initial seeded demo scenario"
              >
                <RotateCcw size={13} /> Reset scenario
              </button>
            </div>
          </div>
          <div className="card-body">
            <div className="filter-row" style={{ marginBottom: 12 }}>
              {EVENT_SPECS.map((candidate) => (
                <button
                  key={candidate.type}
                  className={`btn small ${spec.type === candidate.type ? 'primary' : 'ghost'}`}
                  onClick={() => {
                    setSpec(candidate);
                    setTargetId('');
                    setReason('');
                    setFloodTitle('');
                    setFloodPopulation('');
                    setSeverity('');
                    setResult(null);
                  }}
                >
                  {candidate.icon} {candidate.label}
                </button>
              ))}
            </div>

            <div className="stack-10">
              {/* Target selector per event type */}
              {spec.target === 'road' || spec.target === 'road_blocked' ? (
                <label className="field-label" id="sim-target-label">
                  Road segment
                  <select value={targetId} onChange={(e) => setTargetId(e.target.value)}>
                    <option value="">Select a segment…</option>
                    {(overview.data?.road_segments ?? []).map((segment) => (
                      <option key={segment.id} value={segment.id} disabled={segment.is_blocked}>
                        #{segment.id} · {segment.from_node_name} → {segment.to_node_name}
                        {segment.is_blocked ? ' (already blocked)' : ''} · {segment.distance_km} km
                      </option>
                    ))}
                  </select>
                </label>
              ) : null}
              {(spec.target === 'road' || spec.target === 'road_blocked') && (
                <label className="field-label">
                  Blockage reason (optional)
                  <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder={spec.target === 'road' ? 'Bridge suffered structural collapse' : 'Road impassable due to flooding'} />
                </label>
              )}

              {spec.target === 'warehouse' && (
                <label className="field-label">
                  Warehouse to take offline
                  <select value={targetId} onChange={(e) => setTargetId(e.target.value)}>
                    <option value="">Select a warehouse…</option>
                    {(overview.data?.warehouses ?? []).map((warehouse) => (
                      <option key={warehouse.id} value={warehouse.id}>
                        {warehouse.name} ({titleCase(warehouse.operational_status)})
                      </option>
                    ))}
                  </select>
                </label>
              )}

              {spec.target === 'centre' && (
                <label className="field-label">
                  Relief centre
                  <select value={targetId} onChange={(e) => setTargetId(e.target.value)}>
                    <option value="">Select a relief centre…</option>
                    {(overview.data?.relief_centres ?? []).map((centre) => (
                      <option key={centre.id} value={centre.id}>
                        {centre.name} ({titleCase(centre.operational_status)})
                      </option>
                    ))}
                  </select>
                </label>
              )}

              {spec.target === 'vehicle' && (
                <label className="field-label">
                  Vehicle
                  <select value={targetId} onChange={(e) => setTargetId(e.target.value)}>
                    <option value="">Select a vehicle…</option>
                    {(overview.data?.vehicles ?? []).map((vehicle) => (
                      <option key={vehicle.id} value={vehicle.id}>
                        {vehicle.vehicle_code} ({titleCase(vehicle.status)})
                      </option>
                    ))}
                  </select>
                </label>
              )}

              {spec.target === 'incident' && (
                <label className="field-label">
                  Existing incident to escalate
                  <select value={targetId} onChange={(e) => setTargetId(e.target.value)}>
                    <option value="">Select an incident…</option>
                    {(incidents.data?.items ?? []).map((incident) => (
                      <option key={incident.id} value={incident.id}>
                        #{incident.id} · {incident.title} ({incident.severity}, {incident.status})
                      </option>
                    ))}
                  </select>
                </label>
              )}

              {spec.target === 'flood' && (
                <>
                  <label className="field-label">
                    Incident title
                    <input value={floodTitle} onChange={(e) => setFloodTitle(e.target.value)} placeholder="Flash flooding in sector" />
                  </label>
                  <label className="field-label">
                    Anchor location (coordinates copied from a real map node)
                    <select value={targetId} onChange={(e) => setTargetId(e.target.value)}>
                      <option value="">Select anchor node…</option>
                      {(overview.data?.road_nodes ?? []).map((node) => (
                        <option key={node.id} value={node.id}>
                          {node.node_name} — {node.latitude.toFixed(4)}, {node.longitude.toFixed(4)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <div className="row-12">
                    <label className="field-label" style={{ flex: 1 }}>
                      Affected population (optional)
                      <input
                        value={floodPopulation}
                        onChange={(e) => setFloodPopulation(e.target.value)}
                        inputMode="numeric"
                        placeholder="1200"
                      />
                    </label>
                    <label className="field-label" style={{ flex: 1 }}>
                      Severity (defaults HIGH)
                      <select value={severity} onChange={(e) => setSeverity(e.target.value)}>
                        <option value="">Backend default</option>
                        <option value="low">Low</option>
                        <option value="medium">Medium</option>
                        <option value="high">High</option>
                        <option value="critical">Critical</option>
                      </select>
                    </label>
                  </div>
                </>
              )}

              <div className="callout info" style={{ fontSize: 12.5 }}>
                <strong>Expected impact:</strong> {spec.impact}
              </div>

              <div className="row-8">
                <button
                  className="btn primary"
                  disabled={!isReady || busy}
                  onClick={() => setConfirmOpen(true)}
                >
                  <Zap size={14} /> Apply simulated event
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* Result + explanation */}
        <div className="card">
          <div className="card-header">
            <Download size={15} className="header-icon" />
            <h3>Applied result</h3>
          </div>
          <div className="card-body">
            {!result ? (
              <EmptyState message="Apply an event to see exactly what the backend changed — the transactional change list appears here." />
            ) : (
              <div className="stack-10">
                <div className="spread">
                  <div>
                    <strong>{result.event.title}</strong>
                    <div className="muted" style={{ fontSize: 12 }}>{result.event.description}</div>
                  </div>
                  <StatusBadge value={result.event.severity} className={SEVERITY_CLASS[result.event.severity]} />
                </div>
                <div className="section-title" style={{ marginBottom: 4 }}>Changes applied</div>
                <ul className="check-list" style={{ margin: 0, paddingLeft: 18 }}>
                  {result.changes.map((change) => (
                    <li key={change}>{change}</li>
                  ))}
                </ul>
                <div className="muted" style={{ fontSize: 12 }}>
                  Recorded as simulation event #{result.event.id} at {formatDateTime(result.event.created_at)}
                  {result.event.location_name ? ` · ${result.event.location_name}` : ''}.
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Simulated event timeline */}
      <div className="card">
        <div className="card-header">
          <h3>Simulation event log (append-only)</h3>
          <div className="card-header-right muted">{events.data?.items.length ?? 0} events</div>
        </div>
        <div className="card-body">
          {events.error ? (
            <ErrorState error={events.error} onRetry={events.refresh} />
          ) : events.loading ? (
            <LoadingSkeleton variant="lines" />
          ) : (events.data?.items.length ?? 0) === 0 ? (
            <EmptyState message="No simulated events have been applied to this scenario yet." />
          ) : (
            <div className="table-wrap">
              <table className="op-table">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Type</th>
                    <th>Title</th>
                    <th>Severity</th>
                    <th>Affects</th>
                    <th>When</th>
                  </tr>
                </thead>
                <tbody>
                  {[...(events.data?.items ?? [])].reverse().map((event) => (
                    <tr key={event.id}>
                      <td className="muted num">{event.id}</td>
                      <td>{titleCase(event.event_type)}</td>
                      <td>{event.title}<div className="muted" style={{ fontSize: 12 }}>{event.description}</div></td>
                      <td><StatusBadge value={event.severity} className={SEVERITY_CLASS[event.severity]} /></td>
                      <td className="muted">
                        {event.affected_entity_type
                          ? `${titleCase(event.affected_entity_type)} #${event.affected_entity_id}`
                          : '—'}
                      </td>
                      <td className="muted">{formatDateTime(event.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {/* Confirmations */}
      <ConfirmDialog
        open={confirmOpen}
        title={`Apply “${spec.label}”?`}
        body={`This writes a simulated ${spec.type} event through POST /simulation/events. The backend applies the changes in one transaction and records the event in the log above.`}
        bullets={[spec.impact]}
        confirmLabel="Apply event"
        busy={busy}
        onConfirm={() => void apply()}
        onCancel={() => setConfirmOpen(false)}
      />
      <ConfirmDialog
        open={resetOpen}
        tone="danger"
        title="Reset simulation scenario?"
        body="Restores the original seeded demo data (vehicles, inventory, incidents, roads, orders). All simulated events and downstream changes made since seeding are wiped. Operator-confirmed on purpose."
        confirmLabel="Reset scenario"
        busy={resetting}
        onConfirm={() => void doReset()}
        onCancel={() => setResetOpen(false)}
      />
    </div>
  );
}

function buildPayload(
  spec: EventSpec,
  targetId: string,
  reasonText: string,
  floodTitle: string,
  floodPopulation: string,
  severityText: string,
  overview: MapOverviewResponse | null,
): SimulationEventCreatePayload | null {
  const id = Number(targetId);
  const severity = severityText ? (severityText as Severity) : undefined;
  const reason = reasonText.trim() || undefined;

  switch (spec.target) {
    case 'road':
    case 'road_blocked':
      return Number.isFinite(id) && id > 0
        ? {
            event_type: spec.type,
            road_segment_id: id,
            blockage_reason: reason,
            description: reason,
          }
        : null;
    case 'warehouse':
      return Number.isFinite(id) && id > 0 ? { event_type: spec.type, warehouse_id: id } : null;
    case 'centre':
      return Number.isFinite(id) && id > 0 ? { event_type: spec.type, relief_centre_id: id } : null;
    case 'vehicle':
      return Number.isFinite(id) && id > 0 ? { event_type: spec.type, vehicle_id: id } : null;
    case 'incident':
      return Number.isFinite(id) && id > 0 ? { event_type: spec.type, incident_id: id } : null;
    case 'flood': {
      const node = overview?.road_nodes.find((candidate) => candidate.id === Number(targetId));
      if (!Number.isFinite(id) || !node) return null;
      const population = Number(floodPopulation);
      return {
        event_type: 'new_flood_report',
        title: floodTitle.trim() || undefined,
        location_name: node.node_name,
        latitude: node.latitude,
        longitude: node.longitude,
        affected_population: Number.isFinite(population) && population > 0 ? population : undefined,
        severity,
      };
    }
    default:
      return null;
  }
}
