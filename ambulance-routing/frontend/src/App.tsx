import { useEffect, useState } from "react";
import { MapView } from "./components/MapView";
import { ControlPanel } from "./components/ControlPanel";
import { HospitalInfoPanel } from "./components/HospitalInfoPanel";
import { StatusBar } from "./components/StatusBar";
import { useHospitals } from "./hooks/useHospitals";
import { useRoute } from "./hooks/useRoute";
import { fetchHealth } from "./api/client";
import type { HealthResponse, HospitalListItem, LatLng } from "./types";

const DEFAULT_AMBULANCE_POS: LatLng = { lat: 19.076, lng: 72.8777 }; // central Mumbai

export default function App() {
  const [ambulancePos, setAmbulancePos] = useState<LatLng>(DEFAULT_AMBULANCE_POS);
  const [alphaEmergency, setAlphaEmergency] = useState(1.5);
  const [selectedHospitalId, setSelectedHospitalId] = useState<string | null>(null);

  const { hospitals, loading: hospitalsLoading } = useHospitals();
  const { route, loading: routeLoading, error, dispatch } = useRoute();

  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);

  useEffect(() => {
    fetchHealth()
      .then(setHealth)
      .catch((err) => setHealthError(err.message ?? "unreachable"));
  }, []);

  useEffect(() => {
    if (route) setSelectedHospitalId(route.hospital.id);
  }, [route]);

  function handleDispatch() {
    dispatch({
      latitude: ambulancePos.lat,
      longitude: ambulancePos.lng,
      alpha_emergency: alphaEmergency,
    });
  }

  function handleHospitalClick(hospital: HospitalListItem) {
    setSelectedHospitalId(hospital.id);
  }

  return (
    <div className="app-shell">
      <StatusBar health={health} healthError={healthError} hospitalCount={hospitals.length} />

      <div className="app-body">
        <aside className="sidebar">
          <ControlPanel
            ambulancePos={ambulancePos}
            onPositionChange={setAmbulancePos}
            alphaEmergency={alphaEmergency}
            onAlphaChange={setAlphaEmergency}
            onDispatch={handleDispatch}
            loading={routeLoading}
          />
          <HospitalInfoPanel route={route} error={error} />
        </aside>

        <main className="map-pane">
          {hospitalsLoading && <div className="map-loading-overlay">Loading hospitals…</div>}
          <MapView
            ambulancePos={ambulancePos}
            onMapClick={setAmbulancePos}
            hospitals={hospitals}
            selectedHospitalId={selectedHospitalId}
            route={route}
            onHospitalClick={handleHospitalClick}
          />
        </main>
      </div>
    </div>
  );
}
