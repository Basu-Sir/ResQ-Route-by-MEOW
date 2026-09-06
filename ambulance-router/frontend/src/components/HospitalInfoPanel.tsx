import type { RouteResponse } from "../types";

interface HospitalInfoPanelProps {
  route: RouteResponse | null;
  error: string | null;
}

function formatDistance(meters: number): string {
  if (meters >= 1000) return `${(meters / 1000).toFixed(2)} km`;
  return `${meters.toFixed(0)} m`;
}

function formatDuration(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = Math.round(seconds % 60);
  if (mins === 0) return `${secs}s`;
  return `${mins}m ${secs}s`;
}

const TRAFFIC_LABEL: Record<string, string> = {
  redis: "Live (Redis)",
  fallback: "Fallback feed",
  static: "Static speeds",
};

export function HospitalInfoPanel({ route, error }: HospitalInfoPanelProps) {
  if (error) {
    return (
      <section className="panel panel--error">
        <h2 className="panel__title">Route unavailable</h2>
        <p className="error-message">{error}</p>
      </section>
    );
  }

  if (!route) {
    return (
      <section className="panel panel--empty">
        <h2 className="panel__title">Selected hospital</h2>
        <p className="empty-hint">
          Set the ambulance position and calculate a route to see hospital and
          ETA details here.
        </p>
      </section>
    );
  }

  const { hospital } = route;
  const trafficLabel = TRAFFIC_LABEL[route.traffic_source] ?? route.traffic_source;

  return (
    <section className="panel">
      <h2 className="panel__title">Selected hospital</h2>

      <div className="hospital-card">
        <h3 className="hospital-card__name">{hospital.name}</h3>
        <div className="stat-grid">
          <div className="stat">
            <span className="stat__label">ICU beds</span>
            <span className={hospital.icu_beds > 0 ? "stat__value value-ok" : "stat__value value-critical"}>
              {hospital.icu_beds}
            </span>
          </div>
          <div className="stat">
            <span className="stat__label">Emergency doctors</span>
            <span className={hospital.emergency_doctors > 0 ? "stat__value value-ok" : "stat__value value-critical"}>
              {hospital.emergency_doctors}
            </span>
          </div>
          <div className="stat">
            <span className="stat__label">Distance</span>
            <span className="stat__value value-mono">{formatDistance(route.distance_meters)}</span>
          </div>
          <div className="stat">
            <span className="stat__label">ETA</span>
            <span className="stat__value value-mono">
              {formatDuration(route.estimated_travel_time_seconds)}
            </span>
          </div>
          <div className="stat">
            <span className="stat__label">Traffic source</span>
            <span className="stat__value">{trafficLabel}</span>
          </div>
        </div>

        <div className="route-meta">
          <div className="route-meta__row">
            <span>Priority (alpha)</span>
            <span className="value-mono">{route.alpha_emergency.toFixed(2)}</span>
          </div>
          <div className="route-meta__row">
            <span>Route edges</span>
            <span className="value-mono">{route.route_edge_ids.length}</span>
          </div>
          <div className="route-meta__row">
            <span>Source node</span>
            <span className="value-mono">{route.source_node_id}</span>
          </div>
        </div>
      </div>
    </section>
  );
}
