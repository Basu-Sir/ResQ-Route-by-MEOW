// Mirrors backend/models.py exactly. Keep in sync with the FastAPI schema.

export interface HospitalOut {
  id: string;
  name: string;
  latitude: number;
  longitude: number;
  sumo_node_id: string;
  icu_beds: number;
  emergency_doctors: number;
}

// Slim shape returned by GET /hospitals — no sumo_node_id, since the
// browser never needs to address SUMO internals directly.
export interface HospitalListItem {
  id: string;
  name: string;
  latitude: number;
  longitude: number;
  icu_beds: number;
  emergency_doctors: number;
}

export interface RouteRequest {
  latitude: number;
  longitude: number;
  alpha_emergency: number;
}

// [longitude, latitude] pairs, in path order — GeoJSON LineString style.
export type RouteGeometry = [number, number][];

export interface RouteResponse {
  hospital: HospitalOut;
  route_edge_ids: string[];
  distance_meters: number;
  estimated_travel_time_seconds: number;
  traffic_source: "redis" | "fallback" | "static" | string;
  source_node_id: string;
  alpha_emergency: number;
  route_geometry: RouteGeometry;
}

export interface HealthResponse {
  status: string;
  graph_loaded: boolean;
  graph_nodes: number | null;
  graph_edges: number | null;
  redis_connected: boolean;
  hospitals_loaded: number | null;
  ambulances_loaded?: number | null;
}

export interface LatLng {
  lat: number;
  lng: number;
}

export type AmbulanceStatus = "AVAILABLE" | "BUSY" | "DISPATCHED";

export interface AmbulanceDestination {
  hospital_id: string;
  hospital_name: string;
  latitude: number;
  longitude: number;
}

export interface AmbulanceState {
  ambulance_id: string;
  latitude: number;
  longitude: number;
  status: AmbulanceStatus;
  has_patient: boolean;
  is_roaming?: boolean;
  destination: AmbulanceDestination | null;
  eta_seconds: number | null;
  remaining_distance_meters?: number | null;
  route_geometry: RouteGeometry;
  traffic_source?: string | null;
  traffic_condition?: string | null;
  patient_delivered?: boolean;
  delivered_hospital_name?: string | null;
}


export interface AmbulanceDispatchRequest {
  hospital_id?: string;
  has_patient?: boolean;
  alpha_emergency?: number;
}

export interface EmergencyRequest {
  latitude: number;
  longitude: number;
  alpha_emergency: number;
}

export interface EmergencyResponse {
  ambulance: AmbulanceState;
  travel_time_seconds: number;
  distance_meters: number;
  patient_latitude: number;
  patient_longitude: number;
}

export interface FleetSummary {
  total: number;
  roaming: number;
  standby: number;
  available: number;
  dispatched: number;
  with_patient: number;
}

export interface CongestedSegment {
  edge_id: string;
  level: "HEAVY" | "MODERATE";
  speed_kmh: number;
  normal_speed_kmh: number;
  congestion_ratio: number;
  geometry: [number, number][]; // [lon, lat][]
}

export interface TrafficCongestionResponse {
  total_congested_segments: number;
  heavy_count: number;
  moderate_count: number;
  source: string;
  segments: CongestedSegment[];
}

