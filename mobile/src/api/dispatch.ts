import { http } from './client';
import type { DispatchOrderDetail, DispatchOrderListResponse } from '../types';

export function listDispatchOrders(status?: string): Promise<DispatchOrderListResponse> {
  return http.get<DispatchOrderListResponse>('/dispatch/orders', status ? { status } : undefined);
}

export function getDispatchOrder(orderId: number): Promise<DispatchOrderDetail> {
  return http.get<DispatchOrderDetail>(`/dispatch/orders/${orderId}`);
}

export function dispatchOrder(orderId: number): Promise<DispatchOrderDetail> {
  return http.post<DispatchOrderDetail>(`/dispatch/orders/${orderId}/dispatch`);
}

export function deliverOrder(orderId: number): Promise<DispatchOrderDetail> {
  return http.post<DispatchOrderDetail>(`/dispatch/orders/${orderId}/deliver`);
}
