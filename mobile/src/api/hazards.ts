import { http } from './client';
import type { SimulationEventCreatePayload, SimulationEventResult } from '../types';

export function reportHazard(payload: SimulationEventCreatePayload): Promise<SimulationEventResult> {
  return http.post<SimulationEventResult>('/simulation/events', payload);
}
