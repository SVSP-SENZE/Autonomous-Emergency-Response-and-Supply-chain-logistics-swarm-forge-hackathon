import { http } from './client';
import type { Incident, IncidentCreatePayload, ListResponse } from '../types';

export function createIncident(payload: IncidentCreatePayload): Promise<Incident> {
  return http.post<Incident>('/incidents', payload);
}

export function listIncidents(): Promise<ListResponse<Incident>> {
  return http.get<ListResponse<Incident>>('/incidents');
}
