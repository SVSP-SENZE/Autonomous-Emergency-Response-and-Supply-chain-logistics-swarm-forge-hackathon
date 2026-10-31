import { http } from './client';
import type {
  ListResponse,
  MapOverviewResponse,
  ReliefCentre,
  ReliefCentreDetail,
  Vehicle,
  Warehouse,
  WarehouseDetail,
} from '../types';

/** Everything the disaster map needs (warehouses, centres, vehicles, roads). */
export function getMapOverview(signal?: AbortSignal): Promise<MapOverviewResponse> {
  return http.get<MapOverviewResponse>('/map/overview', undefined, signal);
}

export function listWarehouses(signal?: AbortSignal): Promise<ListResponse<Warehouse>> {
  return http.get<ListResponse<Warehouse>>('/warehouses', undefined, signal);
}

export function getWarehouseDetail(
  id: number,
  signal?: AbortSignal,
): Promise<WarehouseDetail> {
  return http.get<WarehouseDetail>(`/warehouses/${id}`, undefined, signal);
}

export function listReliefCentres(signal?: AbortSignal): Promise<ListResponse<ReliefCentre>> {
  return http.get<ListResponse<ReliefCentre>>('/relief-centres', undefined, signal);
}

export function getReliefCentreDetail(
  id: number,
  signal?: AbortSignal,
): Promise<ReliefCentreDetail> {
  return http.get<ReliefCentreDetail>(`/relief-centres/${id}`, undefined, signal);
}

export function listVehicles(signal?: AbortSignal): Promise<ListResponse<Vehicle>> {
  return http.get<ListResponse<Vehicle>>('/vehicles', undefined, signal);
}
