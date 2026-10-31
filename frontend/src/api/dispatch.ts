import { http } from './client';
import type {
  FleetOverviewResponse,
  RouteConfirmationResponse,
  TrackingResponse,
} from '../types';

export { routeBetweenEntities } from './logistics';
import { routeBetweenEntities } from './logistics';
import type { RouteRead } from '../types';

export type { RouteRead };

export interface DispatchOrderFilters {
  status?: string;
  priority?: string;
  warehouse_id?: number;
  relief_centre_id?: number;
  vehicle_id?: number;
  limit?: number;
}

export interface DispatchOrderListResponse {
  data_mode: 'SIMULATED';
  total: number;
  orders: import('../types').DispatchOrder[];
}

export function getDispatchSummary(signal?: AbortSignal): Promise<DispatchSummary> {
  return http.get<DispatchSummary>('/dispatch/summary', undefined, signal);
}

export type DispatchSummary = import('../types').DispatchSummaryResponse;

export function listDispatchOrders(
  filters: DispatchOrderFilters = {},
  signal?: AbortSignal,
): Promise<DispatchOrderListResponse> {
  return http.get<DispatchOrderListResponse>(
    '/dispatch/orders',
    {
      status: filters.status,
      priority: filters.priority,
      warehouse_id: filters.warehouse_id,
      relief_centre_id: filters.relief_centre_id,
      vehicle_id: filters.vehicle_id,
      limit: filters.limit,
    },
    signal,
  );
}

export function getDispatchOrder(
  orderId: number,
  signal?: AbortSignal,
): Promise<import('../types').DispatchOrderDetail> {
  return http.get<import('../types').DispatchOrderDetail>(
    `/dispatch/orders/${orderId}`,
    undefined,
    signal,
  );
}

export function getOrderTracking(
  orderId: number,
  signal?: AbortSignal,
): Promise<TrackingResponse> {
  return http.get<TrackingResponse>(`/dispatch/orders/${orderId}/tracking`, undefined, signal);
}

export function advanceOrder(orderId: number, minutes?: number): Promise<TrackingResponse> {
  return http.post<TrackingResponse>(`/dispatch/orders/${orderId}/advance`, {
    minutes: minutes ?? null,
  });
}

export function generateDispatchOrders(
  planningRunId: number,
  regenerate = false,
): Promise<import('../types').GenerateOrdersResponse> {
  return http.postWithQuery<import('../types').GenerateOrdersResponse>(
    `/dispatch/planning-runs/${planningRunId}/generate`,
    { regenerate: String(regenerate) },
  );
}

export function assignVehicle(
  orderId: number,
  vehicleId: number | null,
): Promise<import('../types').AssignVehicleResponse> {
  return http.post<import('../types').AssignVehicleResponse>(
    `/dispatch/orders/${orderId}/assign-vehicle`,
    vehicleId === null ? undefined : { vehicle_id: vehicleId },
  );
}

export function approveOrder(orderId: number): Promise<import('../types').DispatchOrderDetail> {
  return http.post<import('../types').DispatchOrderDetail>(`/dispatch/orders/${orderId}/approve`);
}

export function dispatchOrder(orderId: number): Promise<import('../types').DispatchOrderDetail> {
  return http.post<import('../types').DispatchOrderDetail>(`/dispatch/orders/${orderId}/dispatch`);
}

export function deliverOrder(orderId: number): Promise<import('../types').DispatchOrderDetail> {
  return http.post<import('../types').DispatchOrderDetail>(`/dispatch/orders/${orderId}/deliver`);
}

export function cancelOrder(orderId: number): Promise<import('../types').DispatchOrderDetail> {
  return http.post<import('../types').DispatchOrderDetail>(`/dispatch/orders/${orderId}/cancel`);
}

export function confirmOrderRoute(orderId: number): Promise<RouteConfirmationResponse> {
  return http.post<RouteConfirmationResponse>(`/dispatch/orders/${orderId}/confirm-route`);
}

export function getFleetOverview(signal?: AbortSignal): Promise<FleetOverviewResponse> {
  return http.get<FleetOverviewResponse>('/dispatch/fleet/overview', undefined, signal);
}

export function listDispatchEvents(
  orderId?: number,
  limit = 50,
  signal?: AbortSignal,
): Promise<{ total: number; events: import('../types').DispatchEvent[] }> {
  return http.get(
    '/dispatch/events',
    { order_id: orderId, limit },
    signal,
  );
}

export { routeBetweenEntities as computeEntityRoute };
