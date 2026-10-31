import { http } from './client';
import type {
  Incident,
  IncidentCreatePayload,
  IncidentSource,
  IncidentStatus,
  IncidentType,
  IncidentUpdatePayload,
  ListResponse,
  Severity,
} from '../types';

export function listIncidents(
  filters: {
    severity?: Severity;
    status?: IncidentStatus;
    incident_type?: IncidentType;
    source?: IncidentSource;
  } = {},
  signal?: AbortSignal,
): Promise<ListResponse<Incident>> {
  return http.get<ListResponse<Incident>>(
    '/incidents',
    {
      severity: filters.severity,
      status: filters.status,
      incident_type: filters.incident_type,
      source: filters.source,
    },
    signal,
  );
}

export function getIncident(id: number, signal?: AbortSignal): Promise<Incident> {
  return http.get<Incident>(`/incidents/${id}`, undefined, signal);
}

export function createIncident(
  payload: IncidentCreatePayload,
  signal?: AbortSignal,
): Promise<Incident> {
  return http.post<Incident>('/incidents', payload, signal);
}

export function updateIncident(
  id: number,
  payload: IncidentUpdatePayload,
): Promise<Incident> {
  return http.patch<Incident>(`/incidents/${id}`, payload);
}
