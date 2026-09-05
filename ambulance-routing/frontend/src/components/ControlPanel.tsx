import { useEffect, useState } from "react";
import type { LatLng } from "../types";

interface ControlPanelProps {
  ambulancePos: LatLng;
  onPositionChange: (pos: LatLng) => void;
  alphaEmergency: number;
  onAlphaChange: (alpha: number) => void;
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
  alphaEmergency,
  onAlphaChange,
  onDispatch,
  loading,
}: ControlPanelProps) {
  const [latInput, setLatInput] = useState(ambulancePos.lat.toFixed(6));
  const [lngInput, setLngInput] = useState(ambulancePos.lng.toFixed(6));

  useEffect(() => {
    setLatInput(ambulancePos.lat.toFixed(6));
    setLngInput(ambulancePos.lng.toFixed(6));
  }, [ambulancePos]);

  function applyCoords() {
    const lat = parseFloat(latInput);
    const lng = parseFloat(lngInput);
    if (Number.isFinite(lat) && Number.isFinite(lng)) {
      onPositionChange({ lat, lng });
    }
  }

  return (
    <section className="panel">
      <h2 className="panel__title">Dispatch</h2>

      <div className="field-group">
        <label className="field-label" htmlFor="lat-input">
          Ambulance coordinates
        </label>
        <div className="coord-row">
          <input
            id="lat-input"
            className="input input--mono"
            value={latInput}
            onChange={(e) => setLatInput(e.target.value)}
            onBlur={applyCoords}
            placeholder="Latitude"
            inputMode="decimal"
          />
          <input
            className="input input--mono"
            value={lngInput}
            onChange={(e) => setLngInput(e.target.value)}
            onBlur={applyCoords}
            placeholder="Longitude"
            inputMode="decimal"
          />
        </div>
        <p className="field-hint">Click anywhere on the map to set this instead.</p>
      </div>

      <div className="field-group">
        <label className="field-label">Emergency priority</label>
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
        onClick={onDispatch}
        disabled={loading}
      >
        {loading ? "Calculating route…" : "Calculate best route"}
      </button>
    </section>
  );
}
