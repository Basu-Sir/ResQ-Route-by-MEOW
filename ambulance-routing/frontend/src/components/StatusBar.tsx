import type { HealthResponse } from "../types";

interface StatusBarProps {
  health: HealthResponse | null;
  healthError: string | null;
  hospitalCount: number;
}

function Dot({ ok }: { ok: boolean }) {
  return <span className={"status-dot " + (ok ? "status-dot--ok" : "status-dot--bad")} />;
}

export function StatusBar({ health, healthError, hospitalCount }: StatusBarProps) {
  const backendUp = !!health && !healthError;

  return (
    <header className="status-bar">
      <div className="status-bar__brand">
        <span className="status-bar__mark">RESQROUTE</span>
        <span className="status-bar__subtitle">Mumbai Ambulance Dispatch</span>
      </div>

      <div className="status-bar__metrics">
        <div className="status-metric">
          <Dot ok={backendUp} />
          <span>{backendUp ? "Routing service online" : "Routing service unreachable"}</span>
        </div>

        {health?.graph_loaded && (
          <div className="status-metric">
            <span className="value-mono">
              {health.graph_nodes?.toLocaleString()} nodes / {health.graph_edges?.toLocaleString()} edges
            </span>
          </div>
        )}

        <div className="status-metric">
          <Dot ok={!!health?.redis_connected} />
          <span>{health?.redis_connected ? "Redis connected" : "Redis offline (fallback speeds)"}</span>
        </div>

        <div className="status-metric">
          <span className="value-mono">{hospitalCount}</span>
          <span>hospitals loaded</span>
        </div>
      </div>
    </header>
  );
}
