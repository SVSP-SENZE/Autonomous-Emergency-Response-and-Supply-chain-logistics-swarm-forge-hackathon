/**
 * ReliefMesh domain types — 1:1 mirrors of the FastAPI Pydantic schemas
 * (backend/app/schemas/* and backend/app/ai/schemas/chat.py).
 * The backend is the single source of truth for these shapes.
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
export type NodeType = 'warehouse' | 'junction' | 'relief_centre';
export type OrderStatus =
  | 'draft'
  | 'awaiting_approval'
  | 'approved'
  | 'dispatched'
  | 'in_transit'
  | 'delayed'
  | 'delivered'
  | 'cancelled';
export type PlanningType = 'demand' | 'allocation' | 'route_calculation' | 'route_recalculation';

export interface ListResponse<T> {
  items: T[];
  total: number;
  data_mode?: DataMode;
}

// ------------------------------------------------------------------ dashboard

export interface DashboardKPIs {
  affected_population: number;
  active_disasters: number;
  relief_centres: number;
  critical_centres: number;
  warehouses: number;
  total_vehicles: number;
  available_vehicles: number;
  vehicles_in_transit: number;
  blocked_roads: number;
}

export interface InventoryAggregate {
  supply_type: SupplyType;
  unit: string;
  quantity: number;
  reserved_quantity: number;
  available_quantity: number;
}

export interface DashboardResponse {
  data_mode: DataMode;
  summary: DashboardKPIs;
  inventory: InventoryAggregate[];
  orders_by_status: Record<string, number>;
  generated_at: string;
}

// ------------------------------------------------------------------ incidents

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

export interface IncidentUpdatePayload {
  status?: IncidentStatus;
  severity?: Severity;
  description?: string;
}

// -------------------------------------------------------------------- map

export interface MapIncident {
  id: number;
  incident_type: IncidentType;
  title: string;
  severity: Severity;
  status: IncidentStatus;
  location_name: string;
  latitude: number;
  longitude: number;
  affected_population: number;
  /** Provenance (used to hide seeded demo markers and style live ones). */
  source?: IncidentSource;
  is_demo?: boolean;
  updated_at?: string | null;
  metadata?: Record<string, unknown>;
}

export interface MapReliefCentre {
  id: number;
  name: string;
  district: string;
  latitude: number;
  longitude: number;
  affected_population: number;
  priority: Priority;
  operational_status: OperationalStatus;
  water_shortage: boolean;
  is_demo?: boolean;
}

export interface MapWarehouse {
  id: number;
  name: string;
  location_name: string;
  latitude: number;
  longitude: number;
  operational_status: OperationalStatus;
  is_demo?: boolean;
}

export interface MapVehicle {
  id: number;
  vehicle_code: string;
  vehicle_type: VehicleType;
  status: VehicleStatus;
  capacity: number;
  current_latitude: number | null;
  current_longitude: number | null;
  current_location: string;
  is_demo?: boolean;
}

export interface MapRoadNode {
  id: number;
  node_name: string;
  node_type: NodeType;
  latitude: number;
  longitude: number;
  linked_entity_id: number | null;
}

export interface MapRoadSegment {
  id: number;
  from_node_id: number;
  to_node_id: number;
  from_node_name: string;
  to_node_name: string;
  distance_km: number;
  estimated_travel_time_minutes: number;
  risk_factor: number;
  is_blocked: boolean;
  blockage_reason: string | null;
}

export interface MapCenter {
  latitude: number;
  longitude: number;
  zoom: number;
}

// ----------------------------------------------------------------- live layers

export type LiveLayerState = 'ok' | 'stale' | 'unavailable';

export interface LiveLayerStatus {
  source: string;
  status: LiveLayerState;
  last_updated: string | null;
  detail?: string | null;
}

/** Open-Meteo current-conditions marker (one monitored delta station). */
export interface MapWeatherStation {
  name: string;
  district: string;
  latitude: number;
  longitude: number;
  temperature_c: number | null;
  precipitation_mm: number | null;
  daily_precipitation_mm: number | null;
  wind_speed_kmh: number | null;
  wind_gusts_kmh: number | null;
  weather_code: number | null;
  river: string | null;
  severity: Severity | null;
  assessment: string | null;
  updated_at: string | null;
  source: string;
}

/** Open-Meteo Flood API river-discharge gauge at a monitored station. */
export interface MapRiverGauge {
  name: string;
  river: string | null;
  latitude: number;
  longitude: number;
  river_discharge_m3s: number | null;
  daily_precipitation_mm: number | null;
  severity: Severity | null;
  assessment: string | null;
  updated_at: string | null;
  source: string;
}

/** External disaster event / alert (NASA EONET or GDACS). */
export interface MapDisasterEvent {
  external_id: string | null;
  title: string;
  category: string | null;
  alert_level: string | null;
  severity: Severity | null;
  severity_text: string | null;
  latitude: number;
  longitude: number;
  source: string;
  link: string | null;
  occurred_at: string | null;
  updated_at: string | null;
}

/** Genuine hospital / medical facility from OSM Nominatim. */
export interface MapFacility {
  name: string;
  display_name: string | null;
  town: string | null;
  latitude: number;
  longitude: number;
  osm_id: string | null;
  osm_type: string | null;
  category: string;
  source: string;
  updated_at: string | null;
}

export interface MapLiveLayers {
  weather_stations: MapWeatherStation[];
  river_gauges: MapRiverGauge[];
  disaster_events: MapDisasterEvent[];
  facilities: MapFacility[];
  statuses: LiveLayerStatus[];
}

export interface MapOverviewResponse {
  data_mode: DataMode;
  generated_at: string;
  center: MapCenter;
  incidents: MapIncident[];
  relief_centres: MapReliefCentre[];
  warehouses: MapWarehouse[];
  vehicles: MapVehicle[];
  road_nodes: MapRoadNode[];
  road_segments: MapRoadSegment[];
  blocked_roads: MapRoadSegment[];
  live_layers?: MapLiveLayers;
}

// -------------------------------------------------------------------- resources

export interface InventoryItem {
  id: number;
  supply_type: SupplyType;
  quantity: number;
  reserved_quantity: number;
  available_quantity: number;
  unit: string;
  warehouse_id: number;
  updated_at: string;
}

export interface Warehouse {
  id: number;
  name: string;
  location_name: string;
  latitude: number;
  longitude: number;
  operational_status: OperationalStatus;
  storage_capacity: number;
}

export interface WarehouseDetail extends Warehouse {
  inventory: InventoryItem[];
}

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

export interface ReliefCentreInventoryLine {
  supply_type: string;
  quantity: number;
  unit: string;
  updated_at: string;
}

export interface ReliefCentreDetail extends ReliefCentre {
  water_shortage_notes: string | null;
  is_demo: boolean;
  created_at: string;
  updated_at: string;
  inventory: ReliefCentreInventoryLine[];
}

export interface Vehicle {
  id: number;
  vehicle_code: string;
  vehicle_type: VehicleType;
  capacity: number;
  status: VehicleStatus;
  current_latitude: number | null;
  current_longitude: number | null;
  current_location: string;
  warehouse_id?: number | null;
}

// -------------------------------------------------------------------- planning

export interface DemandAssumptions {
  planning_horizon_hours: number;
  consumption_rates_per_person_per_day: Record<string, number>;
  priority_component_weight: number;
  shortage_component_weight: number;
  population_component_weight: number;
  supply_risk_component_weight: number;
  note: string;
}

export interface DemandItem {
  supply_type: SupplyType;
  unit: string;
  required_quantity: number;
  current_stock: number;
  shortage_quantity: number;
  surplus_quantity: number;
  shortage_percentage: number;
}

export interface DemandCentre {
  relief_centre_id: number;
  name: string;
  district: string;
  latitude: number;
  longitude: number;
  affected_population: number;
  centre_priority: Priority;
  operational_status: OperationalStatus;
  allocation_eligible: boolean;
  priority_score: number;
  priority_classification: string;
  items: DemandItem[];
  max_shortage_percentage: number;
}

export interface DemandSummary {
  centres_assessed: number;
  centres_eligible: number;
  total_required_by_supply: Record<string, number>;
  total_shortage_by_supply: Record<string, number>;
  total_stock_at_centres_by_supply: Record<string, number>;
}

export interface DemandAssessmentResponse {
  data_mode: DataMode;
  generated_at: string;
  planning_run_id: number | null;
  horizon_hours: number;
  assumptions: DemandAssumptions;
  summary: DemandSummary;
  centres: DemandCentre[];
}

export interface AllocationSource {
  warehouse_id: number;
  warehouse_name: string;
  quantity: number;
  route_distance_km: number;
  route_travel_time_minutes: number;
  route_risk: number;
  route_cost: number;
}

export interface AllocationLine {
  supply_type: SupplyType;
  required_quantity: number;
  current_stock: number;
  shortage_quantity: number;
  allocated_quantity: number;
  unfulfilled_quantity: number;
  fulfilment_percentage: number;
  sources: AllocationSource[];
}

export interface AllocationCentre {
  relief_centre_id: number;
  name: string;
  district: string;
  affected_population: number;
  centre_priority: Priority;
  priority_score: number;
  operational_status: OperationalStatus;
  lines: AllocationLine[];
}

export interface WarehouseUtilisation {
  warehouse_id: number;
  warehouse_name: string;
  initial_available_by_supply: Record<string, number>;
  allocated_by_supply: Record<string, number>;
  remaining_by_supply: Record<string, number>;
}

export interface AllocationSummary {
  required_by_supply: Record<string, number>;
  allocated_by_supply: Record<string, number>;
  unfulfilled_by_supply: Record<string, number>;
  fulfilment_percentage: number;
  centres_planned: number;
  centres_served: number;
  centres_with_unmet_demand: number;
  warehouse_utilisation: WarehouseUtilisation[];
  remaining_by_supply: Record<string, number>;
}

export interface AllocationPlanResponse {
  data_mode: DataMode;
  generated_at: string;
  planning_run_id: number | null;
  horizon_hours: number;
  summary: AllocationSummary;
  centres: AllocationCentre[];
}

export interface RouteSegment {
  segment_id: number;
  from_node_id: number;
  to_node_id: number;
  from_node_name: string;
  to_node_name: string;
  distance_km: number;
  estimated_travel_time_minutes: number;
  risk_factor: number;
}

export interface RouteEntitiesPayload {
  origin_type: 'warehouse' | 'relief_centre' | 'junction';
  origin_id: number;
  destination_type: 'warehouse' | 'relief_centre' | 'junction';
  destination_id: number;
}

/** POST /planning/routes/recalculate comparison result. */
export interface RouteRecalculationResponse {
  data_mode: DataMode;
  generated_at: string;
  planning_run_id: number | null;
  historical_route_available: boolean;
  current_route: RouteRead;
  previous_route: RouteRead | null;
  delay_minutes: number | null;
  distance_delta_km: number | null;
  alternative_route_available: boolean;
  explanation: string;
}

export interface RouteRead {
  reachable: boolean;
  origin: string;
  destination: string;
  origin_node_id: number;
  destination_node_id: number;
  route_nodes: number[];
  route_node_names: string[];
  segments: RouteSegment[];
  distance_km: number;
  estimated_travel_time_minutes: number;
  route_risk: number;
  blocked_segments_avoided: number;
  message: string;
  /* Real-network (OSM) routing extensions — additive, may be absent on
     simulated-graph responses. */
  status_code?: 'ROUTE_FOUND' | 'NO_ROUTE_AVAILABLE';
  /** GeoJSON [longitude, latitude] pairs along actual mapped roads. */
  geometry_coords?: [number, number][];
  geojson_linestring?: { type: 'LineString'; coordinates: [number, number][] } | null;
  road_names?: string[];
  network?: 'osm_real' | 'simulated_graph';
}

export interface PlanningRunSummary {
  id: number;
  planning_type: PlanningType;
  status: 'completed' | 'failed';
  planning_horizon_hours: number | null;
  created_at: string;
}

export interface PlanningRunDetail extends PlanningRunSummary {
  summary: Record<string, unknown>;
  snapshot: Record<string, unknown>;
}

// -------------------------------------------------------------------- dispatch

export interface DispatchOrderItem {
  id: number;
  supply_type: SupplyType;
  quantity: number;
  unit: string;
  estimated_weight_kg: number;
}

export interface DispatchVehicleBrief {
  id: number;
  vehicle_code: string;
  vehicle_type: VehicleType;
  capacity: number;
  capacity_kg: number | null;
  status: VehicleStatus;
  current_location: string;
  current_latitude: number | null;
  current_longitude: number | null;
}

export interface DispatchOrder {
  id: number;
  order_code: string;
  status: OrderStatus;
  priority: Priority;
  warehouse_id: number;
  relief_centre_id: number;
  vehicle_id: number | null;
  planning_run_id: number | null;
  total_cargo_weight_kg: number;
  estimated_travel_time_minutes: number;
  actual_travel_time_minutes: number | null;
  route_progress_minutes: number;
  progress_percent: number;
  approved_at: string | null;
  dispatched_at: string | null;
  delivered_at: string | null;
  items: DispatchOrderItem[];
  is_demo: boolean;
  created_at: string;
  updated_at: string;
}

export interface DispatchEvent {
  id: number;
  relief_order_id: number;
  event_type: string;
  previous_status: string | null;
  new_status: string | null;
  description: string | null;
  event_metadata: Record<string, unknown>;
  created_at: string;
}

export interface DispatchMovement {
  id: number;
  relief_order_id: number;
  supply_type: SupplyType;
  quantity: number;
  movement_type: 'reserved' | 'dispatched' | 'delivered' | 'reservation_released';
  created_at: string;
}

export interface DispatchOrderDetail {
  data_mode: DataMode;
  order: DispatchOrder;
  warehouse_name: string;
  relief_centre_name: string;
  vehicle: DispatchVehicleBrief | null;
  route: Record<string, unknown>;
  events: DispatchEvent[];
  inventory_movements: DispatchMovement[];
}

export interface GeneratedOrderBrief {
  order_id: number;
  order_code: string;
  warehouse_id: number;
  warehouse_name: string;
  relief_centre_id: number;
  relief_centre_name: string;
  items: Record<string, number>;
  cargo_weight_kg: number;
  route_reachable: boolean;
  estimated_travel_time_minutes: number;
}

export interface SkippedShipment {
  warehouse_id: number;
  warehouse_name: string;
  relief_centre_id: number;
  relief_centre_name: string;
  reason: string;
}

export interface GenerateOrdersResponse {
  data_mode: DataMode;
  planning_run_id: number;
  generated: GeneratedOrderBrief[];
  existing: GeneratedOrderBrief[];
  skipped: SkippedShipment[];
  message: string;
}

export interface AssignmentCandidate {
  vehicle_id: number;
  vehicle_code: string;
  vehicle_type: VehicleType;
  capacity_kg: number;
  cargo_weight_kg: number;
}

export interface AssignVehicleResponse {
  data_mode: DataMode;
  order_id: number;
  order_code: string;
  assigned: boolean;
  auto_selected: boolean;
  vehicle: DispatchVehicleBrief | null;
  previous_vehicle_id: number | null;
  cargo_weight_kg: number;
  reason: string | null;
  candidates_considered: AssignmentCandidate[];
}

export interface FleetVehicleOverview {
  id: number;
  vehicle_code: string;
  vehicle_type: VehicleType;
  capacity: number;
  capacity_kg: number | null;
  status: VehicleStatus;
  current_location: string;
  active_order_code: string | null;
  active_order_id: number | null;
}

export interface FleetOverviewResponse {
  data_mode: DataMode;
  total_vehicles: number;
  available: number;
  assigned: number;
  in_transit: number;
  under_maintenance: number;
  delayed: number;
  total_capacity_kg_available: number;
  vehicles: FleetVehicleOverview[];
}

export interface TrackingSegment {
  segment_id: number;
  from_node_name: string;
  to_node_name: string;
  distance_km: number;
  estimated_travel_time_minutes: number;
  risk_factor: number;
  traversed: boolean;
}

export interface TrackingResponse {
  data_mode: DataMode;
  order_id: number;
  order_code: string;
  status: OrderStatus;
  vehicle_code: string | null;
  origin: string;
  destination: string;
  total_distance_km: number;
  estimated_travel_time_minutes: number;
  progress_minutes: number;
  progress_percent: number;
  progress_km: number;
  current_latitude: number | null;
  current_longitude: number | null;
  current_node_name: string | null;
  remaining_travel_time_minutes: number;
  delayed: boolean;
  last_updated_at: string;
  segments: TrackingSegment[];
}

export interface RouteConfirmationResponse {
  data_mode: DataMode;
  order_id: number;
  order_code: string;
  status: OrderStatus;
  route_updated: boolean;
  route: Record<string, unknown>;
  message: string;
}

export interface DispatchSummaryResponse {
  data_mode: DataMode;
  total_orders: number;
  awaiting_approval: number;
  approved: number;
  dispatched: number;
  in_transit: number;
  delayed: number;
  delivered: number;
  cancelled: number;
  total_cargo_weight_dispatched_kg: number;
  successful_deliveries: number;
  delivery_completion_percent: number;
  vehicles_assigned: number;
  vehicles_available: number;
  total_inventory_reserved: number;
}

// -------------------------------------------------------------------- simulation

export type SimulationEventType =
  | 'bridge_collapse'
  | 'road_blocked'
  | 'warehouse_unavailable'
  | 'relief_centre_water_shortage'
  | 'new_flood_report'
  | 'rainfall_escalation'
  | 'vehicle_breakdown';

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
  warehouse_id?: number;
  relief_centre_id?: number;
  vehicle_id?: number;
  incident_id?: number;
  event_data?: Record<string, unknown>;
}

export interface SimulationEvent {
  id: number;
  event_type: SimulationEventType;
  title: string;
  description: string;
  location_name: string | null;
  latitude: number | null;
  longitude: number | null;
  affected_entity_type: string | null;
  affected_entity_id: number | null;
  severity: Severity;
  event_data: Record<string, unknown>;
  is_demo: boolean;
  created_at: string;
}

export interface SimulationEventResult {
  data_mode: DataMode;
  message: string;
  changes: string[];
  event: SimulationEvent;
}

export interface SimulationResetResponse {
  data_mode: DataMode;
  message: string;
  counts: Record<string, number>;
  reset_at: string;
}

// -------------------------------------------------------------------- agent (Groq)

export interface ToolCallTrace {
  tool_name: string;
  status: 'success' | 'error';
  execution_time_ms: number;
  summary: string;
}

export interface AgentChatResponse {
  data_mode: DataMode;
  session_id: number;
  run_id: number;
  status: 'completed' | 'failed';
  assistant_message: string;
  tool_calls: ToolCallTrace[];
  created_at: string;
}

export interface AgentSessionSummary {
  session_id: number;
  session_title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface AgentMessageView {
  role: 'user' | 'assistant' | 'system';
  content: string;
  created_at: string;
}

export interface AgentRunSummary {
  run_id: number;
  status: 'running' | 'completed' | 'failed';
  model_name: string;
  tool_call_count: number;
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface AgentSessionDetail extends AgentSessionSummary {
  messages: AgentMessageView[];
  runs: AgentRunSummary[];
}

export interface AgentToolExecutionView {
  tool_name: string;
  status: 'success' | 'error';
  arguments_json: Record<string, unknown>;
  result_json: Record<string, unknown>;
  result_summary: string | null;
  execution_time_ms: number;
  created_at: string;
}

export interface AgentRunDetail {
  run_id: number;
  session_id: number;
  status: 'running' | 'completed' | 'failed';
  model_name: string;
  user_message: string;
  assistant_message: string | null;
  tool_call_count: number;
  tool_executions: AgentToolExecutionView[];
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface AgentStatusResponse {
  provider: 'groq';
  model: string;
  api_key_configured: boolean;
  ai_enabled: boolean;
  status: 'ready' | 'not_configured';
}

// ------------------------------------------------------------------- errors

export interface ApiErrorInfo {
  code: string;
  message: string;
  details?: unknown;
}
