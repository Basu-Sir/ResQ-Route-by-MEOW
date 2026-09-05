// Mirrors backend/models.py exactly. Keep in sync with the FastAPI schema.

export interface HospitalOut {
  id: string;
  name: string;
  latitude: number;
  longitude: number;
  sumo_node_id: string;
  icu_beds: number;
}

// Slim shape returned by GET /hospitals — no sumo_node_id, since the
// browser never needs to address SUMO internals directly.
export interface HospitalListItem {
  id: string;
  name: string;
  latitude: number;
  longitude: number;
  icu_beds: number;
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
}

export interface LatLng {
  lat: number;
  lng: number;
}
