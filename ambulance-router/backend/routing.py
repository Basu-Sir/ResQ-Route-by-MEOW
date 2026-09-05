"""
Dynamic shortest-path routing on top of the rustworkx graph.

weight(edge) = length / (max(live_speed, 0.5) * alpha_emergency)

A single multi-target Dijkstra traversal from the ambulance's source node
is used to reach every candidate hospital in one pass, instead of running
Dijkstra once per hospital.
"""
import logging
from dataclasses import dataclass
from typing import Callable, Dict, List, Tuple

import rustworkx as rx

from backend.graph_loader import GraphData
from backend.hospitals import Hospital

logger = logging.getLogger("routing")

MIN_EFFECTIVE_SPEED = 0.5  # m/s floor, avoids divide-by-zero / infinite weight


class NoRouteFoundError(Exception):
    pass


class NoAvailableHospitalError(Exception):
    pass


@dataclass
class RouteResult:
    hospital: Hospital
    edge_ids: List[str]
    distance_meters: float
    travel_time_seconds: float


def compute_effective_speed(live_speed: float) -> float:
    return max(live_speed, MIN_EFFECTIVE_SPEED)


def compute_edge_weight(length: float, speed: float, alpha_emergency: float) -> float:
    effective_speed = compute_effective_speed(speed)
    alpha = alpha_emergency if alpha_emergency > 0 else 1.0
    return length / (effective_speed * alpha)


def resolve_edge_speed(edge_id: str, static_speed: float, redis_speeds: Dict[str, float]) -> float:
    """Live speed from Redis if present, otherwise the edge's static SUMO speed."""
    if edge_id in redis_speeds:
        return redis_speeds[edge_id]
    return static_speed


def build_weight_fn(redis_speeds: Dict[str, float], alpha_emergency: float) -> Callable[[dict], float]:
    def weight_fn(edge_payload: dict) -> float:
        edge_id = edge_payload["edge_id"]
        static_speed = edge_payload["max_speed"]
        live_speed = resolve_edge_speed(edge_id, static_speed, redis_speeds)
        return compute_edge_weight(edge_payload["length"], live_speed, alpha_emergency)

    return weight_fn


def find_route_to_nearest_hospital(
    gd: GraphData,
    source_node_id: str,
    hospitals: List[Hospital],
    redis_speeds: Dict[str, float],
    alpha_emergency: float,
) -> RouteResult:
    if source_node_id not in gd.node_index:
        raise NoRouteFoundError(f"Source node '{source_node_id}' not found in graph")

    source_idx = gd.node_index[source_node_id]

    candidates: List[Tuple[Hospital, int]] = []
    for h in hospitals:
        node_idx = gd.node_index.get(h.sumo_node_id)
        if node_idx is not None:
            candidates.append((h, node_idx))

    if not candidates:
        raise NoAvailableHospitalError("No hospitals with a valid SUMO node were found")

    weight_fn = build_weight_fn(redis_speeds, alpha_emergency)

    # Single multi-target traversal: distances to ALL reachable nodes at once.
    lengths = rx.dijkstra_shortest_path_lengths(gd.graph, source_idx, edge_cost_fn=weight_fn)

    reachable = [(h, idx, lengths[idx]) for h, idx in candidates if idx in lengths]
    if not reachable:
        raise NoRouteFoundError("No candidate hospital is reachable from the ambulance location")

    best_hospital, best_idx, best_weight = min(reachable, key=lambda t: t[2])

    # Reconstruct the actual path only for the chosen target.
    paths = rx.dijkstra_shortest_paths(gd.graph, source_idx, target=best_idx, weight_fn=weight_fn)
    node_path = list(paths[best_idx])

    edge_ids: List[str] = []
    distance_meters = 0.0
    travel_time_seconds = 0.0

    for u, v in zip(node_path[:-1], node_path[1:]):
        edge_id = gd.edge_lookup.get((u, v))
        if edge_id is None:
            continue
        edge_static = gd.edge_static[edge_id]
        live_speed = resolve_edge_speed(edge_id, edge_static.max_speed, redis_speeds)
        effective_speed = compute_effective_speed(live_speed)

        edge_ids.append(edge_id)
        distance_meters += edge_static.length
        # Real physical travel time (alpha_emergency only biases route CHOICE,
        # not the reported ETA).
        travel_time_seconds += edge_static.length / effective_speed

    return RouteResult(
        hospital=best_hospital,
        edge_ids=edge_ids,
        distance_meters=distance_meters,
        travel_time_seconds=travel_time_seconds,
    )


def find_route_to_target_hospital(
    gd: GraphData,
    source_node_id: str,
    hospital: Hospital,
    redis_speeds: Dict[str, float],
    alpha_emergency: float,
) -> RouteResult:
    if source_node_id not in gd.node_index:
        raise NoRouteFoundError(f"Source node '{source_node_id}' not found in graph")

    target_idx = gd.node_index.get(hospital.sumo_node_id)
    if target_idx is None:
        raise NoRouteFoundError(f"Hospital node '{hospital.sumo_node_id}' not found in graph")

    source_idx = gd.node_index[source_node_id]
    weight_fn = build_weight_fn(redis_speeds, alpha_emergency)

    paths = rx.dijkstra_shortest_paths(gd.graph, source_idx, target=target_idx, weight_fn=weight_fn)
    if target_idx not in paths:
        raise NoRouteFoundError(f"Hospital '{hospital.name}' is not reachable from source node '{source_node_id}'")

    node_path = list(paths[target_idx])
    edge_ids: List[str] = []
    distance_meters = 0.0
    travel_time_seconds = 0.0

    for u, v in zip(node_path[:-1], node_path[1:]):
        edge_id = gd.edge_lookup.get((u, v))
        if edge_id is None:
            continue
        edge_static = gd.edge_static[edge_id]
        live_speed = resolve_edge_speed(edge_id, edge_static.max_speed, redis_speeds)
        effective_speed = compute_effective_speed(live_speed)

        edge_ids.append(edge_id)
        distance_meters += edge_static.length
        travel_time_seconds += edge_static.length / effective_speed

    return RouteResult(
        hospital=hospital,
        edge_ids=edge_ids,
        distance_meters=distance_meters,
        travel_time_seconds=travel_time_seconds,
    )


@dataclass
class NodeRouteResult:
    edge_ids: List[str]
    distance_meters: float
    travel_time_seconds: float


def find_route_between_nodes(
    gd: GraphData,
    source_node_id: str,
    target_node_id: str,
    redis_speeds: Dict[str, float],
    alpha_emergency: float,
) -> NodeRouteResult:
    if source_node_id not in gd.node_index:
        raise NoRouteFoundError(f"Source node '{source_node_id}' not found in graph")
    if target_node_id not in gd.node_index:
        raise NoRouteFoundError(f"Target node '{target_node_id}' not found in graph")

    source_idx = gd.node_index[source_node_id]
    target_idx = gd.node_index[target_node_id]

    weight_fn = build_weight_fn(redis_speeds, alpha_emergency)
    paths = rx.dijkstra_shortest_paths(gd.graph, source_idx, target=target_idx, weight_fn=weight_fn)
    if target_idx not in paths:
        raise NoRouteFoundError(f"Target node '{target_node_id}' is not reachable from source node '{source_node_id}'")

    node_path = list(paths[target_idx])
    edge_ids: List[str] = []
    distance_meters = 0.0
    travel_time_seconds = 0.0

    for u, v in zip(node_path[:-1], node_path[1:]):
        edge_id = gd.edge_lookup.get((u, v))
        if edge_id is None:
            continue
        edge_static = gd.edge_static[edge_id]
        live_speed = resolve_edge_speed(edge_id, edge_static.max_speed, redis_speeds)
        effective_speed = compute_effective_speed(live_speed)

        edge_ids.append(edge_id)
        distance_meters += edge_static.length
        travel_time_seconds += edge_static.length / effective_speed

    return NodeRouteResult(
        edge_ids=edge_ids,
        distance_meters=distance_meters,
        travel_time_seconds=travel_time_seconds,
    )