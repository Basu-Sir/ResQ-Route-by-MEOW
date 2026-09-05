import type {
  AmbulanceDispatchRequest,
  AmbulanceState,
  EmergencyRequest,
  EmergencyResponse,
  FleetSummary,
  HealthResponse,
  HospitalListItem,
  RouteRequest,
  RouteResponse,
} from "../types";

// All calls go through /api, which vite.config.ts proxies to the existing
// FastAPI service at http://127.0.0.1:3000. Nothing here talks to SUMO,
// sumolib, or rustworkx directly — that all stays server-side.
const BASE_URL = "/api";

class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      // response wasn't JSON; fall back to statusText
    }
    throw new ApiError(res.status, detail);
  }

  return res.json() as Promise<T>;
}

/** POST /route — delegates entirely to the existing rustworkx routing pipeline. */
export function calculateRoute(payload: RouteRequest): Promise<RouteResponse> {
  return request<RouteResponse>("/route", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/** GET /hospitals — lightweight list for map markers, no SUMO internals. */
export function fetchHospitals(): Promise<HospitalListItem[]> {
  return request<HospitalListItem[]>("/hospitals");
}

/** GET /health — surfaces graph/Redis status in the ops status bar. */
export function fetchHealth(): Promise<HealthResponse> {
  return request<HealthResponse>("/health");
}

/** GET /ambulances — fetches all 30 simulated ambulances. */
export function fetchAmbulances(): Promise<AmbulanceState[]> {
  return request<AmbulanceState[]>("/ambulances");
}

/** GET /ambulances/summary — fetches fleet composition & state breakdown. */
export function fetchFleetSummary(): Promise<FleetSummary> {
  return request<FleetSummary>("/ambulances/summary");
}

/** GET /ambulances/:id — fetches a single ambulance. */
export function fetchAmbulance(id: string): Promise<AmbulanceState> {
  return request<AmbulanceState>(`/ambulances/${id}`);
}

/** POST /ambulances/:id/dispatch — dispatches an available ambulance. */
export function dispatchAmbulance(
  id: string,
  payload?: AmbulanceDispatchRequest
): Promise<AmbulanceState> {
  return request<AmbulanceState>(`/ambulances/${id}/dispatch`, {
    method: "POST",
    body: JSON.stringify(payload ?? {}),
  });
}

/** POST /ambulances/request — finds and dispatches closest available ambulance to patient. */
export function requestEmergencyAmbulance(
  payload: EmergencyRequest
): Promise<EmergencyResponse> {
  return request<EmergencyResponse>("/ambulances/request", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/** POST /ambulances/reset — resets fleet to initial state. */
export function resetAmbulances(): Promise<AmbulanceState[]> {
  return request<AmbulanceState[]>("/ambulances/reset", {
    method: "POST",
  });
}

export { ApiError };

