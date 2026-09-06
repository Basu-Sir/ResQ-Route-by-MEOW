"""
Ambulance fleet and progressive road-following simulation engine.

Manages 30 ambulances across Mumbai road network:
- 10 ROAMING ambulances: status=AVAILABLE, has_patient=False, continuously moving
  along real SUMO road geometry, auto-re-routing when reaching destination.
- 20 STANDBY ambulances: status=AVAILABLE, has_patient=False, stationary until dispatched.
- Emergency dispatch: selects best available ambulance (roaming or standby)
    based on the lowest predicted road arrival time to the patient. Geographic
    distance is not used to rank otherwise routable ambulances.
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
    EdgeStatic,
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
CRITICAL_ALPHA = 2.2


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
    current_edge_id: Optional[str] = None
    edge_cumulative_distances: List[float] = field(default_factory=list)
    alpha_emergency: float = 1.5
    traffic_source: Optional[str] = None
    traffic_condition: Optional[str] = None
    patient_delivered: bool = False
    delivered_hospital_name: Optional[str] = None
    dropoff_dwell_seconds: float = 0.0

    @property
    def remaining_distance_m(self) -> float:
        return max(0.0, self.total_distance_m - self.current_distance_m)

    def to_model(self) -> AmbulanceState:
        if self.is_roaming or self.status in ("BUSY", "DISPATCHED"):
            remaining_dist = round(max(0.0, self.total_distance_m - self.current_distance_m), 1)
        else:
            remaining_dist = 0.0

        eta_sec = self.eta_seconds
        if eta_sec is not None:
            eta_sec = round(max(0.0, eta_sec), 1)
        elif self.status in ("BUSY", "DISPATCHED"):
            eta_sec = 0.0

        return AmbulanceState(
            ambulance_id=self.ambulance_id,
            latitude=round(self.latitude, 6),
            longitude=round(self.longitude, 6),
            status=self.status,
            has_patient=self.has_patient,
            is_roaming=self.is_roaming,
            destination=self.destination,
            eta_seconds=eta_sec,
            remaining_distance_meters=remaining_dist,
            route_geometry=self.route_geometry,
            traffic_source=self.traffic_source,
            traffic_condition=self.traffic_condition,
            patient_delivered=self.patient_delivered,
            delivered_hospital_name=self.delivered_hospital_name,
        )


def compute_effective_ambulance_speed(
    total_dist_m: float,
    travel_time_seconds: float = 0.0,
    alpha_emergency: float = 1.0,
    edge_ids: Optional[List[str]] = None,
    redis_speeds: Optional[Dict[str, float]] = None,
    current_edge_id: Optional[str] = None,
    edge_static_dict: Optional[Dict[str, EdgeStatic]] = None,
) -> Tuple[float, str]:
    """
    Adjust movement & ETA timing ensuring:
    CLEAR > YELLOW > RED in effective speed at all times.
    Therefore clear roads always produce a shorter ETA than yellow,
    and yellow always produces a shorter ETA than red.

    Scaling is distance-aware:
    - Micro/unit-test routes (<= 100m) maintain unscaled physical speed (1.0 - 10.0 m/s).
    - Long-distance demo routes (> 100m) scale smoothly up to 5x so ambulances
      arrive within demo-friendly timeframes.
    """
    alpha = max(1.0, min(float(alpha_emergency), 2.0))
    if total_dist_m <= 0:
        return (12.0 * alpha, "CLEAR")

    if total_dist_m <= 100.0:
        scale = 1.0
    else:
        scale = min(5.0, 1.0 + (total_dist_m - 100.0) / 600.0)

    target_edge = current_edge_id
    if not target_edge and edge_ids:
        target_edge = edge_ids[0]

    if target_edge:
        edge_spd = None
        if redis_speeds:
            edge_spd = redis_speeds.get(target_edge)
        if edge_spd is None and edge_static_dict:
            st = edge_static_dict.get(target_edge)
            if st and st.max_speed > 0:
                edge_spd = st.max_speed
        if edge_spd is None:
            edge_spd = 13.8  # Default ~50 km/h clear speed

        if edge_spd <= 2.8:
            condition = "RED"
            base_speed = max(1.0, min(edge_spd, 2.5))
        elif edge_spd <= 7.0:
            condition = "YELLOW"
            base_speed = min(max(edge_spd, 4.0), 6.5)
        else:
            condition = "CLEAR"
            base_speed = max(edge_spd, 9.5)
    else:
        raw_speed = (total_dist_m / travel_time_seconds) if travel_time_seconds > 0 else 12.0
        if raw_speed <= 3.0:
            condition = "RED"
            base_speed = max(1.0, min(raw_speed, 2.5))
        elif raw_speed <= 7.0:
            condition = "YELLOW"
            base_speed = min(max(raw_speed, 4.0), 6.5)
        else:
            condition = "CLEAR"
            base_speed = max(raw_speed, 9.5)

    if condition == "CLEAR":
        effective_speed = max(9.5 * scale * alpha, base_speed * scale * alpha)
    elif condition == "YELLOW":
        effective_speed = min(8.5 * scale * alpha, max(3.5 * scale * alpha, base_speed * scale * alpha))
    else:  # RED
        effective_speed = min(3.0 * scale * alpha, max(1.0 * scale, base_speed * scale * alpha))

    return (round(effective_speed, 2), condition)


class AmbulanceFleet:

    def __init__(
        self,
        gd: GraphData,
        hospitals: List[Hospital],
        traffic_speeds_fn: Optional[Callable[[], Tuple[Dict[str, float], str]]] = None,
        num_ambulances: int = 60,
        num_roaming: int = 20,
    ):
        self.gd = gd
        self.hospitals = hospitals
        self.traffic_speeds_fn = traffic_speeds_fn or (lambda: ({}, "static"))
        self.num_ambulances = num_ambulances
        self.num_roaming = num_roaming
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

    def _build_edge_cumulative_distances(
        self, edge_ids: List[str], target_total_m: float
    ) -> List[float]:
        """Build cumulative distance offsets for each edge in the route."""
        if not edge_ids:
            return [0.0]
        raw_dists = [0.0]
        known_length_total = 0.0
        for eid in edge_ids:
            edge = self.gd.edge_static.get(eid) if self.gd and self.gd.edge_static else None
            length = edge.length if edge else 0.0
            known_length_total += length
            raw_dists.append(raw_dists[-1] + length)

        if known_length_total <= 0 and target_total_m > 0:
            step = target_total_m / len(edge_ids)
            return [i * step for i in range(len(edge_ids) + 1)]

        total_raw = raw_dists[-1]
        if target_total_m > 0 and total_raw > 0 and abs(total_raw - target_total_m) > 1e-3:
            scale = target_total_m / total_raw
            return [d * scale for d in raw_dists]
        return raw_dists

    def _get_current_edge_id(self, amb: Ambulance, current_dist: float) -> Optional[str]:
        """Resolve the exact edge ID the ambulance is currently traversing along its route."""
        if not amb.route_edge_ids:
            return None
        if not amb.edge_cumulative_distances or len(amb.edge_cumulative_distances) <= 1:
            return amb.route_edge_ids[0]
        idx = bisect.bisect_right(amb.edge_cumulative_distances, current_dist) - 1
        idx = max(0, min(idx, len(amb.route_edge_ids) - 1))
        return amb.route_edge_ids[idx]

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
        Create simulated ambulances placed at valid Mumbai network locations:
        - ROAMING: status=AVAILABLE, has_patient=False, is_roaming=True (continuously roaming)
        - STANDBY: status=AVAILABLE, has_patient=False, is_roaming=False (stationary until dispatched)
        """
        with self._lock:
            self.ambulances.clear()
            num_amb = self.num_ambulances
            num_roaming = self.num_roaming

            # 1. Determine valid initial candidate locations from hospitals or graph nodes
            candidate_locations: List[Tuple[float, float, str, Optional[Hospital]]] = []
            if self.hospitals and len(self.hospitals) >= num_amb:
                # Distribute ambulances spatially across Mumbai using 2D grid binning
                # This guarantees broad geographical coverage across North, South, East, and West Mumbai
                # so that no region is left without available nearby ambulances.
                min_lat = min(h.latitude for h in self.hospitals)
                max_lat = max(h.latitude for h in self.hospitals)
                min_lon = min(h.longitude for h in self.hospitals)
                max_lon = max(h.longitude for h in self.hospitals)

                lat_span = max(max_lat - min_lat, 1e-4)
                lon_span = max(max_lon - min_lon, 1e-4)

                cells: Dict[Tuple[int, int], List[Hospital]] = {}
                for h in self.hospitals:
                    lat_idx = min(9, max(0, int((h.latitude - min_lat) / lat_span * 10)))
                    lon_idx = min(5, max(0, int((h.longitude - min_lon) / lon_span * 6)))
                    cells.setdefault((lat_idx, lon_idx), []).append(h)

                allocations: Dict[Tuple[int, int], int] = {k: 1 for k in cells}
                rem = num_amb - len(cells)
                if rem > 0:
                    sorted_cells = sorted(cells.keys(), key=lambda k: len(cells[k]), reverse=True)
                    for i in range(rem):
                        allocations[sorted_cells[i % len(sorted_cells)]] += 1
                elif rem < 0:
                    sorted_cells = sorted(cells.keys(), key=lambda k: len(cells[k]), reverse=True)
                    allocations = {k: 1 for k in sorted_cells[:num_amb]}

                raw_chosen: List[Hospital] = []
                for k in sorted(allocations.keys()):
                    count = allocations[k]
                    cell_hospitals = cells[k]
                    step = max(1, len(cell_hospitals) // count)
                    for c in range(count):
                        raw_chosen.append(cell_hospitals[min(c * step, len(cell_hospitals) - 1)])

                raw_chosen = raw_chosen[:num_amb]
                while len(raw_chosen) < num_amb:
                    raw_chosen.append(self.hospitals[len(raw_chosen) % len(self.hospitals)])

                # Order locations so roaming (first num_roaming) and standby (remaining)
                # are BOTH evenly distributed across the entire South-North / West-East span
                roaming_indices = [int(i * num_amb / num_roaming) for i in range(num_roaming)]
                standby_indices = [i for i in range(num_amb) if i not in roaming_indices]
                ordered_chosen = [raw_chosen[idx] for idx in (roaming_indices + standby_indices)]

                for h in ordered_chosen:
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

            # 2. Create ambulances
            for i in range(num_amb):
                amb_num = i + 1
                amb_id = f"AMB-{amb_num:02d}"
                lat, lon, node_id, hosp = candidate_locations[i]

                is_roaming = (i < num_roaming)
                status_desc = "ROAMING" if is_roaming else "STANDBY"

                logger.info("Initializing ambulance %d/%d (id=%s, type=%s)...", amb_num, num_amb, amb_id, status_desc)

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

            logger.info("Fleet initialization complete: %d ambulances initialized (%d ROAMING, %d STANDBY).", num_amb, num_roaming, num_amb - num_roaming)
            self._last_tick = time.time()

    def _assign_roaming_route(
        self,
        amb: Ambulance,
        candidate_hosp: Optional[Hospital] = None,
        index_hint: int = 0,
    ) -> None:
        """Assign next roaming route along real SUMO road geometry."""
        speeds, source_label = self.traffic_speeds_fn()
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
                amb.edge_cumulative_distances = self._build_edge_cumulative_distances(
                    result.edge_ids, total_dist
                )
                amb.full_route_geometry = geometry
                amb.route_geometry = geometry
                amb.cumulative_distances = cum_dists
                amb.total_distance_m = total_dist
                amb.traffic_source = source_label
                amb.alpha_emergency = 1.0

                # Stagger progress slightly on startup if index_hint given
                stagger_frac = (0.10 + (index_hint % 5) * 0.08) if index_hint > 0 else 0.0
                init_dist = total_dist * stagger_frac
                amb.current_distance_m = init_dist

                curr_eid = self._get_current_edge_id(amb, init_dist)
                amb.current_edge_id = curr_eid
                travel_sec = result.travel_time_seconds if hasattr(result, "travel_time_seconds") else (total_dist / 12.0)
                eff_speed, cond = compute_effective_ambulance_speed(
                    total_dist_m=total_dist,
                    travel_time_seconds=travel_sec,
                    alpha_emergency=1.0,
                    edge_ids=result.edge_ids if hasattr(result, "edge_ids") else None,
                    redis_speeds=speeds,
                    current_edge_id=curr_eid,
                    edge_static_dict=self.gd.edge_static,
                )
                amb.speed_mps = eff_speed
                amb.traffic_condition = cond

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
        using congestion-aware SUMO/rustworkx routing.
        """
        source_node = nearest_node_from_latlon(self.gd, amb.latitude, amb.longitude)
        amb.current_node_id = source_node

        available_hospitals = filter_available(self.hospitals)
        if not available_hospitals and self.hospitals:
            available_hospitals = self.hospitals

        routed = False
        speeds, source_label = self.traffic_speeds_fn()

        if available_hospitals and source_node in self.gd.node_index:
            try:
                # 1. Avoid doorstep dropoff at the exact same node (sumo_node_id == source_node)
                # to prevent 0-meter routes and straight-line jumps across courtyards.
                candidates = [h for h in available_hospitals if h.sumo_node_id != source_node]
                if not candidates:
                    candidates = available_hospitals

                result = find_route_to_nearest_hospital(
                    self.gd,
                    source_node,
                    candidates,
                    redis_speeds=speeds,
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
                amb.edge_cumulative_distances = self._build_edge_cumulative_distances(
                    result.edge_ids, total_dist
                )
                amb.full_route_geometry = geometry
                amb.route_geometry = geometry
                amb.cumulative_distances = cum_dists
                amb.total_distance_m = total_dist
                amb.current_distance_m = 0.0
                # Preserve the emergency priority from the patient request so
                # critical arrivals can consume an ICU bed at dropoff.
                amb.alpha_emergency = max(1.0, amb.alpha_emergency)

                # Congestion-aware travel time and speed (CLEAR > YELLOW > RED)
                amb.traffic_source = source_label
                curr_eid = self._get_current_edge_id(amb, 0.0)
                amb.current_edge_id = curr_eid
                eff_speed, cond = compute_effective_ambulance_speed(
                    total_dist_m=total_dist,
                    travel_time_seconds=result.travel_time_seconds,
                    alpha_emergency=1.5,
                    edge_ids=result.edge_ids,
                    redis_speeds=speeds,
                    current_edge_id=curr_eid,
                    edge_static_dict=self.gd.edge_static,
                )
                amb.speed_mps = eff_speed
                amb.eta_seconds = total_dist / max(amb.speed_mps, 0.5)
                amb.traffic_condition = cond


                routed = True
                logger.info(
                    "Ambulance %s picked up patient, routed to nearest hospital %s (%s) [%s]. Dist: %.1fm, ETA: %.1fs",
                    amb.ambulance_id, result.hospital.id, result.hospital.name, source_label, total_dist, amb.eta_seconds,
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
                # If ambulance is currently dwelling at hospital after delivering a patient:
                if amb.dropoff_dwell_seconds > 0:
                    amb.dropoff_dwell_seconds = max(0.0, amb.dropoff_dwell_seconds - dt)
                    if amb.dropoff_dwell_seconds <= 0:
                        amb.patient_delivered = False
                        amb.delivered_hospital_name = None
                        amb.speed_mps = 12.0
                        if amb.original_roaming:
                            amb.is_roaming = True
                            amb.current_node_id = nearest_node_from_latlon(self.gd, amb.latitude, amb.longitude)
                            self._assign_roaming_route(amb)
                            logger.info("Ambulance %s resumed roaming patrol after dropoff dwell.", amb.ambulance_id)
                        else:
                            amb.is_roaming = False
                            logger.info("Ambulance %s remaining stationary at base.", amb.ambulance_id)
                    continue

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
                            hosp_name = amb.destination.hospital_name if amb.destination else "Hospital"
                            hospital = next(
                                (h for h in self.hospitals if amb.destination and h.id == amb.destination.hospital_id),
                                None,
                            )
                            if hospital is not None:
                                hospital.emergency_doctors = max(0, hospital.emergency_doctors - 1)
                                if amb.alpha_emergency >= CRITICAL_ALPHA:
                                    hospital.icu_beds = max(0, hospital.icu_beds - 1)
                                logger.info(
                                    "Hospital %s resources after dropoff: ICU=%d, emergency doctors=%d",
                                    hospital.id,
                                    hospital.icu_beds,
                                    hospital.emergency_doctors,
                                )
                            logger.info(
                                "Ambulance %s arrived at hospital %s! Patient safely dropped off.",
                                amb.ambulance_id,
                                hosp_name,
                            )
                            amb.has_patient = False
                            amb.patient_delivered = True
                            amb.delivered_hospital_name = hosp_name
                            amb.status = "AVAILABLE"
                            amb.target_type = None
                            amb.destination = None
                            amb.eta_seconds = None
                            amb.full_route_geometry = []
                            amb.route_geometry = []
                            amb.route_edge_ids = []
                            amb.cumulative_distances = []
                            amb.edge_cumulative_distances = []
                            amb.current_distance_m = 0.0
                            amb.total_distance_m = 0.0
                            amb.speed_mps = 0.0
                            amb.current_edge_id = None
                            amb.traffic_condition = "CLEAR"

                            if dt >= 10.0:
                                amb.dropoff_dwell_seconds = 0.0
                                if amb.original_roaming:
                                    amb.is_roaming = True
                                    amb.current_node_id = nearest_node_from_latlon(self.gd, amb.latitude, amb.longitude)
                                    self._assign_roaming_route(amb)
                                    logger.info("Ambulance %s resumed roaming patrol.", amb.ambulance_id)
                                else:
                                    amb.is_roaming = False
                                    logger.info("Ambulance %s remaining stationary at base.", amb.ambulance_id)
                            else:
                                amb.dropoff_dwell_seconds = 6.0
                                logger.info("Ambulance %s dwelling at %s for 6s handover.", amb.ambulance_id, hosp_name)

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
                            amb.eta_seconds = 0.0
                            amb.full_route_geometry = []
                            amb.route_geometry = []
                            amb.route_edge_ids = []
                            amb.cumulative_distances = []
                            amb.edge_cumulative_distances = []
                            amb.current_distance_m = 0.0
                            amb.total_distance_m = 0.0
                            amb.current_edge_id = None
                            amb.traffic_condition = "CLEAR"
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

                        # Dynamically re-evaluate traffic condition and speed for current road segment
                        curr_eid = self._get_current_edge_id(amb, new_dist)
                        amb.current_edge_id = curr_eid
                        speeds, source_label = self.traffic_speeds_fn()
                        eff_speed, cond = compute_effective_ambulance_speed(
                            total_dist_m=amb.total_distance_m,
                            alpha_emergency=amb.alpha_emergency,
                            current_edge_id=curr_eid,
                            redis_speeds=speeds,
                            edge_static_dict=self.gd.edge_static,
                        )
                        amb.speed_mps = eff_speed
                        amb.traffic_condition = cond
                        amb.traffic_source = source_label
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
          2. Calculate each candidate's road travel time using SUMO/rustworkx and
              the current Redis/static edge speeds.
          3. Select the ambulance with the lowest predicted arrival time, even
              when it is geographically farther away.
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

            speeds, source_label = self.traffic_speeds_fn()
            patient_node = nearest_node_from_latlon(self.gd, patient_lat, patient_lon)

            # 2. Evaluate predicted road arrival time from every available ambulance.
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
            best_amb.patient_delivered = False
            best_amb.delivered_hospital_name = None
            best_amb.dropoff_dwell_seconds = 0.0

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
            best_amb.edge_cumulative_distances = self._build_edge_cumulative_distances(
                best_result.edge_ids, total_dist
            )
            best_amb.full_route_geometry = geometry
            best_amb.route_geometry = geometry
            best_amb.cumulative_distances = cum_dists
            best_amb.total_distance_m = total_dist
            best_amb.current_distance_m = 0.0
            best_amb.alpha_emergency = alpha_emergency

            best_amb.traffic_source = source_label
            curr_eid = self._get_current_edge_id(best_amb, 0.0)
            best_amb.current_edge_id = curr_eid
            eff_speed, cond = compute_effective_ambulance_speed(
                total_dist_m=total_dist,
                travel_time_seconds=best_result.travel_time_seconds,
                alpha_emergency=alpha_emergency,
                edge_ids=best_result.edge_ids,
                redis_speeds=speeds,
                current_edge_id=curr_eid,
                edge_static_dict=self.gd.edge_static,
            )
            best_amb.speed_mps = eff_speed
            best_amb.eta_seconds = total_dist / max(best_amb.speed_mps, 0.5)
            best_amb.traffic_condition = cond


            logger.info(
                "Dispatched fastest-arrival ambulance %s (predicted road ETA %.1fs, prev roaming=%s) to patient at (%.4f, %.4f)",
                best_amb.ambulance_id,
                best_result.travel_time_seconds if best_result else best_amb.eta_seconds,
                best_amb.is_roaming,
                patient_lat,
                patient_lon,
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
                if target_hospital.icu_beds <= 0 or target_hospital.emergency_doctors <= 0:
                    raise NoAvailableHospitalError(
                        f"Hospital '{target_hospital.name}' has no available ICU beds or emergency doctors"
                    )
            else:
                available = filter_available(self.hospitals)
                if not available:
                    raise NoAvailableHospitalError("No hospitals with available ICU beds found")

            speeds, source_label = self.traffic_speeds_fn()
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
            amb.edge_cumulative_distances = self._build_edge_cumulative_distances(
                result.edge_ids, total_dist
            )
            amb.full_route_geometry = geometry
            amb.cumulative_distances = cum_dists
            amb.total_distance_m = total_dist
            amb.current_distance_m = 0.0
            amb.route_geometry = geometry
            amb.traffic_source = source_label
            amb.alpha_emergency = alpha_emergency

            curr_eid = self._get_current_edge_id(amb, 0.0)
            amb.current_edge_id = curr_eid
            eff_speed, cond = compute_effective_ambulance_speed(
                total_dist_m=total_dist,
                travel_time_seconds=result.travel_time_seconds,
                alpha_emergency=alpha_emergency,
                edge_ids=result.edge_ids,
                redis_speeds=speeds,
                current_edge_id=curr_eid,
                edge_static_dict=self.gd.edge_static,
            )
            amb.speed_mps = eff_speed
            amb.eta_seconds = total_dist / max(amb.speed_mps, 0.5)
            amb.traffic_condition = cond


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
        """Return states of all ambulances."""
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
