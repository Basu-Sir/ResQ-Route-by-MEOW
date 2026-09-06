import { useEffect, useState } from "react";
import { MapView } from "./components/MapView";
import { ControlPanel } from "./components/ControlPanel";
import { HospitalInfoPanel } from "./components/HospitalInfoPanel";
import { StatusBar } from "./components/StatusBar";
import { useHospitals } from "./hooks/useHospitals";
import { useAmbulances } from "./hooks/useAmbulances";
import { useRoute } from "./hooks/useRoute";
import { useTrafficCongestion } from "./hooks/useTrafficCongestion";
import { fetchHealth, requestEmergencyAmbulance } from "./api/client";
import type { EmergencyResponse, HealthResponse, HospitalListItem, LatLng } from "./types";

const DEFAULT_AMBULANCE_POS: LatLng = { lat: 19.076, lng: 72.8777 }; // central Mumbai
const DEFAULT_PATIENT_POS: LatLng = DEFAULT_AMBULANCE_POS;

export default function App() {
  const [ambulancePos, setAmbulancePos] = useState<LatLng>(DEFAULT_AMBULANCE_POS);
  const [patientPos, setPatientPos] = useState<LatLng>(DEFAULT_PATIENT_POS);
  const [patientActive, setPatientActive] = useState(false);
  const [alphaEmergency, setAlphaEmergency] = useState(1.5);
  const [selectedHospitalId, setSelectedHospitalId] = useState<string | null>(null);
  const [lastEmergency, setLastEmergency] = useState<EmergencyResponse | null>(null);
  const [emergencyLoading, setEmergencyLoading] = useState(false);
  const [emergencyError, setEmergencyError] = useState<string | null>(null);

  const { hospitals, loading: hospitalsLoading, refresh: refreshHospitals } = useHospitals();
  const { ambulances: fleetAmbulances, summary, refresh: refreshAmbulances } = useAmbulances();
  const { route, loading: routeLoading, error, dispatch } = useRoute();
  const { congestion, loading: trafficLoading, reseed: reseedTraffic } = useTrafficCongestion();


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
    if (current) {
      if (current.patient_delivered || (lastEmergency.ambulance.has_patient && !current.has_patient)) {
        setPatientActive(false);
      }
      if (!lastEmergency.ambulance.patient_delivered && current.patient_delivered) {
        refreshHospitals();
      }
      if (
        current.latitude !== lastEmergency.ambulance.latitude ||
        current.longitude !== lastEmergency.ambulance.longitude ||
        current.status !== lastEmergency.ambulance.status ||
        current.has_patient !== lastEmergency.ambulance.has_patient ||
        current.patient_delivered !== lastEmergency.ambulance.patient_delivered ||
        current.delivered_hospital_name !== lastEmergency.ambulance.delivered_hospital_name ||
        current.eta_seconds !== lastEmergency.ambulance.eta_seconds ||
        current.remaining_distance_meters !== lastEmergency.ambulance.remaining_distance_meters ||
        current.destination?.hospital_id !== lastEmergency.ambulance.destination?.hospital_id ||
        current.traffic_source !== lastEmergency.ambulance.traffic_source ||
        current.traffic_condition !== lastEmergency.ambulance.traffic_condition
      ) {
        setLastEmergency((prev) =>
          prev
            ? {
                ...prev,
                ambulance: current,
                travel_time_seconds: current.eta_seconds ?? prev.travel_time_seconds,
                distance_meters: current.remaining_distance_meters ?? prev.distance_meters,
              }
            : null
        );
      }
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
      setPatientActive(true);
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
    setPatientActive(true);
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
        congestionData={congestion}
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
            onClearEmergency={() => {
              setLastEmergency(null);
              setPatientActive(false);
            }}
            onDispatch={handleDispatchRoute}
            loading={routeLoading}
          />
          <HospitalInfoPanel route={route} error={error} />
        </aside>

        <main className="map-pane">
          {hospitalsLoading && <div className="map-loading-overlay">Loading hospitals…</div>}
          <MapView
            ambulancePos={ambulancePos}
            patientLocation={
              patientActive && !lastEmergency?.ambulance.patient_delivered
                ? lastEmergency?.ambulance.has_patient
                  ? {
                      lat: lastEmergency.ambulance.latitude,
                      lng: lastEmergency.ambulance.longitude,
                    }
                  : patientPos
                : null
            }
            onMapClick={handleMapClick}
            hospitals={hospitals}
            selectedHospitalId={selectedHospitalId}
            route={route}
            onHospitalClick={handleHospitalClick}
            fleetAmbulances={fleetAmbulances}
            congestionData={congestion}
            onReseedTraffic={reseedTraffic}
            isTrafficLoading={trafficLoading}
          />
        </main>
      </div>
    </div>

  );
}
