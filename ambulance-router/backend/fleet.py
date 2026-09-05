"""
Ambulance fleet and progressive road-following simulation engine.

Manages 30 ambulances across Mumbai road network:
- 10 ROAMING ambulances: status=AVAILABLE, has_patient=False, continuously moving
  along real SUMO road geometry, auto-re-routing when reaching destination.
- 20 STANDBY ambulances: status=AVAILABLE, has_patient=False, stationary until dispatched.
- Emergency dispatch: selects best available ambulance (roaming or standby)
  based on shortest road routing travel time/cost to patient.
- Patient pickup: transitions ambulance to status=BUSY, has_patient=True upon arrival at patient.
"""
import bisect
import logging
import math
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from backend.graph_loader import (
    GraphData,
    edge_ids_to_lonlat_geometry,
    nearest_node_from_latlon,
)
from backend.hospitals import Hospital, filter_available
from backend.models import (
    AmbulanceDestination,
    AmbulanceState,
    EmergencyResponse,
    FleetSummary,
)
from backend.routing import (
    NoAvailableHospitalError,
    NoRouteFoundError,
    NodeRouteResult,
    find_route_between_nodes,
    find_route_to_nearest_hospital,
    find_route_to_target_hospital,
)

logger = logging.getLogger("fleet")


class AmbulanceHasPatientError(Exception):
    """Raised when trying to dispatch an ambulance that is already carrying a patient."""
    pass


def haversine_meters(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Calculate the great-circle distance between two points on the Earth in meters."""
    R = 6371000.0  # Earth radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
    return R * c


@dataclass
class Ambulance:
    ambulance_id: str
    latitude: float
    longitude: float
    status: str  # "AVAILABLE", "BUSY", "DISPATCHED"
    has_patient: bool
    is_roaming: bool = False
    original_roaming: bool = False
    target_type: Optional[str] = None  # "ROAMING", "PATIENT", "HOSPITAL"
    destination: Optional[AmbulanceDestination] = None
    eta_seconds: Optional[float] = None
    # Full route polyline for the current journey [[lon, lat], ...]
    full_route_geometry: List[List[float]] = field(default_factory=list)
    # Remaining route polyline from current position [[lon, lat], ...]
    route_geometry: List[List[float]] = field(default_factory=list)
    route_edge_ids: List[str] = field(default_factory=list)
    cumulative_distances: List[float] = field(default_factory=list)
    total_distance_m: float = 0.0
    current_distance_m: float = 0.0
    speed_mps: float = 12.0  # ~43 km/h effective ambulance speed
    current_node_id: Optional[str] = None

    def to_model(self) -> AmbulanceState:
        return AmbulanceState(
            ambulance_id=self.ambulance_id,
            latitude=round(self.latitude, 6),
            longitude=round(self.longitude, 6),
            status=self.status,
            has_patient=self.has_patient,
            is_roaming=self.is_roaming,
            destination=self.destination,
            eta_seconds=round(self.eta_seconds, 1) if self.eta_seconds is not None else None,
            route_geometry=self.route_geometry,
        )


class AmbulanceFleet:
    def __init__(
        self,
        gd: GraphData,
        hospitals: List[Hospital],
        traffic_speeds_fn: Optional[Callable[[], Tuple[Dict[str, float], str]]] = None,
    ):
        self.gd = gd
        self.hospitals = hospitals
        self.traffic_speeds_fn = traffic_speeds_fn or (lambda: ({}, "static"))
        self.ambulances: Dict[str, Ambulance] = {}
        self._lock = threading.RLock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_tick = time.time()

        self.initialize_fleet()

    def _build_cumulative_distances(
        self, points: List[List[float]], target_total_meters: Optional[float] = None
    ) -> Tuple[List[float], float]:
        """
        Compute cumulative distances along [lon, lat] polyline in meters.
        If target_total_meters is provided and > 0, scale cumulative distances to match it.
        """
        if not points or len(points) < 2:
            dist = target_total_meters if (target_total_meters and target_total_meters > 0) else 0.0
            return ([0.0] * len(points), dist)

        dists = [0.0]
        for i in range(len(points) - 1):
            p1 = points[i]
            p2 = points[i + 1]
            seg = haversine_meters(p1[0], p1[1], p2[0], p2[1])
            dists.append(dists[-1] + seg)

        raw_total = dists[-1]
        if target_total_meters is not None and target_total_meters > 0 and raw_total > 0:
            scale = target_total_meters / raw_total
            scaled_dists = [d * scale for d in dists]
            return (scaled_dists, target_total_meters)

        return (dists, raw_total)

    def _interpolate_position(
        self, points: List[List[float]], cum_dists: List[float], current_dist: float
    ) -> Tuple[float, float, List[List[float]]]:
        """
        Interpolate (latitude, longitude) at current_dist along the polyline.
        Returns: (lat, lon, remaining_points_including_current_pos).
        """
        if not points:
            return (0.0, 0.0, [])
        if len(points) == 1 or current_dist <= 0.0:
            return (points[0][1], points[0][0], points)

        total_dist = cum_dists[-1] if cum_dists else 0.0
        if current_dist >= total_dist and total_dist > 0:
            return (points[-1][1], points[-1][0], [points[-1]])

        # Find segment i where cum_dists[i] <= current_dist < cum_dists[i + 1]
        idx = bisect.bisect_right(cum_dists, current_dist) - 1
        idx = max(0, min(idx, len(points) - 2))

        p1 = points[idx]
        p2 = points[idx + 1]
        seg_dist = cum_dists[idx + 1] - cum_dists[idx]

        if seg_dist > 1e-6:
            frac = (current_dist - cum_dists[idx]) / seg_dist
        else:
            frac = 0.0

        lon = p1[0] + frac * (p2[0] - p1[0])
        lat = p1[1] + frac * (p2[1] - p1[1])
        curr_pt = [round(lon, 6), round(lat, 6)]

        remaining = [curr_pt] + points[idx + 1 :]
        return (lat, lon, remaining)

    def initialize_fleet(self) -> None:
        """
        Create exactly 30 simulated ambulances placed at valid Mumbai network locations:
        - 10 ROAMING: status=AVAILABLE, has_patient=False, is_roaming=True (continuously roaming)
        - 20 STANDBY: status=AVAILABLE, has_patient=False, is_roaming=False (stationary until dispatched)
        """
        with self._lock:
            self.ambulances.clear()
            num_amb = 30

            # 1. Determine valid initial candidate locations from hospitals or graph nodes
            candidate_locations: List[Tuple[float, float, str, Optional[Hospital]]] = []
            if self.hospitals and len(self.hospitals) >= num_amb:
                sorted_hospitals = sorted(self.hospitals, key=lambda h: h.latitude)
                step = len(sorted_hospitals) // num_amb
                for i in range(num_amb):
                    h = sorted_hospitals[min(i * step, len(sorted_hospitals) - 1)]
                    candidate_locations.append((h.latitude, h.longitude, h.sumo_node_id, h))
            elif self.gd.node_coords:
                nodes = list(self.gd.node_coords.keys())
                for i in range(num_amb):
                    node_id = nodes[i % len(nodes)]
                    nx, ny = self.gd.node_coords[node_id]
                    if self.gd.net and hasattr(self.gd.net, "convertXY2LonLat"):
                        try:
                            lon, lat = self.gd.net.convertXY2LonLat(nx, ny)
                        except Exception:
                            lon, lat = nx, ny
                    else:
                        lon, lat = nx, ny
                    candidate_locations.append((lat, lon, node_id, None))
            else:
                for i in range(num_amb):
                    candidate_locations.append((19.0760 + i * 0.005, 72.8777 + i * 0.005, f"node_{i}", None))

            # 2. Create 30 ambulances
            for i in range(num_amb):
                amb_num = i + 1
                amb_id = f"AMB-{amb_num:02d}"
                lat, lon, node_id, hosp = candidate_locations[i]

                is_roaming = (i < 10)  # Exactly 10 roaming, 20 standby
                status_desc = "ROAMING" if is_roaming else "STANDBY"

                logger.info("Initializing ambulance %d/30 (id=%s, type=%s)...", amb_num, amb_id, status_desc)

                amb = Ambulance(
                    ambulance_id=amb_id,
                    latitude=lat,
                    longitude=lon,
                    status="AVAILABLE",
                    has_patient=False,
                    is_roaming=is_roaming,
                    original_roaming=is_roaming,
                    target_type="ROAMING" if is_roaming else None,
                    current_node_id=node_id,
                    speed_mps=12.0,
                )

                # If roaming, assign initial active route along real SUMO roads
                if is_roaming:
                    self._assign_roaming_route(amb, candidate_hosp=hosp, index_hint=i)

                self.ambulances[amb_id] = amb

            logger.info("Fleet initialization complete: 30 ambulances initialized (10 ROAMING, 20 STANDBY).")
            self._last_tick = time.time()

    def _assign_roaming_route(
        self,
        amb: Ambulance,
        candidate_hosp: Optional[Hospital] = None,
        index_hint: int = 0,
    ) -> None:
        """Assign next roaming route along real SUMO road geometry."""
        speeds, _ = self.traffic_speeds_fn()
        source_node = amb.current_node_id
        if not source_node or source_node not in self.gd.node_index:
            source_node = nearest_node_from_latlon(self.gd, amb.latitude, amb.longitude)
            amb.current_node_id = source_node

        available_hospitals = filter_available(self.hospitals)
        if not available_hospitals and self.hospitals:
            available_hospitals = self.hospitals

        routed = False
        if available_hospitals and len(available_hospitals) > 1:
            source_id = candidate_hosp.id if candidate_hosp else None
            candidates = [
                h for h in available_hospitals
                if h.id != source_id and h.sumo_node_id != source_node
            ]
            if not candidates:
                candidates = available_hospitals

            try:
                result = find_route_to_nearest_hospital(
                    self.gd, source_node, candidates, speeds, alpha_emergency=1.0
                )
                geometry = edge_ids_to_lonlat_geometry(self.gd, result.edge_ids)
                if not geometry or len(geometry) < 2:
                    geometry = [
                        [amb.longitude, amb.latitude],
                        [result.hospital.longitude, result.hospital.latitude],
                    ]

                cum_dists, total_dist = self._build_cumulative_distances(
                    geometry, target_total_meters=result.distance_meters
                )

                amb.destination = AmbulanceDestination(
                    hospital_id=result.hospital.id,
                    hospital_name=f"Patrol ({result.hospital.name})",
                    latitude=result.hospital.latitude,
                    longitude=result.hospital.longitude,
                )
                amb.route_edge_ids = result.edge_ids
                amb.full_route_geometry = geometry
                amb.route_geometry = geometry
                amb.cumulative_distances = cum_dists
                amb.total_distance_m = total_dist
                # Stagger progress slightly on startup if index_hint given
                stagger_frac = (0.10 + (index_hint % 5) * 0.08) if index_hint > 0 else 0.0
                init_dist = total_dist * stagger_frac
                amb.current_distance_m = init_dist

                lat, lon, remaining = self._interpolate_position(geometry, cum_dists, init_dist)
                amb.latitude = lat
                amb.longitude = lon
                amb.route_geometry = remaining
                remaining_dist = max(0.0, total_dist - init_dist)
                amb.eta_seconds = remaining_dist / max(amb.speed_mps, 0.5)
                amb.target_type = "ROAMING"
                routed = True
            except Exception as exc:
                logger.debug("Roaming routing for %s: %s", amb.ambulance_id, exc)

        if not routed and self.gd.node_coords and len(self.gd.node_coords) > 1:
            # Fallback for test graph or isolated nodes
            nodes = [n for n in self.gd.node_coords.keys() if n != source_node]
            if nodes:
                target_node = nodes[index_hint % len(nodes)]
                try:
                    res = find_route_between_nodes(self.gd, source_node, target_node, speeds, 1.0)
                    geometry = edge_ids_to_lonlat_geometry(self.gd, res.edge_ids)
                    if not geometry or len(geometry) < 2:
                        nx, ny = self.gd.node_coords[target_node]
                        geometry = [[amb.longitude, amb.latitude], [nx, ny]]

                    cum_dists, total_dist = self._build_cumulative_distances(
                        geometry, target_total_meters=res.distance_meters
                    )
                    amb.destination = AmbulanceDestination(
                        hospital_id=target_node,
                        hospital_name=f"Sector {target_node}",
                        latitude=geometry[-1][1],
                        longitude=geometry[-1][0],
                    )
                    amb.route_edge_ids = res.edge_ids
                    amb.full_route_geometry = geometry
                    amb.route_geometry = geometry
                    amb.cumulative_distances = cum_dists
                    amb.total_distance_m = total_dist
                    amb.current_distance_m = 0.0
                    amb.eta_seconds = total_dist / max(amb.speed_mps, 0.5)
                    amb.target_type = "ROAMING"
                    routed = True
                except Exception:
                    pass

        if not routed:
            # Safe minimal roaming fallback
            target_lat = amb.latitude + 0.005
            target_lon = amb.longitude + 0.005
            fallback_geo = [[amb.longitude, amb.latitude], [target_lon, target_lat]]
            cum_dists, total_dist = self._build_cumulative_distances(fallback_geo, target_total_meters=500.0)
            amb.destination = AmbulanceDestination(
                hospital_id="roam_patrol",
                hospital_name="Patrol Route",
                latitude=target_lat,
                longitude=target_lon,
            )
            amb.full_route_geometry = fallback_geo
            amb.route_geometry = fallback_geo
            amb.cumulative_distances = cum_dists
            amb.total_distance_m = total_dist
            amb.current_distance_m = 0.0
            amb.eta_seconds = total_dist / max(amb.speed_mps, 0.5)
            amb.target_type = "ROAMING"

    def _route_to_nearest_hospital(self, amb: Ambulance) -> None:
        """
        Route ambulance from patient location to the nearest suitable hospital
        using existing static SUMO/rustworkx routing (no traffic, static speeds).
        """
        source_node = nearest_node_from_latlon(self.gd, amb.latitude, amb.longitude)
        amb.current_node_id = source_node

        available_hospitals = filter_available(self.hospitals)
        if not available_hospitals and self.hospitals:
            available_hospitals = self.hospitals

        routed = False
        if available_hospitals and source_node in self.gd.node_index:
            try:
                # Use existing normal/static routing speeds (redis_speeds={}, alpha_emergency=1.0)
                result = find_route_to_nearest_hospital(
                    self.gd,
                    source_node,
                    available_hospitals,
                    redis_speeds={},
                    alpha_emergency=1.0,
                )
                geometry = edge_ids_to_lonlat_geometry(self.gd, result.edge_ids)
                if not geometry or len(geometry) < 2:
                    geometry = [
                        [round(amb.longitude, 6), round(amb.latitude, 6)],
                        [round(result.hospital.longitude, 6), round(result.hospital.latitude, 6)],
                    ]

                cum_dists, total_dist = self._build_cumulative_distances(
                    geometry, target_total_meters=result.distance_meters
                )

                amb.has_patient = True
                amb.status = "BUSY"
                amb.is_roaming = False
                amb.target_type = "HOSPITAL"
                amb.destination = AmbulanceDestination(
                    hospital_id=result.hospital.id,
                    hospital_name=result.hospital.name,
                    latitude=result.hospital.latitude,
                    longitude=result.hospital.longitude,
                )
                amb.route_edge_ids = result.edge_ids
                amb.full_route_geometry = geometry
                amb.route_geometry = geometry
                amb.cumulative_distances = cum_dists
                amb.total_distance_m = total_dist
                amb.current_distance_m = 0.0
                amb.eta_seconds = total_dist / max(amb.speed_mps, 0.5)
                routed = True
                logger.info(
                    "Ambulance %s picked up patient, routed to nearest hospital %s (%s). Dist: %.1fm, ETA: %.1fs",
                    amb.ambulance_id, result.hospital.id, result.hospital.name, total_dist, amb.eta_seconds,
                )
            except Exception as exc:
                logger.warning("Routing to hospital failed for %s: %s", amb.ambulance_id, exc)

        if not routed:
            logger.error(
                "Could not route ambulance %s from patient to a hospital; keeping it at the pickup point",
                amb.ambulance_id,
            )
            amb.has_patient = True
            amb.status = "BUSY"
            amb.is_roaming = False
            amb.target_type = "HOSPITAL"
            amb.destination = None
            amb.route_edge_ids = []
            amb.full_route_geometry = []
            amb.route_geometry = []
            amb.cumulative_distances = []
            amb.current_distance_m = 0.0
            amb.total_distance_m = 0.0
            amb.eta_seconds = None

    def step(self, dt: float) -> None:
        """
        Advance simulation forward by dt seconds.
        Interpolates all moving ambulances along road geometry.
        """
        if dt <= 0:
            return

        with self._lock:
            for amb in self.ambulances.values():
                # Only ambulances with active routes move (roaming, dispatched, or busy)
                if amb.full_route_geometry and (amb.is_roaming or amb.status in ("BUSY", "DISPATCHED")):
                    progress = amb.speed_mps * dt
                    new_dist = amb.current_distance_m + progress

                    if new_dist >= amb.total_distance_m:
                        # Ambulance reached destination!
                        if amb.destination:
                            amb.latitude = amb.destination.latitude
                            amb.longitude = amb.destination.longitude

                        # Check destination type
                        if amb.target_type == "PATIENT":
                            # 1. PATIENT PICKUP OCCURS!
                            # Automatically set has_patient = True, status = "BUSY", immediately assign hospital destination
                            self._route_to_nearest_hospital(amb)

                        elif amb.target_type == "HOSPITAL":
                            # 2. HOSPITAL ARRIVAL: Drop off patient
                            logger.info(
                                "Ambulance %s arrived at hospital %s! Patient dropped off.",
                                amb.ambulance_id,
                                amb.destination.hospital_name if amb.destination else "",
                            )
                            amb.has_patient = False
                            amb.status = "AVAILABLE"
                            amb.target_type = None
                            amb.destination = None
                            amb.eta_seconds = None
                            amb.full_route_geometry = []
                            amb.route_geometry = []
                            amb.route_edge_ids = []
                            amb.cumulative_distances = []
                            amb.current_distance_m = 0.0
                            amb.total_distance_m = 0.0
                            amb.speed_mps = 12.0

                            if amb.original_roaming:
                                amb.is_roaming = True
                                amb.current_node_id = nearest_node_from_latlon(self.gd, amb.latitude, amb.longitude)
                                self._assign_roaming_route(amb)
                                logger.info("Ambulance %s resumed roaming patrol.", amb.ambulance_id)
                            else:
                                amb.is_roaming = False
                                logger.info("Ambulance %s remaining stationary at base.", amb.ambulance_id)

                        elif amb.is_roaming and amb.status == "AVAILABLE" and not amb.has_patient:
                            # Roaming ambulance arrived at its patrol destination -> auto-choose next route!
                            amb.current_node_id = nearest_node_from_latlon(self.gd, amb.latitude, amb.longitude)
                            self._assign_roaming_route(amb)

                        else:
                            # Regular arrival fallback
                            amb.status = "AVAILABLE"
                            amb.has_patient = False
                            amb.target_type = None
                            amb.destination = None
                            amb.eta_seconds = None
                            amb.full_route_geometry = []
                            amb.route_geometry = []
                            amb.route_edge_ids = []
                            amb.cumulative_distances = []
                            amb.current_distance_m = 0.0
                            amb.total_distance_m = 0.0
                            if amb.original_roaming:
                                amb.is_roaming = True
                                amb.current_node_id = nearest_node_from_latlon(self.gd, amb.latitude, amb.longitude)
                                self._assign_roaming_route(amb)
                            else:
                                amb.is_roaming = False
                    else:
                        # Advance position along polyline
                        amb.current_distance_m = new_dist
                        lat, lon, remaining = self._interpolate_position(
                            amb.full_route_geometry, amb.cumulative_distances, new_dist
                        )
                        amb.latitude = lat
                        amb.longitude = lon
                        amb.route_geometry = remaining

                        remaining_dist = max(0.0, amb.total_distance_m - new_dist)
                        amb.eta_seconds = remaining_dist / max(amb.speed_mps, 0.5)

    def request_ambulance(
        self,
        patient_lat: float,
        patient_lon: float,
        alpha_emergency: float = 1.5,
    ) -> EmergencyResponse:
        """
        Emergency dispatch:
        1. Find all currently AVAILABLE ambulances without patients (both roaming and standby).
        2. Calculate actual road travel time/cost to patient using SUMO/rustworkx routing.
        3. Select closest/best ambulance based on shortest travel time.
        4. Mark selected as DISPATCHED, stop roaming if it was roaming.
        5. Assign route to patient and start moving toward patient.
        """
        with self._lock:
            # 1. Find all available ambulances without patients
            available_ambs = [
                a for a in self.ambulances.values()
                if a.status == "AVAILABLE" and not a.has_patient
            ]
            if not available_ambs:
                raise ValueError("No available ambulances found for emergency request")

            speeds, _ = self.traffic_speeds_fn()
            patient_node = nearest_node_from_latlon(self.gd, patient_lat, patient_lon)

            # 2. Evaluate road routing cost from each available ambulance to patient
            best_amb: Optional[Ambulance] = None
            best_result: Optional[NodeRouteResult] = None
            best_travel_time = float("inf")

            for amb in available_ambs:
                source_node = amb.current_node_id
                if not source_node or source_node not in self.gd.node_index:
                    source_node = nearest_node_from_latlon(self.gd, amb.latitude, amb.longitude)

                if source_node == patient_node:
                    travel_time = 0.0
                    result = NodeRouteResult(edge_ids=[], distance_meters=0.0, travel_time_seconds=0.0)
                else:
                    try:
                        result = find_route_between_nodes(
                            self.gd, source_node, patient_node, speeds, alpha_emergency
                        )
                        travel_time = result.travel_time_seconds
                    except Exception:
                        # Fallback heuristic using road distance if disconnected component
                        dist = haversine_meters(amb.longitude, amb.latitude, patient_lon, patient_lat)
                        travel_time = dist / max(amb.speed_mps * alpha_emergency, 1.0)
                        result = NodeRouteResult(edge_ids=[], distance_meters=dist, travel_time_seconds=travel_time)

                if travel_time < best_travel_time:
                    best_travel_time = travel_time
                    best_amb = amb
                    best_result = result

            if best_amb is None:
                best_amb = available_ambs[0]
                dist = haversine_meters(best_amb.longitude, best_amb.latitude, patient_lon, patient_lat)
                best_result = NodeRouteResult(edge_ids=[], distance_meters=dist, travel_time_seconds=dist / 15.0)

            # 3. Mark selected ambulance as DISPATCHED and stop roaming
            best_amb.status = "DISPATCHED"
            best_amb.is_roaming = False  # Immediately ceases roaming!
            best_amb.has_patient = False
            best_amb.target_type = "PATIENT"

            # 4. Build geometry and assign route toward patient
            geometry = []
            if best_result.edge_ids:
                geometry = edge_ids_to_lonlat_geometry(self.gd, best_result.edge_ids)

            if not geometry or len(geometry) < 2:
                geometry = [
                    [round(best_amb.longitude, 6), round(best_amb.latitude, 6)],
                    [round(patient_lon, 6), round(patient_lat, 6)],
                ]

            target_m = best_result.distance_meters if best_result.distance_meters > 0 else None
            cum_dists, total_dist = self._build_cumulative_distances(geometry, target_total_meters=target_m)

            best_amb.destination = AmbulanceDestination(
                hospital_id="emergency_patient",
                hospital_name="Emergency Patient Location",
                latitude=patient_lat,
                longitude=patient_lon,
            )
            best_amb.route_edge_ids = best_result.edge_ids
            best_amb.full_route_geometry = geometry
            best_amb.route_geometry = geometry
            best_amb.cumulative_distances = cum_dists
            best_amb.total_distance_m = total_dist
            best_amb.current_distance_m = 0.0
            best_amb.speed_mps = max(12.0, 12.0 * alpha_emergency)
            best_amb.eta_seconds = total_dist / max(best_amb.speed_mps, 0.5)

            logger.info(
                "Dispatched ambulance %s (prev roaming=%s) to patient at (%.4f, %.4f). ETA: %.1fs",
                best_amb.ambulance_id, best_amb.is_roaming, patient_lat, patient_lon, best_amb.eta_seconds
            )

            return EmergencyResponse(
                ambulance=best_amb.to_model(),
                travel_time_seconds=round(best_amb.eta_seconds, 1),
                distance_meters=round(total_dist, 1),
                patient_latitude=patient_lat,
                patient_longitude=patient_lon,
            )

    def dispatch(
        self,
        ambulance_id: str,
        hospital_id: Optional[str] = None,
        has_patient: bool = False,
        alpha_emergency: float = 1.5,
    ) -> AmbulanceState:
        """
        Direct manual dispatch to a hospital (kept for backward compatibility).
        """
        with self._lock:
            amb = self.ambulances.get(ambulance_id)
            if amb is None:
                raise KeyError(f"Ambulance '{ambulance_id}' not found")

            if amb.has_patient:
                raise AmbulanceHasPatientError(
                    f"Ambulance '{ambulance_id}' is already carrying a patient and cannot be dispatched"
                )

            target_hospital: Optional[Hospital] = None
            if hospital_id:
                for h in self.hospitals:
                    if h.id == hospital_id:
                        target_hospital = h
                        break
                if target_hospital is None:
                    raise ValueError(f"Hospital '{hospital_id}' not found")
            else:
                available = filter_available(self.hospitals)
                if not available:
                    raise NoAvailableHospitalError("No hospitals with available ICU beds found")

            speeds, _ = self.traffic_speeds_fn()
            source_node = nearest_node_from_latlon(self.gd, amb.latitude, amb.longitude)

            if target_hospital:
                result = find_route_to_target_hospital(
                    self.gd, source_node, target_hospital, speeds, alpha_emergency
                )
            else:
                result = find_route_to_nearest_hospital(
                    self.gd, source_node, filter_available(self.hospitals), speeds, alpha_emergency
                )

            geometry = edge_ids_to_lonlat_geometry(self.gd, result.edge_ids)
            if not geometry or len(geometry) < 2:
                geometry = [
                    [amb.longitude, amb.latitude],
                    [result.hospital.longitude, result.hospital.latitude],
                ]

            cum_dists, total_dist = self._build_cumulative_distances(
                geometry, target_total_meters=result.distance_meters
            )

            amb.status = "BUSY" if has_patient else "DISPATCHED"
            amb.has_patient = has_patient
            amb.is_roaming = False  # Stopped
            amb.target_type = "HOSPITAL"
            amb.destination = AmbulanceDestination(
                hospital_id=result.hospital.id,
                hospital_name=result.hospital.name,
                latitude=result.hospital.latitude,
                longitude=result.hospital.longitude,
            )
            amb.route_edge_ids = result.edge_ids
            amb.full_route_geometry = geometry
            amb.cumulative_distances = cum_dists
            amb.total_distance_m = total_dist
            amb.current_distance_m = 0.0
            amb.route_geometry = geometry
            amb.speed_mps = max(10.0, 12.0 * alpha_emergency)
            amb.eta_seconds = total_dist / max(amb.speed_mps, 0.5)

            return amb.to_model()

    def get_summary(self) -> FleetSummary:
        """Return dynamic fleet summary."""
        with self._lock:
            roaming = sum(1 for a in self.ambulances.values() if a.is_roaming and a.status == "AVAILABLE" and not a.has_patient)
            standby = sum(1 for a in self.ambulances.values() if not a.is_roaming and a.status == "AVAILABLE" and not a.has_patient)
            available = sum(1 for a in self.ambulances.values() if a.status == "AVAILABLE" and not a.has_patient)
            dispatched = sum(1 for a in self.ambulances.values() if a.status == "DISPATCHED")
            with_patient = sum(1 for a in self.ambulances.values() if a.has_patient)
            return FleetSummary(
                total=len(self.ambulances),
                roaming=roaming,
                standby=standby,
                available=available,
                dispatched=dispatched,
                with_patient=with_patient,
            )

    def get_all(self) -> List[AmbulanceState]:
        """Return states of all 30 ambulances."""
        with self._lock:
            now = time.time()
            dt = now - self._last_tick
            if dt >= 0.5:
                self.step(dt)
                self._last_tick = now

            return [amb.to_model() for amb in self.ambulances.values()]

    def get_by_id(self, ambulance_id: str) -> Optional[AmbulanceState]:
        """Return state of a single ambulance."""
        with self._lock:
            amb = self.ambulances.get(ambulance_id)
            if amb is None:
                return None
            return amb.to_model()

    def reset(self) -> List[AmbulanceState]:
        """Reset fleet to initial simulation state."""
        self.initialize_fleet()
        return self.get_all()

    def start_background_simulation(self, interval: float = 1.0) -> None:
        """Start a background daemon thread that steps simulation every interval seconds."""
        if self._running:
            return

        self._running = True
        self._last_tick = time.time()

        def _loop():
            while self._running:
                try:
                    time.sleep(interval)
                    now = time.time()
                    dt = now - self._last_tick
                    self._last_tick = now
                    self.step(dt)
                except Exception as exc:
                    logger.exception("Error in simulation loop: %s", exc)

        self._thread = threading.Thread(target=_loop, daemon=True, name="ambulance-simulation")
        self._thread.start()
        logger.info("Ambulance simulation daemon started (interval=%.1fs)", interval)

    def stop_background_simulation(self) -> None:
        """Stop background simulation daemon."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
            self._thread = None
        logger.info("Ambulance simulation daemon stopped")
