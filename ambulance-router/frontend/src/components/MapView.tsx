import { useEffect, useMemo, useRef, useState } from "react";
import {
  MapContainer,
  Marker,
  Polyline,
  Popup,
  TileLayer,
  useMapEvents,
} from "react-leaflet";
import MarkerClusterGroup from "react-leaflet-cluster";
import L, { type LatLngExpression } from "leaflet";
import type {
  AmbulanceState,
  HospitalListItem,
  LatLng,
  RouteResponse,
  TrafficCongestionResponse,
} from "../types";

import "leaflet/dist/leaflet.css";
import "leaflet.markercluster/dist/MarkerCluster.css";
import "leaflet.markercluster/dist/MarkerCluster.Default.css";

/**
 * Formats distance in kilometers with 2 decimal places.
 * Examples: 496m -> "0.50 km", 2257m -> "2.26 km"
 */
export function formatDistanceKm(meters: number | null | undefined): string {
  if (meters === null || meters === undefined || meters < 0) {
    return "0.00 km";
  }
  return `${(meters / 1000).toFixed(2)} km`;
}

/**
 * Formats ETA in hours and minutes.
 * Examples:
 *   45 sec -> "1 min"
 *   125 sec -> "2 min"
 *   3600 sec -> "1 hr"
 *   3660 sec -> "1 hr 1 min"
 *   5400 sec -> "1 hr 30 min"
 */
export function formatEta(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || seconds <= 0) {
    return "0 min";
  }
  const totalSec = Math.round(seconds);
  if (totalSec < 60) {
    return "1 min";
  }
  const hours = Math.floor(totalSec / 3600);
  const remainingSec = totalSec % 3600;
  const mins = Math.round(remainingSec / 60);

  if (hours > 0) {
    if (mins === 60) {
      return `${hours + 1} hr`;
    }
    if (mins > 0) {
      return `${hours} hr ${mins} min`;
    }
    return `${hours} hr`;
  }

  return `${mins} min`;
}

const MUMBAI_CENTER: LatLngExpression = [19.076, 72.8777];


// Divisor of DOM icons rather than default Leaflet pin images
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

function getAmbulanceFleetIcon(
  status: string,
  hasPatient: boolean,
  isRoaming?: boolean,
  trafficCondition?: string | null
) {
  const isWithPatient = hasPatient || status === "BUSY";
  const isDispatched = status === "DISPATCHED";
  const isRed = trafficCondition === "RED";
  const isYellow = trafficCondition === "YELLOW" || trafficCondition === "CONGESTED";
  const isCongested = isRed || isYellow;

  // Green for Available, Orange for Dispatched, Red for Patient
  const color = isWithPatient ? "#FF4D5E" : isDispatched ? "#FFAA00" : "#35D48C";
  const glow = isRed
    ? "rgba(255, 77, 94, 0.85)"
    : isYellow
    ? "rgba(255, 170, 0, 0.85)"
    : isWithPatient
    ? "rgba(255, 77, 94, 0.55)"
    : isDispatched
    ? "rgba(255, 170, 0, 0.55)"
    : "rgba(53, 212, 140, 0.45)";

  const trafficBadge = isRed
    ? `<span style="position:absolute;top:-6px;left:-6px;font-size:10px;filter:drop-shadow(0 1px 2px rgba(0,0,0,0.8));">🔴</span>`
    : isYellow
    ? `<span style="position:absolute;top:-6px;left:-6px;font-size:10px;filter:drop-shadow(0 1px 2px rgba(0,0,0,0.8));">🟡</span>`
    : "";

  const roleBadge = isWithPatient
    ? `<span style="position:absolute;top:-6px;right:-6px;font-size:11px;filter:drop-shadow(0 1px 2px rgba(0,0,0,0.8));">🚨</span>`
    : isRoaming
    ? `<span style="position:absolute;top:-5px;right:-5px;font-size:9px;background:#0A0E14;border:1px solid #35D48C;border-radius:3px;padding:0 2px;">⚡</span>`
    : "";

  return L.divIcon({
    className: `resqroute-fleet-amb resqroute-fleet-${status.toLowerCase()}`,
    html: `<div style="
      position:relative;width:28px;height:28px;border-radius:50%;
      background:${color};border:2px solid ${isCongested ? "#FFAA00" : "#0A0E14"};
      box-shadow:0 0 0 3px ${glow}, 0 2px 6px rgba(0,0,0,0.5);
      display:flex;align-items:center;justify-content:center;
      font-size:13px;cursor:pointer;
    ">🚑${trafficBadge}${roleBadge}</div>`,
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
  patientAmbulanceId?: string | null;
  onMapClick: (pos: LatLng) => void;
  hospitals: HospitalListItem[];
  selectedHospitalId: string | null;
  route: RouteResponse | null;
  onHospitalClick: (hospital: HospitalListItem) => void;
  fleetAmbulances?: AmbulanceState[];
  onAmbulanceClick?: (ambulance: AmbulanceState) => void;
  congestionData?: TrafficCongestionResponse | null;
  onReseedTraffic?: () => void;
  isTrafficLoading?: boolean;
}

export function MapView({
  ambulancePos,
  patientLocation,
  patientAmbulanceId,
  onMapClick,
  hospitals,
  selectedHospitalId,
  route,
  onHospitalClick,
  fleetAmbulances = [],
  onAmbulanceClick,
  congestionData,
  onReseedTraffic,
  isTrafficLoading = false,
}: MapViewProps) {
  const [showTraffic, setShowTraffic] = useState(true);
  const [animatedPositions, setAnimatedPositions] = useState<Record<string, LatLng>>({});
  const animationFrameRef = useRef<number | null>(null);
  const animationStatesRef = useRef<Record<string, {
    /** Polyline path [lat, lng][] the ambulance should follow this tick */
    path: LatLng[];
    /** Cumulative distances along `path` (same length) */
    pathCumDist: number[];
    /** Total length of `path` in meters */
    pathTotalDist: number;
    /** performance.now() when the travel animation started */
    startedAt: number;
    /** Duration (ms) over which to traverse the full path segment */
    durationMs: number;
    /** If > 0, hold at holdPosition until this timestamp before moving */
    holdUntil: number;
    /** Position to display while holding */
    holdPosition?: LatLng;
  }>>({});
  const previousFleetRef = useRef<Record<string, AmbulanceState>>({});

  // ── helpers ────────────────────────────────────────────────────────────
  /** Haversine distance in meters between two lat/lng points. */
  const haversineM = (a: LatLng, b: LatLng): number => {
    const R = 6_371_000;
    const toRad = (d: number) => (d * Math.PI) / 180;
    const dLat = toRad(b.lat - a.lat);
    const dLng = toRad(b.lng - a.lng);
    const sinHalf = Math.sin(dLat / 2);
    const sinHalfLng = Math.sin(dLng / 2);
    const h =
      sinHalf * sinHalf +
      Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * sinHalfLng * sinHalfLng;
    return R * 2 * Math.atan2(Math.sqrt(h), Math.sqrt(1 - h));
  };

  /** Build cumulative-distance array for a polyline. */
  const buildCumDist = (pts: LatLng[]): { cumDist: number[]; total: number } => {
    const cumDist = [0];
    for (let i = 1; i < pts.length; i++) {
      cumDist.push(cumDist[i - 1] + haversineM(pts[i - 1], pts[i]));
    }
    return { cumDist, total: cumDist[cumDist.length - 1] };
  };

  /** Interpolate position at `dist` meters along a polyline. */
  const interpolateAlongPath = (
    pts: LatLng[],
    cumDist: number[],
    dist: number,
  ): LatLng => {
    if (pts.length === 0) return { lat: 0, lng: 0 };
    if (dist <= 0 || pts.length === 1) return pts[0];
    if (dist >= cumDist[cumDist.length - 1]) return pts[pts.length - 1];
    // Binary-search for the segment
    let lo = 0;
    let hi = cumDist.length - 1;
    while (lo < hi - 1) {
      const mid = (lo + hi) >> 1;
      if (cumDist[mid] <= dist) lo = mid;
      else hi = mid;
    }
    const segLen = cumDist[hi] - cumDist[lo];
    const frac = segLen > 1e-9 ? (dist - cumDist[lo]) / segLen : 0;
    return {
      lat: pts[lo].lat + (pts[hi].lat - pts[lo].lat) * frac,
      lng: pts[lo].lng + (pts[hi].lng - pts[lo].lng) * frac,
    };
  };

  /**
   * Build the path segment an ambulance should travel THIS tick.
   * We take the ambulance's route_geometry (remaining route from backend,
   * in GeoJSON [lon, lat] order) and prepend the current display position
   * so the ambulance smoothly moves from where it appears now toward
   * the backend-reported position along the road.
   */
  const buildPathForAmbulance = (
    currentDisplayPos: LatLng,
    ambulance: AmbulanceState,
  ): LatLng[] => {
    const backendPos: LatLng = { lat: ambulance.latitude, lng: ambulance.longitude };

    // Route geometry is [lon, lat][] — convert to LatLng[]
    const routeLatLngs: LatLng[] =
      ambulance.route_geometry?.map(([lon, lat]) => ({ lat, lng: lon })) ?? [];

    if (routeLatLngs.length < 2) {
      // No route — fall back to straight-line interpolation
      return [currentDisplayPos, backendPos];
    }

    // Find the point on the route polyline closest to the current display position
    // and the point closest to the backend-reported position, then extract the
    // sub-path between them.
    const projectOnRoute = (target: LatLng): { idx: number; frac: number; dist: number } => {
      let bestDist = Infinity;
      let bestIdx = 0;
      let bestFrac = 0;
      for (let i = 0; i < routeLatLngs.length - 1; i++) {
        const a = routeLatLngs[i];
        const b = routeLatLngs[i + 1];
        // Project target onto segment a→b
        const dx = b.lng - a.lng;
        const dy = b.lat - a.lat;
        const lenSq = dx * dx + dy * dy;
        let t = 0;
        if (lenSq > 1e-14) {
          t = Math.max(0, Math.min(1, ((target.lng - a.lng) * dx + (target.lat - a.lat) * dy) / lenSq));
        }
        const projLat = a.lat + t * dy;
        const projLng = a.lng + t * dx;
        const d = haversineM(target, { lat: projLat, lng: projLng });
        if (d < bestDist) {
          bestDist = d;
          bestIdx = i;
          bestFrac = t;
          // Early exit for near-exact matches
          if (d < 0.5) break;
        }
      }
      return { idx: bestIdx, frac: bestFrac, dist: bestDist };
    };

    const fromProj = projectOnRoute(currentDisplayPos);
    const toProj = projectOnRoute(backendPos);

    // Build sub-path from fromProj → toProj along the polyline
    const subPath: LatLng[] = [];

    // Start from projected position on the polyline (or currentDisplayPos if off-route)
    if (fromProj.dist > 500) {
      // If we're very far from the route, just straight-line to backend pos
      return [currentDisplayPos, backendPos];
    }

    // Starting interpolated point on the route
    const startPt: LatLng = {
      lat: routeLatLngs[fromProj.idx].lat + fromProj.frac * (routeLatLngs[fromProj.idx + 1].lat - routeLatLngs[fromProj.idx].lat),
      lng: routeLatLngs[fromProj.idx].lng + fromProj.frac * (routeLatLngs[fromProj.idx + 1].lng - routeLatLngs[fromProj.idx].lng),
    };
    subPath.push(startPt);

    // Determine which direction along the route we're going
    // (from segment → to segment should be in route order, i.e. toIdx >= fromIdx)
    const fromSeg = fromProj.idx;
    const toSeg = toProj.idx;

    if (toSeg > fromSeg || (toSeg === fromSeg && toProj.frac > fromProj.frac)) {
      // Normal forward movement along route
      // Add intermediate polyline vertices between fromSeg+1 .. toSeg
      for (let i = fromProj.idx + 1; i <= toProj.idx; i++) {
        subPath.push(routeLatLngs[i]);
      }
    } else {
      // Backend position is behind or same as current — just go straight
      subPath.length = 0;
      subPath.push(currentDisplayPos);
    }

    // End interpolated point on the route
    const endPt: LatLng = {
      lat: routeLatLngs[toProj.idx].lat + toProj.frac * (routeLatLngs[toProj.idx + 1].lat - routeLatLngs[toProj.idx].lat),
      lng: routeLatLngs[toProj.idx].lng + toProj.frac * (routeLatLngs[toProj.idx + 1].lng - routeLatLngs[toProj.idx].lng),
    };
    subPath.push(endPt);

    // Deduplicate consecutive identical points
    const cleaned: LatLng[] = [subPath[0]];
    for (let i = 1; i < subPath.length; i++) {
      if (
        Math.abs(subPath[i].lat - cleaned[cleaned.length - 1].lat) > 1e-9 ||
        Math.abs(subPath[i].lng - cleaned[cleaned.length - 1].lng) > 1e-9
      ) {
        cleaned.push(subPath[i]);
      }
    }

    return cleaned.length >= 2 ? cleaned : [currentDisplayPos, backendPos];
  };

  // ── Main animation effect ──────────────────────────────────────────────
  // Smooth the coarse backend snapshots for display only. Routing, movement,
  // status transitions, and server-side timing remain unchanged.
  useEffect(() => {
    const now = performance.now();
    const nextPositions: Record<string, LatLng> = { ...animatedPositions };
    const nextPrevious: Record<string, AmbulanceState> = {};

    for (const ambulance of fleetAmbulances) {
      const id = ambulance.ambulance_id;
      const target = { lat: ambulance.latitude, lng: ambulance.longitude };
      const current = nextPositions[id] ?? target;
      const previous = previousFleetRef.current[id];
      const pickedUp = previous && !previous.has_patient && ambulance.has_patient;

      if (pickedUp) {
        // Patient pickup — hold at patient location for 2 seconds
        nextPositions[id] = target;
        animationStatesRef.current[id] = {
          path: [target],
          pathCumDist: [0],
          pathTotalDist: 0,
          startedAt: now + 2000,
          durationMs: 0,
          holdUntil: now + 2000,
          holdPosition: target,
        };
      } else if (
        Math.abs(current.lat - target.lat) > 1e-8 ||
        Math.abs(current.lng - target.lng) > 1e-8
      ) {
        const existing = animationStatesRef.current[id];
        const isHolding = existing && existing.holdUntil > now;

        const animFrom = isHolding ? (existing.holdPosition ?? current) : current;
        const path = buildPathForAmbulance(animFrom, ambulance);
        const { cumDist, total } = buildCumDist(path);

        animationStatesRef.current[id] = {
          path,
          pathCumDist: cumDist,
          pathTotalDist: total,
          startedAt: isHolding ? existing.holdUntil : now,
          durationMs: 1400,
          holdUntil: isHolding ? existing.holdUntil : 0,
          holdPosition: isHolding ? (existing.holdPosition ?? current) : undefined,
        };
      }

      nextPrevious[id] = ambulance;
    }

    previousFleetRef.current = nextPrevious;
    setAnimatedPositions(nextPositions);

    if (animationFrameRef.current === null) {
      const animate = (timestamp: number) => {
        let active = false;
        const framePositions: Record<string, LatLng> = { ...nextPositions };

        for (const [id, state] of Object.entries(animationStatesRef.current)) {
          if (timestamp < state.holdUntil) {
            framePositions[id] = state.holdPosition ?? state.path[0];
            active = true;
            continue;
          }

          if (state.pathTotalDist < 1e-6 || state.durationMs <= 0) {
            // No distance to travel — snap to final position
            framePositions[id] = state.path[state.path.length - 1];
            continue;
          }

          const rawProgress = Math.min(1, (timestamp - state.startedAt) / state.durationMs);
          // Ease-in-out quad for smooth acceleration / deceleration
          const eased =
            rawProgress < 0.5
              ? 2 * rawProgress * rawProgress
              : 1 - Math.pow(-2 * rawProgress + 2, 2) / 2;

          const distAlong = eased * state.pathTotalDist;
          framePositions[id] = interpolateAlongPath(
            state.path,
            state.pathCumDist,
            distAlong,
          );

          if (rawProgress < 1) active = true;
        }

        setAnimatedPositions(framePositions);
        animationFrameRef.current = active ? requestAnimationFrame(animate) : null;
      };
      animationFrameRef.current = requestAnimationFrame(animate);
    }

    return () => {
      if (animationFrameRef.current !== null) {
        cancelAnimationFrame(animationFrameRef.current);
        animationFrameRef.current = null;
      }
    };
    // Snapshot updates intentionally restart the display interpolation.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fleetAmbulances]);

  const animatedFleetAmbulances = fleetAmbulances.map((ambulance) => {
    const position = animatedPositions[ambulance.ambulance_id];
    return position ? { ...ambulance, latitude: position.lat, longitude: position.lng } : ambulance;
  });
  const attachedAmbulance = patientAmbulanceId
    ? animatedFleetAmbulances.find((ambulance) => ambulance.ambulance_id === patientAmbulanceId)
    : undefined;
  const renderedPatientLocation = attachedAmbulance?.has_patient
    ? { lat: attachedAmbulance.latitude, lng: attachedAmbulance.longitude }
    : patientLocation;

  // route_geometry is [lon, lat][] (GeoJSON order) — Leaflet wants [lat, lon].
  const routeLatLngs: LatLngExpression[] = useMemo(() => {
    if (!route?.route_geometry?.length) return [];
    return route.route_geometry.map(([lon, lat]) => [lat, lon]);
  }, [route]);

  const congestedAmbsCount = animatedFleetAmbulances.filter(
    (a) => a.traffic_condition === "CONGESTED"
  ).length;

  return (
    <div style={{ position: "relative", width: "100%", height: "100%" }}>
      {/* Live Redis Traffic Congestion Floating Panel & Legend */}
      <div
        style={{
          position: "absolute",
          top: "12px",
          right: "12px",
          zIndex: 1000,
          background: "rgba(10, 14, 20, 0.92)",
          backdropFilter: "blur(8px)",
          border: "1px solid #263140",
          borderRadius: "8px",
          padding: "10px 14px",
          color: "#fff",
          display: "flex",
          flexDirection: "column",
          gap: "8px",
          boxShadow: "0 6px 16px rgba(0,0,0,0.6)",
          minWidth: "260px",
          pointerEvents: "auto",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
            <span style={{ fontSize: "16px" }}>🚦</span>
            <div>
              <div style={{ fontWeight: 700, fontSize: "11px", letterSpacing: "0.5px", color: "#E0E6ED" }}>
                LIVE REDIS TRAFFIC
              </div>
              <div style={{ fontSize: "10px", color: "#35D48C" }}>
                ● Stored in Redis (<code>traffic:speeds</code>)
              </div>
            </div>
          </div>
          <button
            onClick={() => setShowTraffic((prev) => !prev)}
            style={{
              background: showTraffic ? "rgba(53, 212, 140, 0.18)" : "rgba(255, 255, 255, 0.08)",
              border: `1px solid ${showTraffic ? "#35D48C" : "#555"}`,
              color: showTraffic ? "#35D48C" : "#aaa",
              borderRadius: "4px",
              padding: "3px 8px",
              fontSize: "10px",
              cursor: "pointer",
              fontWeight: 600,
            }}
          >
            {showTraffic ? "Overlay: ON" : "Overlay: OFF"}
          </button>
        </div>

        {/* Traffic Levels Breakdown */}
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: "5px",
            fontSize: "11px",
            borderTop: "1px solid #1E293B",
            paddingTop: "6px",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <span style={{ display: "flex", alignItems: "center", gap: "6px" }}>
              <span
                style={{
                  display: "inline-block",
                  width: "16px",
                  height: "5px",
                  background: "#FF3B30",
                  borderRadius: "2px",
                  boxShadow: "0 0 4px #FF3B30",
                }}
              />
              <span>Heavy Congestion (Avoided):</span>
            </span>
            <span style={{ color: "#FF3B30", fontWeight: "bold" }}>
              {congestionData ? `${congestionData.heavy_count} rds` : "Loading..."}
            </span>
          </div>

          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <span style={{ display: "flex", alignItems: "center", gap: "6px" }}>
              <span
                style={{
                  display: "inline-block",
                  width: "16px",
                  height: "5px",
                  background: "#FFCC00",
                  borderRadius: "2px",
                  boxShadow: "0 0 4px #FFCC00",
                }}
              />
              <span>Moderate Congestion:</span>
            </span>
            <span style={{ color: "#FFCC00", fontWeight: "bold" }}>
              {congestionData ? `${congestionData.moderate_count} rds` : "Loading..."}
            </span>
          </div>

          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <span style={{ display: "flex", alignItems: "center", gap: "6px" }}>
              <span
                style={{
                  display: "inline-block",
                  width: "16px",
                  height: "5px",
                  background: "#00E5FF",
                  borderRadius: "2px",
                  boxShadow: "0 0 4px #00E5FF",
                }}
              />
              <span>Ambulance Fastest Path:</span>
            </span>
            <span style={{ color: "#00E5FF", fontWeight: "bold" }}>
              Dynamic Detour
            </span>
          </div>
        </div>

        {congestedAmbsCount > 0 && (
          <div
            style={{
              fontSize: "10px",
              color: "#FFAA00",
              background: "rgba(255,170,0,0.12)",
              padding: "4px 8px",
              borderRadius: "4px",
              border: "1px solid rgba(255,170,0,0.3)",
            }}
          >
            ⚠️ {congestedAmbsCount} ambulance(s) actively rerouting around congestion
          </div>
        )}

        {onReseedTraffic && (
          <button
            onClick={onReseedTraffic}
            disabled={isTrafficLoading}
            style={{
              marginTop: "2px",
              background: "#1E293B",
              border: "1px solid #334155",
              color: "#94A3B8",
              borderRadius: "4px",
              padding: "4px 8px",
              fontSize: "10px",
              cursor: isTrafficLoading ? "not-allowed" : "pointer",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: "4px",
            }}
          >
            🔄 {isTrafficLoading ? "Updating Redis Speeds..." : "Simulate Traffic Shift (Redis)"}
          </button>
        )}
      </div>

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

        {/* Live Redis Traffic Congestion Polylines (Red = Heavy, Yellow = Moderate) */}
        {showTraffic &&
          congestionData?.segments?.map((seg) => {
            const pts: LatLngExpression[] = seg.geometry.map(([lon, lat]) => [lat, lon]);
            const isHeavy = seg.level === "HEAVY";
            return (
              <Polyline
                key={`traffic-${seg.edge_id}`}
                positions={pts}
                pathOptions={{
                  color: isHeavy ? "#FF3B30" : "#FFCC00",
                  weight: isHeavy ? 5 : 4,
                  opacity: isHeavy ? 0.88 : 0.82,
                  lineCap: "round",
                  lineJoin: "round",
                }}
              >
                <Popup>
                  <div style={{ minWidth: "170px", padding: "2px", color: "#111" }}>
                    <div
                      style={{
                        fontWeight: "bold",
                        fontSize: "12px",
                        color: isHeavy ? "#D32F2F" : "#F57C00",
                        marginBottom: "4px",
                        borderBottom: "1px solid #ddd",
                        paddingBottom: "3px",
                      }}
                    >
                      {isHeavy ? "🔴 Heavy Congestion Zone" : "🟡 Moderate Congestion Zone"}
                    </div>
                    <div style={{ fontSize: "11px", lineHeight: "1.5" }}>
                      <div>
                        <strong>Live Speed:</strong> {seg.speed_kmh} km/h
                      </div>
                      <div>
                        <strong>Normal Speed:</strong> {seg.normal_speed_kmh} km/h
                      </div>
                      <div>
                        <strong>Slowdown:</strong> {Math.round((1 - seg.congestion_ratio) * 100)}% slower
                      </div>
                      <div style={{ fontSize: "10px", color: "#666", marginTop: "3px" }}>
                        Edge: <code>{seg.edge_id}</code>
                      </div>
                      <div
                        style={{
                          fontSize: "10px",
                          color: "#1e8e5a",
                          marginTop: "2px",
                          fontWeight: "bold",
                        }}
                      >
                        ● Live from Redis hash: <code>traffic:speeds</code>
                      </div>
                    </div>
                  </div>
                </Popup>
              </Polyline>
            );
          })}

        {/* Clustered hospital markers */}
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
                  <div className="hospital-popup__row">
                    <span>Emergency doctors</span>
                    <span className={h.emergency_doctors > 0 ? "value-ok" : "value-critical"}>
                      {h.emergency_doctors}
                    </span>
                  </div>
                </div>
              </Popup>
            </Marker>
          ))}
        </MarkerClusterGroup>

        {/* Active route polylines for moving fleet ambulances */}
        {animatedFleetAmbulances.map((amb) => {
          if (!amb.route_geometry || amb.route_geometry.length < 2) return null;
          const pts: LatLngExpression[] = amb.route_geometry.map(([lon, lat]) => [lat, lon]);
          const isWithPatient = amb.has_patient || amb.status === "BUSY";
          const isDispatched = amb.status === "DISPATCHED";
          const isRed = amb.traffic_condition === "RED";
          const isYellow = amb.traffic_condition === "YELLOW" || amb.traffic_condition === "CONGESTED";
          const color = isWithPatient ? "#FF4D5E" : isDispatched ? "#FFAA00" : "#35D48C";

          return (
            <Polyline
              key={`fleet-route-${amb.ambulance_id}`}
              positions={pts}
              pathOptions={{
                color: isRed ? "#FF3B30" : isYellow ? "#FFCC00" : color,
                weight: isDispatched || isWithPatient || isRed || isYellow ? 4 : 3,
                opacity: isDispatched || isWithPatient ? 0.9 : 0.6,
                dashArray: isRed || isYellow ? "5, 5" : isDispatched || isWithPatient ? undefined : "5, 6",
              }}
            />
          );
        })}

        {/* 30 simulated fleet ambulances */}
        {animatedFleetAmbulances.map((amb) => (
          <Marker
            key={amb.ambulance_id}
            position={[amb.latitude, amb.longitude]}
            icon={getAmbulanceFleetIcon(
              amb.status,
              amb.has_patient,
              amb.is_roaming,
              amb.traffic_condition
            )}
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
                    <strong>Patient onboard:</strong>{" "}
                    <span
                      style={{
                        color: amb.has_patient ? "#FF4D5E" : "#35D48C",
                        fontWeight: "bold",
                      }}
                    >
                      {amb.has_patient ? "Yes" : "No"}
                    </span>
                  </div>

                  {amb.destination && (
                    <div>
                      <strong>
                        {amb.status === "DISPATCHED" ? "Patient Destination:" : "Hospital Destination:"}
                      </strong>{" "}
                      {amb.destination.hospital_name}
                    </div>
                  )}

                  {/* LIVE REMAINING DISTANCE (IN KM) */}
                  {amb.remaining_distance_meters !== null &&
                  amb.remaining_distance_meters !== undefined ? (
                    <div>
                      <strong>
                        {amb.status === "DISPATCHED"
                          ? "Remaining to Patient:"
                          : amb.status === "BUSY"
                          ? "Remaining to Hospital:"
                          : "Patrol Route Remaining:"}
                      </strong>{" "}
                      <span className="value-mono" style={{ color: "#38BDF8", fontWeight: "bold" }}>
                        {formatDistanceKm(amb.remaining_distance_meters)}
                      </span>
                    </div>
                  ) : amb.status === "AVAILABLE" && !amb.is_roaming ? (
                    <div>
                      <strong>Remaining Distance:</strong>{" "}
                      <span style={{ color: "#888" }}>0.00 km (Stationary Base)</span>
                    </div>
                  ) : null}

                  {/* LIVE ETA (IN HOURS/MINUTES) */}
                  {amb.eta_seconds !== null && amb.eta_seconds !== undefined ? (
                    <div>
                      <strong>
                        {amb.status === "DISPATCHED"
                          ? "ETA to Patient:"
                          : amb.status === "BUSY"
                          ? "ETA to Hospital:"
                          : "Patrol ETA:"}
                      </strong>{" "}
                      <span className="value-mono" style={{ color: "#34D399", fontWeight: "bold" }}>
                        {formatEta(amb.eta_seconds)}
                      </span>
                    </div>
                  ) : amb.status === "AVAILABLE" && !amb.is_roaming ? (
                    <div>
                      <strong>ETA:</strong> <span style={{ color: "#888" }}>Standby</span>
                    </div>
                  ) : null}

                  <div>
                    <strong>Fleet Mode:</strong>{" "}
                    {amb.is_roaming ? "Roaming Patrol ⚡" : "Standby Base 🅿️"}
                  </div>

                  {amb.traffic_source && (
                    <div>
                      <strong>Traffic Feed:</strong>{" "}
                      <span
                        style={{
                          color:
                            amb.traffic_condition === "RED"
                              ? "#FF4D5E"
                              : amb.traffic_condition === "YELLOW" ||
                                amb.traffic_condition === "CONGESTED"
                              ? "#FFAA00"
                              : "#35D48C",
                          fontWeight: "bold",
                        }}
                      >
                        {amb.traffic_source === "redis"
                          ? "Live (Redis)"
                          : amb.traffic_source === "fallback"
                          ? "Fallback"
                          : "Static"}{" "}
                        {amb.traffic_condition === "RED"
                          ? "🔴 Heavy"
                          : amb.traffic_condition === "YELLOW" ||
                            amb.traffic_condition === "CONGESTED"
                          ? "🟡 Moderate"
                          : "🟢 Clear"}
                      </span>
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
        {renderedPatientLocation && (
          <Marker position={[renderedPatientLocation.lat, renderedPatientLocation.lng]} icon={patientMarkerIcon}>
            <Popup>
              <div style={{ minWidth: "160px" }}>
                <strong style={{ color: "#FF4D5E", fontSize: "13px" }}>
                  🚨 Emergency Patient Location
                </strong>
                <div style={{ fontSize: "12px", marginTop: "4px" }}>
                  <div>
                    Latitude:{" "}
                    <span className="value-mono">{renderedPatientLocation.lat.toFixed(5)}</span>
                  </div>
                  <div>
                    Longitude:{" "}
                    <span className="value-mono">{renderedPatientLocation.lng.toFixed(5)}</span>
                  </div>
                </div>
              </div>
            </Popup>
          </Marker>
        )}

        {/* User ambulance dispatch marker (fallback / original) */}
        <Marker position={[ambulancePos.lat, ambulancePos.lng]} icon={ambulanceIcon}>
          <Popup>User Selected Location</Popup>
        </Marker>

        {/* Active dispatch route with high-contrast dual-stroke (Dark casing + Glowing Cyan/Emerald) */}
        {routeLatLngs.length > 1 && (
          <>
            <Polyline
              key={`route-casing-${route?.hospital.id ?? "route"}`}
              positions={routeLatLngs}
              pathOptions={{ color: "#0A0E14", weight: 8, opacity: 0.7 }}
            />
            <Polyline
              key={`${route?.hospital.id ?? "route"}-${routeLatLngs.length}-${route?.estimated_travel_time_seconds ?? 0}`}
              positions={routeLatLngs}
              pathOptions={{ color: "#00E5FF", weight: 5, opacity: 0.95 }}
            />
          </>
        )}
      </MapContainer>
    </div>
  );
}
