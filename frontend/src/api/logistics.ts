import { http } from './client';
import type {
  AllocationPlanResponse,
  DemandAssessmentResponse,
  ListResponse,
  PlanningRunDetail,
  PlanningRunSummary,
  PlanningType,
  RouteEntitiesPayload,
  RouteRead,
  RouteRecalculationResponse,
} from '../types';

/**
 * Demand estimation.
 *
 * `persist=true` uses POST /planning/demand/estimate (persists an auditable
 * planning run); otherwise GET /planning/demand is read-only.
 */
export function computeDemand(
  horizonHours: number,
  persist: boolean,
): Promise<DemandAssessmentResponse> {
  return persist
    ? http.postWithQuery<DemandAssessmentResponse>('/planning/demand/estimate', {
        horizon_hours: horizonHours,
      })
    : http.get<DemandAssessmentResponse>('/planning/demand', {
        horizon_hours: horizonHours,
      });
}

/** Multi-warehouse allocation plan (persisted snapshot; never mutates stock). */
export function computeAllocation(horizonHours: number): Promise<AllocationPlanResponse> {
  return http.post<AllocationPlanResponse>('/planning/allocation/compute', {
    horizon_hours: horizonHours,
  });
}

export function getLatestAllocation(signal?: AbortSignal): Promise<AllocationPlanResponse> {
  return http.get<AllocationPlanResponse>('/planning/allocation/latest', undefined, signal);
}

/** Route between warehouse/centre/junction entities (not persisted). */
export function routeBetweenEntities(payload: RouteEntitiesPayload): Promise<RouteRead> {
  return http.post<RouteRead>('/planning/routes/between-entities', payload);
}

/** Recalculate a route after disruption, comparing with the last persisted one. */
export function recalculateRoute(
  originNodeId: number,
  destinationNodeId: number,
): Promise<RouteRecalculationResponse> {
  return http.post<RouteRecalculationResponse>('/planning/routes/recalculate', {
    origin_node_id: originNodeId,
    destination_node_id: destinationNodeId,
  });
}

/** Persisted planning-run audit history (newest first). */
export function listPlanningRuns(
  planningType?: PlanningType,
  limit = 20,
  signal?: AbortSignal,
): Promise<ListResponse<PlanningRunSummary>> {
  return http.get<ListResponse<PlanningRunSummary>>(
    '/planning/runs',
    { planning_type: planningType, limit },
    signal,
  );
}

export function getPlanningRunDetail(
  runId: number,
  signal?: AbortSignal,
): Promise<PlanningRunDetail> {
  return http.get<PlanningRunDetail>(`/planning/runs/${runId}`, undefined, signal);
}
