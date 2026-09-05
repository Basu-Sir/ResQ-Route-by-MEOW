import { useEffect, useState } from "react";
 
import type { EmergencyResponse, LatLng } from "../types";

interface ControlPanelProps {
  ambulancePos: LatLng;
  onPositionChange: (pos: LatLng) => void;
  patientPos: LatLng;
  onPatientPosChange: (pos: LatLng) => void;
  alphaEmergency: number;
  onAlphaChange: (alpha: number) => void;
  onRequestAmbulance: () => void;
  requestLoading: boolean;
  lastEmergency: EmergencyResponse | null;
  emergencyError: string | null;
  onDispatch: () => void;
  loading: boolean;
}

const PRIORITY_PRESETS = [
  { label: "Routine", value: 1.0, hint: "Standard road speeds" },
  { label: "Urgent", value: 1.5, hint: "Moderate priority routing" },
  { label: "Critical", value: 2.2, hint: "Maximum priority routing" },
];

export function ControlPanel({
  ambulancePos,
  onPositionChange,
  patientPos,
  onPatientPosChange,
  alphaEmergency,
  onAlphaChange,
  onRequestAmbulance,
  requestLoading,
  lastEmergency,
  emergencyError,
  onDispatch,
  loading,
}: ControlPanelProps) {
  // Emergency patient coordinates
  const [patLatInput, setPatLatInput] = useState(patientPos.lat.toFixed(6));
  const [patLngInput, setPatLngInput] = useState(patientPos.lng.toFixed(6));

  // Legacy single-ambulance coords
  const [latInput, setLatInput] = useState(ambulancePos.lat.toFixed(6));
  const [lngInput, setLngInput] = useState(ambulancePos.lng.toFixed(6));

  const [showDirectRoute, setShowDirectRoute] = useState(false);

  useEffect(() => {
    setPatLatInput(patientPos.lat.toFixed(6));
    setPatLngInput(patientPos.lng.toFixed(6));
  }, [patientPos]);

  useEffect(() => {
    setLatInput(ambulancePos.lat.toFixed(6));
    setLngInput(ambulancePos.lng.toFixed(6));
  }, [ambulancePos]);

  function applyPatientCoords() {
    const lat = parseFloat(patLatInput);
    const lng = parseFloat(patLngInput);
    if (Number.isFinite(lat) && Number.isFinite(lng)) {
      onPatientPosChange({ lat, lng });
    }
  }

  function applyAmbulanceCoords() {
    const lat = parseFloat(latInput);
    const lng = parseFloat(lngInput);
    if (Number.isFinite(lat) && Number.isFinite(lng)) {
      onPositionChange({ lat, lng });
    }
  }

  return (
    <div className="control-panels-container">
      {/* 1. Emergency Request Panel */}
      <section className="panel" style={{ borderBottom: "2px solid #263140" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "14px" }}>
          <h2 className="panel__title" style={{ margin: 0, color: "#FF4D5E", letterSpacing: "0.1em" }}>
            🚨 EMERGENCY DISPATCH
          </h2>
          <span style={{ fontSize: "11px", color: "#8895A3", background: "rgba(255, 77, 94, 0.12)", padding: "2px 6px", borderRadius: "3px" }}>
            Real-time
          </span>
        </div>

        <div className="field-group">
          <label className="field-label" htmlFor="pat-lat-input">
            Patient Location Coordinates
          </label>
          <div className="coord-row">
            <input
              id="pat-lat-input"
              className="input input--mono"
              value={patLatInput}
              onChange={(e) => setPatLatInput(e.target.value)}
              onBlur={applyPatientCoords}
              placeholder="Patient Latitude"
              inputMode="decimal"
            />
            <input
              className="input input--mono"
              value={patLngInput}
              onChange={(e) => setPatLngInput(e.target.value)}
              onBlur={applyPatientCoords}
              placeholder="Patient Longitude"
              inputMode="decimal"
            />
          </div>
          <p className="field-hint">Click anywhere on the map or type to set patient location.</p>
        </div>

        <div className="field-group">
          <label className="field-label">Emergency Priority (Alpha)</label>
          <div className="priority-group">
            {PRIORITY_PRESETS.map((preset) => (
              <button
                key={preset.label}
                type="button"
                className={
                  "priority-btn" +
                  (Math.abs(alphaEmergency - preset.value) < 0.01
                    ? " priority-btn--active"
                    : "")
                }
                onClick={() => onAlphaChange(preset.value)}
              >
                <span className="priority-btn__label">{preset.label}</span>
                <span className="priority-btn__hint">{preset.hint}</span>
              </button>
            ))}
          </div>
          <div className="alpha-readout">
            alpha_emergency = <span className="value-mono">{alphaEmergency.toFixed(2)}</span>
          </div>
        </div>

        <button
          type="button"
          className="dispatch-btn"
          style={{ background: "#FF4D5E", color: "#FFF", fontWeight: 700, fontSize: "14px" }}
          onClick={onRequestAmbulance}
          disabled={requestLoading}
        >
          {requestLoading ? "Finding closest ambulance…" : "🚨 REQUEST AMBULANCE"}
        </button>

        {emergencyError && (
          <div style={{ marginTop: "12px", padding: "8px 12px", background: "rgba(255, 77, 94, 0.15)", borderRadius: "4px", border: "1px solid #FF4D5E", color: "#FF8591", fontSize: "12px" }}>
            ❌ {emergencyError}
          </div>
        )}

        {/* Selected Ambulance Result Card */}
        {lastEmergency && (
          <div
            style={{
              marginTop: "16px",
              padding: "14px",
              background: "rgba(38, 49, 64, 0.5)",
              borderRadius: "6px",
              border: "1px solid #35D48C",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "10px" }}>
              <strong style={{ fontSize: "14px", color: "#35D48C" }}>
                🚑 {lastEmergency.ambulance.ambulance_id} Assigned
              </strong>
              <span
                style={{
                  fontSize: "11px",
                  padding: "2px 6px",
                  borderRadius: "4px",
                  background: "#FFAA00",
                  color: "#0A0E14",
                  fontWeight: "bold",
                }}
              >
                {lastEmergency.ambulance.status}
              </span>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px", fontSize: "12px" }}>
              <div>
                <span style={{ color: "#8895A3" }}>ETA:</span>{" "}
                <strong style={{ color: "#FFF" }}>
                  {Math.round(lastEmergency.travel_time_seconds)}s (
                  {Math.ceil(lastEmergency.travel_time_seconds / 60)} min)
                </strong>
              </div>
              <div>
                <span style={{ color: "#8895A3" }}>Distance:</span>{" "}
                <strong style={{ color: "#FFF" }}>
                  {(lastEmergency.distance_meters / 1000).toFixed(2)} km
                </strong>
              </div>
              <div>
                <span style={{ color: "#8895A3" }}>Origin Mode:</span>{" "}
                <span style={{ color: "#FFF" }}>
                  {lastEmergency.ambulance.is_roaming ? "⚡ Roaming Patrol" : "🅿️ Standby Base"}
                </span>
              </div>
              <div>
                <span style={{ color: "#8895A3" }}>Patient Status:</span>{" "}
                <span style={{ color: lastEmergency.ambulance.has_patient ? "#FF4D5E" : "#35D48C" }}>
                  {lastEmergency.ambulance.has_patient ? "🚨 Picked Up" : "En Route"}
                </span>
              </div>
            </div>
          </div>
        )}
      </section>

      {/* 2. Direct Hospital Route Section (POST /route) */}
      <section className="panel">
        <button
          type="button"
          onClick={() => setShowDirectRoute(!showDirectRoute)}
          style={{
            background: "none",
            border: "none",
            color: "#8895A3",
            padding: 0,
            cursor: "pointer",
            display: "flex",
            justifyContent: "space-between",
            width: "100%",
            alignItems: "center",
          }}
        >
          <h3 className="panel__title" style={{ margin: 0, fontSize: "11px" }}>
            🏥 HOSPITAL ROUTE FINDER (POST /route)
          </h3>
          <span style={{ fontSize: "12px" }}>{showDirectRoute ? "▲" : "▼"}</span>
        </button>

        {showDirectRoute && (
          <div style={{ marginTop: "14px" }}>
            <div className="field-group">
              <label className="field-label" htmlFor="amb-lat-input">
                Origin Coordinates
              </label>
              <div className="coord-row">
                <input
                  id="amb-lat-input"
                  className="input input--mono"
                  value={latInput}
                  onChange={(e) => setLatInput(e.target.value)}
                  onBlur={applyAmbulanceCoords}
                  placeholder="Latitude"
                  inputMode="decimal"
                />
                <input
                  className="input input--mono"
                  value={lngInput}
                  onChange={(e) => setLngInput(e.target.value)}
                  onBlur={applyAmbulanceCoords}
                  placeholder="Longitude"
                  inputMode="decimal"
                />
              </div>
            </div>

            <button
              type="button"
              className="dispatch-btn"
              onClick={onDispatch}
              disabled={loading}
              style={{ background: "#263140", color: "#FFF", border: "1px solid #4FA8FF" }}
            >
              {loading ? "Calculating route…" : "Find Closest Hospital"}
            </button>
          </div>
        )}
      </section>
    </div>
  );
}
