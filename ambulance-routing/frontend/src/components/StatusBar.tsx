<<<<<<< HEAD
import type { FleetSummary, HealthResponse } from "../types";
=======
import type { HealthResponse } from "../types";
>>>>>>> da3cfbcd28d6553d843ed02f67732fb3b002d2ad

interface StatusBarProps {
  health: HealthResponse | null;
  healthError: string | null;
  hospitalCount: number;
<<<<<<< HEAD
  fleetSummary?: FleetSummary | null;
  fleetCount?: number;
  availableCount?: number;
  busyCount?: number;
  dispatchedCount?: number;
=======
>>>>>>> da3cfbcd28d6553d843ed02f67732fb3b002d2ad
}

function Dot({ ok }: { ok: boolean }) {
  return <span className={"status-dot " + (ok ? "status-dot--ok" : "status-dot--bad")} />;
}

<<<<<<< HEAD
export function StatusBar({
  health,
  healthError,
  hospitalCount,
  fleetSummary,
  fleetCount = 0,
  availableCount = 0,
  busyCount = 0,
  dispatchedCount = 0,
}: StatusBarProps) {
  const backendUp = !!health && !healthError;

  const total = fleetSummary?.total ?? fleetCount;
  const roaming = fleetSummary?.roaming ?? 0;
  const standby = fleetSummary?.standby ?? 0;
  const available = fleetSummary?.available ?? availableCount;
  const dispatched = fleetSummary?.dispatched ?? dispatchedCount;
  const withPatient = fleetSummary?.with_patient ?? busyCount;

=======
export function StatusBar({ health, healthError, hospitalCount }: StatusBarProps) {
  const backendUp = !!health && !healthError;

>>>>>>> da3cfbcd28d6553d843ed02f67732fb3b002d2ad
  return (
    <header className="status-bar">
      <div className="status-bar__brand">
        <span className="status-bar__mark">RESQROUTE</span>
<<<<<<< HEAD
        <span className="status-bar__subtitle">Mumbai Fleet Dispatch Simulation</span>
=======
        <span className="status-bar__subtitle">Mumbai Ambulance Dispatch</span>
>>>>>>> da3cfbcd28d6553d843ed02f67732fb3b002d2ad
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
<<<<<<< HEAD

        {total > 0 && (
          <div
            className="status-metric"
            style={{
              background: "rgba(255, 255, 255, 0.06)",
              padding: "4px 10px",
              borderRadius: "5px",
              border: "1px solid rgba(255, 255, 255, 0.12)",
              display: "flex",
              alignItems: "center",
              gap: "6px",
            }}
          >
            <span>🚑 <strong>{total} Total</strong></span>
            <span style={{ color: "#555" }}>|</span>
            <span style={{ color: "#35D48C" }}><strong>{roaming}</strong> Roaming</span>
            <span style={{ color: "#555" }}>|</span>
            <span style={{ color: "#4FA8FF" }}><strong>{standby}</strong> Standby</span>
            <span style={{ color: "#555" }}>|</span>
            <span style={{ color: "#35D48C" }}><strong>{available}</strong> Avail</span>
            <span style={{ color: "#555" }}>|</span>
            <span style={{ color: "#FFAA00" }}><strong>{dispatched}</strong> Dispatched</span>
            <span style={{ color: "#555" }}>|</span>
            <span style={{ color: "#FF4D5E" }}><strong>{withPatient}</strong> Patient</span>
          </div>
        )}
=======
>>>>>>> da3cfbcd28d6553d843ed02f67732fb3b002d2ad
      </div>
    </header>
  );
}
<<<<<<< HEAD

=======
>>>>>>> da3cfbcd28d6553d843ed02f67732fb3b002d2ad
