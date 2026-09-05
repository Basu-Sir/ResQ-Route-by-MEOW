import { useEffect, useMemo, useRef } from "react";
import {
  MapContainer,
  Marker,
  Polyline,
  Popup,
  TileLayer,
  useMapEvents,
} from "react-leaflet";
import MarkerClusterGroup from "react-leaflet-cluster";
import L, { type LatLngExpression, type LatLngBoundsExpression } from "leaflet";
import type { AmbulanceState, HospitalListItem, LatLng, RouteResponse } from "../types";

import "leaflet/dist/leaflet.css";
import "leaflet.markercluster/dist/MarkerCluster.css";
import "leaflet.markercluster/dist/MarkerCluster.Default.css";

const MUMBAI_CENTER: LatLngExpression = [19.076, 72.8777];

// Divisor of DOM icons rather than default Leaflet pin images (no extra
// image requests, easy to theme, and trivially cheap even in a cluster).
function pinIcon(color: string, size = 26) {
  return L.divIcon({
    className: "resqroute-pin",
    html: `<span style="
      display:block;width:${size}px;height:${size}px;
      background:${color};border:2px solid #0A0E14;border-radius:50% 50% 50% 0;
      transform:rotate(-45deg);box-shadow:0 2px 6px rgba(0,0,0,0.5);
    "></span>`,
    iconSize: [size, size],
    iconAnchor: [size / 2, size],
    popupAnchor: [0, -size],
  });
}

const ambulanceIcon = L.divIcon({
  className: "resqroute-ambulance",
  html: `<div style="
    width:30px;height:30px;border-radius:50%;
    background:#FF4D5E;border:3px solid #0A0E14;
    box-shadow:0 0 0 4px rgba(255,77,94,0.28), 0 2px 8px rgba(0,0,0,0.5);
    display:flex;align-items:center;justify-content:center;
    font-size:15px;
  ">🚑</div>`,
  iconSize: [30, 30],
  iconAnchor: [15, 15],
});

const hospitalIcon = pinIcon("#4FA8FF");
const selectedHospitalIcon = pinIcon("#35D48C", 32);

function getAmbulanceFleetIcon(status: string, hasPatient: boolean, isRoaming?: boolean) {
  const isWithPatient = hasPatient || status === "BUSY";
  const isDispatched = status === "DISPATCHED";
  
  // Green for Available (both roaming and standby), Orange for Dispatched, Red for Patient
  const color = isWithPatient ? "#FF4D5E" : isDispatched ? "#FFAA00" : "#35D48C";
  const glow = isWithPatient
    ? "rgba(255, 77, 94, 0.55)"
    : isDispatched
    ? "rgba(255, 170, 0, 0.55)"
    : "rgba(53, 212, 140, 0.45)";

  const badge = isWithPatient
    ? `<span style="position:absolute;top:-6px;right:-6px;font-size:11px;filter:drop-shadow(0 1px 2px rgba(0,0,0,0.8));">🚨</span>`
    : isRoaming
    ? `<span style="position:absolute;top:-5px;right:-5px;font-size:9px;background:#0A0E14;border:1px solid #35D48C;border-radius:3px;padding:0 2px;">⚡</span>`
    : "";

  return L.divIcon({
    className: `resqroute-fleet-amb resqroute-fleet-${status.toLowerCase()}`,
    html: `<div style="
      position:relative;width:28px;height:28px;border-radius:50%;
      background:${color};border:2px solid #0A0E14;
      box-shadow:0 0 0 3px ${glow}, 0 2px 6px rgba(0,0,0,0.5);
      display:flex;align-items:center;justify-content:center;
      font-size:13px;cursor:pointer;
    ">🚑${badge}</div>`,
    iconSize: [28, 28],
    iconAnchor: [14, 14],
    popupAnchor: [0, -14],
  });
}

const patientMarkerIcon = L.divIcon({
  className: "resqroute-patient-pin",
  html: `<div style="
    position:relative;width:34px;height:34px;border-radius:50%;
    background:#FF4D5E;border:3px solid #FFFFFF;
    box-shadow:0 0 0 4px rgba(255,77,94,0.45), 0 3px 12px rgba(0,0,0,0.7);
    display:flex;align-items:center;justify-content:center;
    font-size:16px;cursor:pointer;
  ">🆘<span style="
    position:absolute;bottom:-18px;left:50%;transform:translateX(-50%);
    background:#0A0E14;color:#FF4D5E;font-size:10px;font-weight:bold;
    padding:1px 5px;border-radius:3px;border:1px solid #FF4D5E;white-space:nowrap;
  ">PATIENT</span></div>`,
  iconSize: [34, 34],
  iconAnchor: [17, 17],
  popupAnchor: [0, -17],
});
interface MapClickHandlerProps {
  onMapClick: (pos: LatLng) => void;
}

function MapClickHandler({ onMapClick }: MapClickHandlerProps) {
  useMapEvents({
    click(e) {
      onMapClick({ lat: e.latlng.lat, lng: e.latlng.lng });
    },
  });
  return null;
}

interface FitToRouteProps {
  route: RouteResponse | null;
  ambulancePos: LatLng;
  routeLatLngs: LatLngExpression[];
}

/** Re-centers the map on the ambulance + selected hospital + route polyline whenever a new route arrives. */
function FitToRoute({ route, ambulancePos, routeLatLngs }: FitToRouteProps) {
  const map = useMapEvents({});
  const lastRouteRef = useRef<RouteResponse | null>(null);

  useEffect(() => {
    if (!route || route === lastRouteRef.current) return;
    lastRouteRef.current = route;

    const points: LatLngExpression[] = [
      [ambulancePos.lat, ambulancePos.lng],
      [route.hospital.latitude, route.hospital.longitude],
      ...routeLatLngs,
    ];
    const bounds = L.latLngBounds(points);
    map.fitBounds(bounds, { padding: [80, 80], maxZoom: 15 });
  }, [route, ambulancePos, routeLatLngs, map]);

  return null;
}

interface MapViewProps {
  ambulancePos: LatLng;
  patientLocation?: LatLng | null;
  onMapClick: (pos: LatLng) => void;
  hospitals: HospitalListItem[];
  selectedHospitalId: string | null;
  route: RouteResponse | null;
  onHospitalClick: (hospital: HospitalListItem) => void;
  fleetAmbulances?: AmbulanceState[];
  onAmbulanceClick?: (ambulance: AmbulanceState) => void;
}

export function MapView({
  ambulancePos,
  patientLocation,
  onMapClick,
  hospitals,
  selectedHospitalId,
  route,
  onHospitalClick,
  fleetAmbulances = [],
  onAmbulanceClick,
}: MapViewProps) {
  // route_geometry is [lon, lat][] (GeoJSON order) — Leaflet wants [lat, lon].
  const routeLatLngs: LatLngExpression[] = useMemo(() => {
    if (!route?.route_geometry?.length) return [];
    return route.route_geometry.map(([lon, lat]) => [lat, lon]);
  }, [route]);

  return (
    <MapContainer
      center={MUMBAI_CENTER}
      zoom={12}
      className="map-container"
      preferCanvas
    >
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        maxZoom={19}
      />

      <MapClickHandler onMapClick={onMapClick} />
      <FitToRoute route={route} ambulancePos={ambulancePos} routeLatLngs={routeLatLngs} />

      {/* Clustered so the browser never renders ~930 raw markers at once. */}
      <MarkerClusterGroup chunkedLoading maxClusterRadius={60} spiderfyOnMaxZoom>
        {hospitals.map((h) => (
          <Marker
            key={h.id}
            position={[h.latitude, h.longitude]}
            icon={h.id === selectedHospitalId ? selectedHospitalIcon : hospitalIcon}
            eventHandlers={{ click: () => onHospitalClick(h) }}
          >
            <Popup>
              <div className="hospital-popup">
                <strong>{h.name}</strong>
                <div className="hospital-popup__row">
                  <span>ICU beds</span>
                  <span className={h.icu_beds > 0 ? "value-ok" : "value-critical"}>
                    {h.icu_beds}
                  </span>
                </div>
              </div>
            </Popup>
          </Marker>
        ))}
      </MarkerClusterGroup>

      {/* Active route polylines for moving fleet ambulances */}
      {fleetAmbulances.map((amb) => {
        if (!amb.route_geometry || amb.route_geometry.length < 2) return null;
        const pts: LatLngExpression[] = amb.route_geometry.map(([lon, lat]) => [lat, lon]);
        const isWithPatient = amb.has_patient || amb.status === "BUSY";
        const isDispatched = amb.status === "DISPATCHED";
        const color = isWithPatient ? "#FF4D5E" : isDispatched ? "#FFAA00" : "#35D48C";

        return (
          <Polyline
            key={`fleet-route-${amb.ambulance_id}`}
            positions={pts}
            pathOptions={{
              color,
              weight: isDispatched ? 4 : 3,
              opacity: isDispatched ? 0.9 : 0.6,
              dashArray: isDispatched ? undefined : "5, 6",
            }}
          />
        );
      })}

      {/* 30 simulated fleet ambulances */}
      {fleetAmbulances.map((amb) => (
        <Marker
          key={amb.ambulance_id}
          position={[amb.latitude, amb.longitude]}
          icon={getAmbulanceFleetIcon(amb.status, amb.has_patient, amb.is_roaming)}
          eventHandlers={{
            click: () => onAmbulanceClick && onAmbulanceClick(amb),
          }}
        >
          <Popup>
            <div className="ambulance-popup" style={{ minWidth: "200px", padding: "4px" }}>
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  marginBottom: "8px",
                  borderBottom: "1px solid #333",
                  paddingBottom: "4px",
                }}
              >
                <strong style={{ fontSize: "14px" }}>{amb.ambulance_id}</strong>
                <span
                  style={{
                    fontSize: "10px",
                    padding: "2px 6px",
                    borderRadius: "4px",
                    fontWeight: "bold",
                    color: "#fff",
                    background:
                      amb.has_patient || amb.status === "BUSY"
                        ? "#c5221f"
                        : amb.status === "DISPATCHED"
                        ? "#d97706"
                        : "#1e8e5a",
                  }}
                >
                  {amb.status} {amb.is_roaming ? "(ROAMING)" : "(STANDBY)"}
                </span>
              </div>
              <div style={{ fontSize: "12px", lineHeight: "1.6" }}>
                <div>
                  <strong>Patient on Board:</strong> {amb.has_patient ? "Yes (🚨 En Route)" : "None"}
                </div>
                <div>
                  <strong>Fleet Mode:</strong> {amb.is_roaming ? "Roaming Patrol ⚡" : "Standby Base 🅿️"}
                </div>
                {amb.destination && (
                  <div>
                    <strong>Heading To:</strong> {amb.destination.hospital_name}
                  </div>
                )}
                {amb.eta_seconds !== null && amb.eta_seconds > 0 && (
                  <div>
                    <strong>ETA:</strong> {Math.round(amb.eta_seconds)}s (
                    {Math.ceil(amb.eta_seconds / 60)} min)
                  </div>
                )}
                <div style={{ fontSize: "11px", color: "#888", marginTop: "4px" }}>
                  Coord: {amb.latitude.toFixed(4)}, {amb.longitude.toFixed(4)}
                </div>
              </div>
            </div>
          </Popup>
        </Marker>
      ))}

      {/* Emergency patient location marker */}
      {patientLocation && (
        <Marker position={[patientLocation.lat, patientLocation.lng]} icon={patientMarkerIcon}>
          <Popup>
            <div style={{ minWidth: "160px" }}>
              <strong style={{ color: "#FF4D5E", fontSize: "13px" }}>🚨 Emergency Patient Location</strong>
              <div style={{ fontSize: "12px", marginTop: "4px" }}>
                <div>Latitude: <span className="value-mono">{patientLocation.lat.toFixed(5)}</span></div>
                <div>Longitude: <span className="value-mono">{patientLocation.lng.toFixed(5)}</span></div>
              </div>
            </div>
          </Popup>
        </Marker>
      )}

      {/* User ambulance dispatch marker (fallback / original) */}
      <Marker position={[ambulancePos.lat, ambulancePos.lng]} icon={ambulanceIcon}>
        <Popup>User Selected Location</Popup>
      </Marker>


      {/* Active dispatch route for user search */}
      {routeLatLngs.length > 1 && (
        <Polyline
          key={`${route?.hospital.id ?? "route"}-${routeLatLngs.length}-${route?.estimated_travel_time_seconds ?? 0}`}
          positions={routeLatLngs}
          pathOptions={{ color: "#35D48C", weight: 5, opacity: 0.9 }}
        />
      )}
    </MapContainer>
  );
}
