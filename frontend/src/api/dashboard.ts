import { http } from './client';
import type { DashboardResponse } from '../types';

export interface HealthResponse {
  status: string;
  app: string;
  version: string;
  environment: string;
  data_mode: string;
}

export function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return http.get<HealthResponse>('/health', undefined, signal);
}

export function getDashboardSummary(signal?: AbortSignal): Promise<DashboardResponse> {
  return http.get<DashboardResponse>('/dashboard/summary', undefined, signal);
}
