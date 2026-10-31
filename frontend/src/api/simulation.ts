import { http } from './client';
import type {
  ListResponse,
  SimulationEvent,
  SimulationEventCreatePayload,
  SimulationEventResult,
  SimulationResetResponse,
  Vehicle,
} from '../types';

export function listSimulationEvents(
  limit = 100,
  signal?: AbortSignal,
): Promise<ListResponse<SimulationEvent>> {
  return http.get<ListResponse<SimulationEvent>>('/simulation/events', { limit }, signal);
}

/** Apply a simulated event; returns exactly what the backend changed. */
export function applySimulationEvent(
  payload: SimulationEventCreatePayload,
): Promise<SimulationEventResult> {
  return http.post<SimulationEventResult>('/simulation/events', payload);
}

/** Reset the demo scenario to its initial seeded state (operator-confirmed). */
export function resetSimulation(): Promise<SimulationResetResponse> {
  return http.post<SimulationResetResponse>('/simulation/reset');
}

export function listVehicles(signal?: AbortSignal): Promise<ListResponse<Vehicle>> {
  return http.get<ListResponse<Vehicle>>('/vehicles', undefined, signal);
}
