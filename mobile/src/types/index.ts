/**
 * ReliefMesh Mobile — Shared TypeScript types
 * Mirrors the FastAPI Pydantic schemas in backend/app/schemas/
 */

export type DataMode = 'SIMULATED';
export type Severity = 'low' | 'medium' | 'high' | 'critical';
export type Priority = Severity;
export type IncidentType =
  | 'flood'
  | 'cyclone'
  | 'landslide'
  | 'infrastructure_damage'
  | 'water_shortage'
  | 'fire'
  | 'other';
export type IncidentSource = 'weather_api' | 'citizen_report' | 'operator' | 'simulation';
export type IncidentStatus = 'reported' | 'investigating' | 'active' | 'resolved';
export type OperationalStatus = 'operational' | 'degraded' | 'unavailable';
export type SupplyType = 'food_kit' | 'water_litre' | 'medical_kit' | 'hygiene_kit';
export type VehicleType = 'truck' | 'van' | 'drone';
export type VehicleStatus = 'available' | 'assigned' | 'in_transit' | 'delayed' | 'maintenance';
export type OrderStatus =
  | 'draft'
  | 'awaiting_approval'
  | 'approved'
  | 'dispatched'
  | 'in_transit'
  | 'delayed'
  | 'delivered'
  | 'cancelled';
export type SimulationEventType =
  | 'bridge_collapse'
  | 'road_blocked'
  | 'warehouse_unavailable'
  | 'relief_centre_water_shortage'
  | 'new_flood_report'
  | 'rainfall_escalation'
  | 'vehicle_breakdown';

export interface ListResponse<T> {
  items: T[];
  total: number;
  data_mode?: DataMode;
}

// ----------------------------------------------------------------- incidents

export interface Incident {
  id: number;
  incident_type: IncidentType;
  title: string;
  description: string;
  source: IncidentSource;
  severity: Severity;
  status: IncidentStatus;
  location_name: string;
  latitude: number | null;
  longitude: number | null;
  affected_population: number;
  metadata: Record<string, unknown>;
  is_demo: boolean;
  created_at: string;
  updated_at: string;
}

export interface IncidentCreatePayload {
  incident_type: IncidentType;
  title: string;
  description: string;
  source: IncidentSource;
  severity: Severity;
  status?: IncidentStatus;
  location_name: string;
  latitude: number;
  longitude: number;
  affected_population: number;
}

// ----------------------------------------------------------------- relief centres

export interface ReliefCentre {
  id: number;
  name: string;
  district: string;
  latitude: number;
  longitude: number;
  affected_population: number;
  priority: Priority;
  operational_status: OperationalStatus;
  water_shortage: boolean;
}

// ----------------------------------------------------------------- dispatch

export interface DispatchOrderItem {
  id: number;
  supply_type: SupplyType;
  quantity: number;
  unit: string;
  estimated_weight_kg: number;
}

export interface DispatchOrder {
  id: number;
  order_code: string;
  status: OrderStatus;
  priority: Priority;
  warehouse_id: number;
  relief_centre_id: number;
  vehicle_id: number | null;
  total_cargo_weight_kg: number;
  estimated_travel_time_minutes: number;
  progress_percent: number;
  dispatched_at: string | null;
  delivered_at: string | null;
  items: DispatchOrderItem[];
  created_at: string;
  updated_at: string;
}

export interface DispatchOrderListResponse {
  data_mode: DataMode;
  total: number;
  orders: DispatchOrder[];
}

export interface DispatchOrderDetail {
  data_mode: DataMode;
  order: DispatchOrder;
  warehouse_name: string;
  relief_centre_name: string;
}

// ----------------------------------------------------------------- simulation

export interface SimulationEventCreatePayload {
  event_type: SimulationEventType;
  title?: string;
  description?: string;
  severity?: Severity;
  location_name?: string;
  latitude?: number;
  longitude?: number;
  affected_population?: number;
  blockage_reason?: string;
  road_segment_id?: number;
}

export interface SimulationEventResult {
  data_mode: DataMode;
  message: string;
  event_id: number;
}

// ----------------------------------------------------------------- app-local types

export type AppRole = 'citizen' | 'volunteer';

export interface SosForm {
  peopleCount: number;
  hasMedical: boolean;
  hasElderly: boolean;
  hasChildren: boolean;
  waterLevel: 'ankle' | 'knee' | 'waist' | 'chest' | 'roof';
  locationName: string;
}
