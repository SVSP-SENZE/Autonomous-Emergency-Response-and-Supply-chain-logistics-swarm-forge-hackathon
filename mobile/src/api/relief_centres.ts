import { http } from './client';
import type { ListResponse, ReliefCentre } from '../types';

export function listReliefCentres(): Promise<ListResponse<ReliefCentre>> {
  return http.get<ListResponse<ReliefCentre>>('/relief-centres');
}
