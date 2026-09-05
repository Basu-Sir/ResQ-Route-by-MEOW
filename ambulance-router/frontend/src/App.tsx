import { useEffect, useState } from "react";
import { MapView } from "./components/MapView";
import { ControlPanel } from "./components/ControlPanel";
import { HospitalInfoPanel } from "./components/HospitalInfoPanel";
import { StatusBar } from "./components/StatusBar";
import { useHospitals } from "./hooks/useHospitals";
import { useAmbulances } from "./hooks/useAmbulances";
import { useRoute } from "./hooks/useRoute";
import { fetchHealth, requestEmergencyAmbulance } from "./api/client";
import type { EmergencyResponse, HealthResponse, HospitalListItem, LatLng } from "./types";

const DEFAULT_AMBULANCE_POS: LatLng = { lat: 19.076, lng: 72.8777 }; // central Mumbai
const DEFAULT_PATIENT_POS: LatLng = DEFAULT_AMBULANCE_POS;

export default function App() {
  const [ambulancePos, setAmbulancePos] = useState<LatLng>(DEFAULT_AMBULANCE_POS);
  const [patientPos, setPatientPos] = useState<LatLng>(DEFAULT_PATIENT_POS);
  const [alphaEmergency, setAlphaEmergency] = useState(1.5);
  const [selectedHospitalId, setSelectedHospitalId] = useState<string | null>(null);
  const [lastEmergency, setLastEmergency] = useState<EmergencyResponse | null>(null);
  const [emergencyLoading, setEmergencyLoading] = useState(false);
  const [emergencyError, setEmergencyError] = useState<string | null>(null);

  const { hospitals, loading: hospitalsLoading } = useHospitals();
  const { ambulances: fleetAmbulances, summary, refresh: refreshAmbulances } = useAmbulances();
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

  // Keep lastEmergency updated if the selected ambulance updates during polling
  useEffect(() => {
    if (!lastEmergency) return;
    const current = fleetAmbulances.find(
      (a) => a.ambulance_id === lastEmergency.ambulance.ambulance_id
    );
    if (current && (current.status !== lastEmergency.ambulance.status || current.has_patient !== lastEmergency.ambulance.has_patient)) {
      setLastEmergency((prev) => (prev ? { ...prev, ambulance: current } : null));
    }
  }, [fleetAmbulances, lastEmergency]);

  async function handleRequestAmbulance() {
    setEmergencyLoading(true);
    setEmergencyError(null);
    try {
      const resp = await requestEmergencyAmbulance({
        latitude: patientPos.lat,
        longitude: patientPos.lng,
        alpha_emergency: alphaEmergency,
      });
      setLastEmergency(resp);
      // Immediately refresh fleet so marker reflects dispatched status right away
      refreshAmbulances();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to dispatch ambulance";
      setEmergencyError(msg);
    } finally {
      setEmergencyLoading(false);
    }
  }

  function handleDispatchRoute() {
    dispatch({
      latitude: ambulancePos.lat,
      longitude: ambulancePos.lng,
      alpha_emergency: alphaEmergency,
    });
  }

  function handleHospitalClick(hospital: HospitalListItem) {
    setSelectedHospitalId(hospital.id);
  }

  function handleMapClick(pos: LatLng) {
    setPatientPos(pos);
    setAmbulancePos(pos);
  }

  return (
    <div className="app-shell">
      <StatusBar
        health={health}
        healthError={healthError}
        hospitalCount={hospitals.length}
        fleetSummary={summary}
        fleetCount={fleetAmbulances.length}
      />

      <div className="app-body">
        <aside className="sidebar">
          <ControlPanel
            patientPos={patientPos}
            onPatientPosChange={setPatientPos}
            ambulancePos={ambulancePos}
            onPositionChange={setAmbulancePos}
            alphaEmergency={alphaEmergency}
            onAlphaChange={setAlphaEmergency}
            onRequestAmbulance={handleRequestAmbulance}
            requestLoading={emergencyLoading}
            lastEmergency={lastEmergency}
            emergencyError={emergencyError}
            onDispatch={handleDispatchRoute}
            loading={routeLoading}
          />
          <HospitalInfoPanel route={route} error={error} />
        </aside>

        <main className="map-pane">
          {hospitalsLoading && <div className="map-loading-overlay">Loading hospitals…</div>}
          <MapView
            ambulancePos={ambulancePos}
            patientLocation={lastEmergency ? { lat: lastEmergency.patient_latitude, lng: lastEmergency.patient_longitude } : patientPos}
            onMapClick={handleMapClick}
            hospitals={hospitals}
            selectedHospitalId={selectedHospitalId}
            route={route}
            onHospitalClick={handleHospitalClick}
            fleetAmbulances={fleetAmbulances}
          />
        </main>
      </div>
    </div>
  );
}
