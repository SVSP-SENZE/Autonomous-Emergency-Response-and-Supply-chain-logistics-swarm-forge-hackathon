import { useMemo, useState } from 'react';
import { useBackendData } from '../hooks/useBackendData';
import { createIncident, listIncidents, updateIncident } from '../api/incidents';
import { listSimulationEvents } from '../api/simulation';
import { ErrorState } from '../components/common/ErrorState';
import { EmptyState } from '../components/common/EmptyState';
import { LoadingSkeleton } from '../components/common/LoadingSkeleton';
import { StatusBadge } from '../components/common/StatusBadge';
import { ConfirmDialog } from '../components/common/ConfirmDialog';
import { useToast } from '../components/common/Toast';
import { SEVERITY_CLASS, formatDateTime, formatNumber, titleCase } from '../utils/format';
import type {
  Incident,
  IncidentStatus,
  IncidentType,
  Severity,
} from '../types';

const SEVERITIES: Severity[] = ['low', 'medium', 'high', 'critical'];
const INCIDENT_TYPES: IncidentType[] = [
  'flood',
  'cyclone',
  'landslide',
  'infrastructure_damage',
  'water_shortage',
  'fire',
  'other',
];
const STATUSES: IncidentStatus[] = ['reported', 'investigating', 'active', 'resolved'];

export function IncidentsPage() {
  const [severity, setSeverity] = useState('');
  const [status, setStatus] = useState('');
  const [incidentType, setIncidentType] = useState('');
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const { push } = useToast();

  const incidents = useBackendData(
    (signal) =>
      listIncidents(
        {
          severity: (severity || undefined) as Severity | undefined,
          status: (status || undefined) as IncidentStatus | undefined,
          incident_type: (incidentType || undefined) as IncidentType | undefined,
        },
        signal,
      ),
    [severity, status, incidentType],
    20000,
  );
  const simEvents = useBackendData((signal) => listSimulationEvents(200, signal), [], 30000);

  const selected = useMemo(
    () => incidents.data?.items.find((item) => item.id === selectedId) ?? null,
    [incidents.data, selectedId],
  );

  const relatedEvents = useMemo(
    () =>
      (simEvents.data?.items ?? [])
        .filter((event) => event.affected_entity_type === 'incident' && event.affected_entity_id === selectedId)
        .reverse()
        .slice(0, 8),
    [simEvents.data, selectedId],
  );

  return (
    <div className="stack-16">
      <div className="spread">
        <div className="filter-row">
          <select value={severity} onChange={(e) => setSeverity(e.target.value)} aria-label="Filter by severity">
            <option value="">All severities</option>
            {SEVERITIES.map((value) => <option key={value} value={value}>{titleCase(value)}</option>)}
          </select>
          <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Filter by status">
            <option value="">All statuses</option>
            {STATUSES.map((value) => <option key={value} value={value}>{titleCase(value)}</option>)}
          </select>
          <select value={incidentType} onChange={(e) => setIncidentType(e.target.value)} aria-label="Filter by type">
            <option value="">All types</option>
            {INCIDENT_TYPES.map((value) => <option key={value} value={value}>{titleCase(value)}</option>)}
          </select>
        </div>
        <span className="sim-note">All incident records are simulated scenario data</span>
      </div>

      <div className="grid-2-1">
        <div className="card">
          <div className="card-header">
            <h3>Incidents ({incidents.data?.total ?? 0})</h3>
          </div>
          <div className="card-body">
            {incidents.error ? (
              <ErrorState error={incidents.error} onRetry={incidents.refresh} />
            ) : incidents.loading ? (
              <LoadingSkeleton variant="table" />
            ) : incidents.data && incidents.data.items.length > 0 ? (
              <div className="table-wrap">
                <table className="op-table">
                  <thead>
                    <tr>
                      <th>Title</th>
                      <th>Type</th>
                      <th>Severity</th>
                      <th>Status</th>
                      <th>Affected</th>
                      <th>Source</th>
                      <th>Updated</th>
                    </tr>
                  </thead>
                  <tbody>
                    {incidents.data.items.map((incident) => (
                      <tr
                        key={incident.id}
                        className={`clickable ${selectedId === incident.id ? 'selected' : ''}`}
                        onClick={() => setSelectedId(incident.id)}
                      >
                        <td style={{ fontWeight: selectedId === incident.id ? 650 : 400 }}>{incident.title}</td>
                        <td className="muted">{titleCase(incident.incident_type)}</td>
                        <td><StatusBadge value={incident.severity} className={SEVERITY_CLASS[incident.severity]} /></td>
                        <td><StatusBadge value={incident.status} className="badge-plain" /></td>
                        <td className="num">{formatNumber(incident.affected_population)}</td>
                        <td className="muted">{titleCase(incident.source)}</td>
                        <td className="muted">{formatDateTime(incident.updated_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <EmptyState message="No incidents match the selected filters." />
            )}
          </div>
        </div>

        <div className="stack-16">
          <IncidentDetail
            incident={selected}
            relatedEvents={relatedEvents}
            onUpdated={(updated) => {
              incidents.refresh();
              push(`Incident #${updated.id} updated to ${titleCase(updated.status ?? '')}.`, 'success');
            }}
            onStatusChangeError={(message) => push(message, 'error')}
          />
          <ReportIncidentForm
            onCreated={(incident) => {
              incidents.refresh();
              setSelectedId(incident.id);
              push(
                `Report filed (source: ${titleCase(incident.source)}). It is unverified until an operator validates it.`,
                'info',
              );
            }}
          />
        </div>
      </div>
    </div>
  );
}

function IncidentDetail({
  incident,
  relatedEvents,
  onUpdated,
  onStatusChangeError,
}: {
  incident: Incident | null;
  relatedEvents: { id: number; title: string; created_at: string; severity: string }[];
  onUpdated: (incident: Incident) => void;
  onStatusChangeError: (message: string) => void;
}) {
  const [confirmStatus, setConfirmStatus] = useState<IncidentStatus | null>(null);
  const [busy, setBusy] = useState(false);

  if (!incident) {
    return (
      <div className="card">
        <div className="card-header"><h3>Incident detail</h3></div>
        <div className="card-body">
          <EmptyState message="Select an incident row to see its full record." />
        </div>
      </div>
    );
  }

  const applyStatus = async () => {
    if (!confirmStatus || !incident) return;
    setBusy(true);
    try {
      const updated = await updateIncident(incident.id, { status: confirmStatus });
      onUpdated(updated);
    } catch (err) {
      onStatusChangeError(err instanceof Error ? err.message : 'Status update failed');
    } finally {
      setBusy(false);
      setConfirmStatus(null);
    }
  };

  return (
    <div className="card">
      <div className="card-header">
        <h3>Incident #{incident.id}</h3>
        <div className="card-header-right">
          <StatusBadge value={incident.severity} className={SEVERITY_CLASS[incident.severity]} />
          <StatusBadge value={incident.status} className="badge-plain" />
        </div>
      </div>
      <div className="card-body stack-12">
        <div>
          <strong style={{ fontSize: 15 }}>{incident.title}</strong>
          <div className="muted">{incident.location_name} · {formatDateTime(incident.created_at)}</div>
        </div>
        <p style={{ margin: 0, fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.55 }}>
          {incident.description}
        </p>
        <div className="stack-8">
          <div className="kv-row"><span className="k">Type</span><span className="v">{titleCase(incident.incident_type)}</span></div>
          <div className="kv-row"><span className="k">Source</span><span className="v">{titleCase(incident.source)}{incident.is_demo ? ' (seeded demo)' : ''}</span></div>
          <div className="kv-row"><span className="k">Affected population</span><span className="v">{formatNumber(incident.affected_population)}</span></div>
          <div className="kv-row">
            <span className="k">Coordinates</span>
            <span className="v">
              {incident.latitude !== null && incident.longitude !== null
                ? `${incident.latitude.toFixed(4)}, ${incident.longitude.toFixed(4)}`
                : '—'}
            </span>
          </div>
        </div>

        {relatedEvents.length > 0 && (
          <div>
            <div className="section-title" style={{ marginBottom: 6 }}>Related simulated events</div>
            <div className="stack-8">
              {relatedEvents.map((event) => (
                <div className="timeline-item" key={event.id} style={{ '--tl-color': 'var(--accent-orange)' } as React.CSSProperties}>
                  <div className="tl-title">
                    {event.title}
                    <span className="badge sev-critical" style={{ fontSize: 9 }}>Simulated</span>
                  </div>
                  <div className="tl-meta">{formatDateTime(event.created_at)}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        {incident.status !== 'resolved' && (
          <div className="row-8">
            <span className="section-title">Update status:</span>
            {(['investigating', 'active', 'resolved'] as IncidentStatus[])
              .filter((value) => value !== incident.status)
              .map((value) => (
                <button key={value} className="btn ghost small" disabled={busy} onClick={() => setConfirmStatus(value)}>
                  Mark {titleCase(value)}
                </button>
              ))}
          </div>
        )}
      </div>

      <ConfirmDialog
        open={confirmStatus !== null}
        title={`Set incident #${incident.id} to ${confirmStatus ? titleCase(confirmStatus) : ''}?`}
        body="The backend records the status change in the incident registry. This does not alter any dispatch order or inventory."
        confirmLabel="Set status"
        busy={busy}
        onConfirm={() => void applyStatus()}
        onCancel={() => setConfirmStatus(null)}
      />
    </div>
  );
}

function ReportIncidentForm({
  onCreated,
}: {
  onCreated: (incident: Incident) => void;
}) {
  const { push } = useToast();
  const [form, setForm] = useState({
    incident_type: 'flood' as IncidentType,
    title: '',
    description: '',
    location_name: '',
    latitude: '',
    longitude: '',
    severity: 'medium' as Severity,
    affected_population: '0',
  });
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);

  const set = (key: keyof typeof form) => (event: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
    setForm((current) => ({ ...current, [key]: event.target.value }));

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const validation: string[] = [];
    if (form.title.trim().length < 3) validation.push('A descriptive title (min 3 characters) is required.');
    if (!form.description.trim()) validation.push('A description is required.');
    if (!form.location_name.trim()) validation.push('A location name is required.');
    const lat = Number(form.latitude);
    const lng = Number(form.longitude);
    if (form.latitude === '' || Number.isNaN(lat) || lat < -90 || lat > 90) validation.push('Latitude must be a number between -90 and 90.');
    if (form.longitude === '' || Number.isNaN(lng) || lng < -180 || lng > 180) validation.push('Longitude must be a number between -180 and 180.');
    setErrors(validation);
    if (validation.length > 0) return;

    setBusy(true);
    try {
      const created = await createIncident({
        incident_type: form.incident_type,
        title: form.title.trim(),
        description: form.description.trim(),
        source: 'operator',
        severity: form.severity,
        status: 'reported',
        location_name: form.location_name.trim(),
        latitude: lat,
        longitude: lng,
        affected_population: Math.max(0, Math.round(Number(form.affected_population) || 0)),
      });
      setForm({
        incident_type: 'flood',
        title: '',
        description: '',
        location_name: '',
        latitude: '',
        longitude: '',
        severity: 'medium',
        affected_population: '0',
      });
      onCreated(created);
    } catch (err) {
      push(err instanceof Error ? err.message : 'Incident creation failed', 'error');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card">
      <div className="card-header">
        <h3>Report an incident</h3>
        <div className="card-header-right muted">filed as operator source · unverified until reviewed</div>
      </div>
      <div className="card-body">
        <form className="stack-12" onSubmit={submit}>
          <div className="form-grid">
            <div className="field">
              <label>Type</label>
              <select value={form.incident_type} onChange={set('incident_type')}>
                {INCIDENT_TYPES.map((value) => <option key={value} value={value}>{titleCase(value)}</option>)}
              </select>
            </div>
            <div className="field">
              <label>Severity</label>
              <select value={form.severity} onChange={set('severity')}>
                {SEVERITIES.map((value) => <option key={value} value={value}>{titleCase(value)}</option>)}
              </select>
            </div>
          </div>
          <div className="field">
            <label>Title *</label>
            <input className="input" value={form.title} onChange={set('title')} placeholder="e.g. Levee breach near Ambattur" />
          </div>
          <div className="field">
            <label>Description *</label>
            <textarea value={form.description} onChange={set('description')} placeholder="What is happening, when was it observed…" />
          </div>
          <div className="form-grid">
            <div className="field">
              <label>Location name *</label>
              <input className="input" value={form.location_name} onChange={set('location_name')} />
            </div>
            <div className="field">
              <label>Latitude *</label>
              <input className="input" value={form.latitude} onChange={set('latitude')} placeholder="13.0827" inputMode="decimal" />
            </div>
            <div className="field">
              <label>Longitude *</label>
              <input className="input" value={form.longitude} onChange={set('longitude')} placeholder="80.2707" inputMode="decimal" />
            </div>
            <div className="field">
              <label>Affected population</label>
              <input className="input" value={form.affected_population} onChange={set('affected_population')} inputMode="numeric" />
            </div>
          </div>
          {errors.length > 0 && (
            <div style={{ color: 'var(--accent-red)', fontSize: 12 }}>
              {errors.map((error, i) => <div key={i}>· {error}</div>)}
            </div>
          )}
          <div className="row-8">
            <button className="btn primary" type="submit" disabled={busy}>
              {busy ? 'Filing…' : 'File report'}
            </button>
            <span className="muted">
              Filed reports carry source “operator” and start as <strong>reported</strong>; they are not verified data.
            </span>
          </div>
        </form>
      </div>
    </div>
  );
}
