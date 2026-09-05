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
import type { HospitalListItem, LatLng, RouteResponse } from "../types";

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
  onMapClick: (pos: LatLng) => void;
  hospitals: HospitalListItem[];
  selectedHospitalId: string | null;
  route: RouteResponse | null;
  onHospitalClick: (hospital: HospitalListItem) => void;
}

export function MapView({
  ambulancePos,
  onMapClick,
  hospitals,
  selectedHospitalId,
  route,
  onHospitalClick,
}: MapViewProps) {
  // route_geometry is [lon, lat][] (GeoJSON order) — Leaflet wants [lat, lon].
  // This is at most a few hundred points (the selected route only), never
  // the full 196k-edge network.
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

      <Marker position={[ambulancePos.lat, ambulancePos.lng]} icon={ambulanceIcon}>
        <Popup>Ambulance position</Popup>
      </Marker>

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
