"""
traffic_service.py

Manages live traffic congestion in Redis (`traffic:speeds`).
Generates realistic congestion corridors across central Mumbai bottlenecks
(Dharavi-Sion, Kurla-BKC, Dadar TT, SCLR, Western & Eastern Express highways),
persists live speeds directly into Redis, and provides formatted GeoJSON-style
polyline geometries for frontend map rendering.
"""
import json
import logging
import random
import threading
import time
from typing import Dict, List, Optional, Tuple

from backend import config, redis_client
from backend.graph_loader import GraphData, edge_ids_to_lonlat_geometry
from backend.models import CongestedSegment, TrafficCongestionResponse

logger = logging.getLogger("traffic_service")

# Key congestion corridors across central Mumbai
CONGESTION_CORRIDORS = [
    {
        "name": "Dharavi-Sion Bottleneck",
        "lat": 19.043,
        "lon": 72.860,
        "radius": 0.009,
        "heavy_prob": 0.65,
    },
    {
        "name": "Kurla-BKC Connector",
        "lat": 19.068,
        "lon": 72.875,
        "radius": 0.010,
        "heavy_prob": 0.60,
    },
    {
        "name": "Dadar TT & Ambedkar Road",
        "lat": 19.019,
        "lon": 72.845,
        "radius": 0.009,
        "heavy_prob": 0.55,
    },
    {
        "name": "SCLR & Chembur Link",
        "lat": 19.075,
        "lon": 72.895,
        "radius": 0.011,
        "heavy_prob": 0.55,
    },
    {
        "name": "Western Express Corridor (Bandra-Santacruz)",
        "lat": 19.062,
        "lon": 72.842,
        "radius": 0.010,
        "heavy_prob": 0.60,
    },
    {
        "name": "Eastern Express Corridor (Ghatkopar)",
        "lat": 19.088,
        "lon": 72.915,
        "radius": 0.010,
        "heavy_prob": 0.50,
    },
]

# In-memory geometry cache so GET /traffic/congestion returns in < 5ms
_GEOMETRY_CACHE: Dict[str, List[List[float]]] = {}
_CACHE_LOCK = threading.Lock()
_SIMULATION_THREAD: Optional[threading.Thread] = None
_RUNNING = False


def find_corridor_edges(gd: GraphData) -> Dict[str, dict]:
    """
    Identifies edges from the SUMO graph that lie inside key Mumbai congestion corridors.
    Returns mapping: edge_id -> {corridor_name, heavy_prob, static_max_speed, length}
    """
    if not gd or not gd.edge_static or not gd.node_coords or gd.net is None:
        return {}

    corridor_edges = {}
    for edge_id, edge in gd.edge_static.items():
        if edge.length < 25.0:  # Skip tiny junction fragments for clean map display
            continue
        if edge.from_node not in gd.node_coords:
            continue

        nx, ny = gd.node_coords[edge.from_node]
        try:
            if hasattr(gd.net, "convertXY2LonLat"):
                lon, lat = gd.net.convertXY2LonLat(nx, ny)
            else:
                lon, lat = nx, ny
        except Exception:
            continue

        for corridor in CONGESTION_CORRIDORS:
            d = ((lat - corridor["lat"]) ** 2 + (lon - corridor["lon"]) ** 2) ** 0.5
            if d <= corridor["radius"]:
                corridor_edges[edge_id] = {
                    "corridor": corridor["name"],
                    "heavy_prob": corridor["heavy_prob"],
                    "max_speed": edge.max_speed,
                    "length": edge.length,
                }
                break

    return corridor_edges


def seed_traffic_in_redis(
    gd: GraphData,
    force: bool = False,
    client: Optional[object] = None,
) -> Dict[str, float]:
    """
    Populates Redis (`traffic:speeds`) with realistic congestion data.
    - RED (Heavy): 1.2 - 2.5 m/s (~4.3 - 9.0 km/h)
    - YELLOW (Moderate): 3.8 - 6.2 m/s (~13.7 - 22.3 km/h)
    """
    client = client or redis_client.get_redis_client()
    if not redis_client.is_available(client):
        logger.warning("Redis not available; skipping traffic seeding")
        return {}

    existing = redis_client.read_speeds(client)
    # If Redis already has more than 50 real speeds and force=False, keep existing
    if not force and len(existing) > 50:
        logger.info("Redis already has %d traffic speeds; keeping existing", len(existing))
        return existing

    corridor_edges = find_corridor_edges(gd)
    if not corridor_edges:
        logger.warning("No corridor edges found to seed traffic")
        return {}

    speeds_to_write: Dict[str, float] = {}
    for edge_id, info in corridor_edges.items():
        is_heavy = random.random() < info["heavy_prob"]
        if is_heavy:
            speed = round(random.uniform(1.2, 2.5), 2)
        else:
            speed = round(random.uniform(3.8, 6.2), 2)
        speeds_to_write[edge_id] = speed

    # Batch write directly to Redis hash `traffic:speeds`
    redis_client.write_speeds(speeds_to_write, client)
    logger.info("Successfully seeded %d congested edge speeds to Redis", len(speeds_to_write))

    # Also save fallback JSON snapshot
    try:
        with open(config.FALLBACK_FILE, "w", encoding="utf-8") as f:
            json.dump(speeds_to_write, f, indent=2)
    except Exception as exc:
        logger.warning("Could not write fallback snapshot: %s", exc)

    return speeds_to_write


def get_congested_segments(
    gd: GraphData,
    max_segments: int = 400,
    client: Optional[object] = None,
) -> TrafficCongestionResponse:
    """
    Reads live speeds from Redis, classifies congestion levels, and returns
    lightweight GeoJSON polylines for the Leaflet frontend.
    - HEAVY (RED): speed <= 2.8 m/s (~10 km/h) or congestion_ratio <= 0.35
    - MODERATE (YELLOW): speed <= 7.0 m/s (~25 km/h) or congestion_ratio <= 0.65
    """
    global _GEOMETRY_CACHE
    client = client or redis_client.get_redis_client()
    source = "redis"
    speeds = {}

    if redis_client.is_available(client):
        speeds = redis_client.read_speeds(client)
    
    if not speeds:
        # Fallback to local file if Redis unreachable
        try:
            with open(config.FALLBACK_FILE, "r", encoding="utf-8") as f:
                speeds = json.load(f)
                source = "fallback"
        except Exception:
            speeds = {}
            source = "none"

    if not speeds or gd is None:
        return TrafficCongestionResponse(
            total_congested_segments=0,
            heavy_count=0,
            moderate_count=0,
            source=source,
            segments=[],
        )

    # Filter and sort by severity (heavy first)
    classified: List[Tuple[str, str, float, float, float]] = []
    for edge_id, speed in speeds.items():
        if edge_id not in gd.edge_static:
            continue
        edge_static = gd.edge_static[edge_id]
        normal_speed = edge_static.max_speed
        if normal_speed <= 0:
            continue

        ratio = speed / normal_speed
        if speed <= 2.8 or ratio <= 0.35:
            level = "HEAVY"
        elif speed <= 7.0 or ratio <= 0.65:
            level = "MODERATE"
        else:
            continue  # Normal flow; omit from congestion overlay

        classified.append((edge_id, level, speed, normal_speed, ratio))

    # Separate into heavy and moderate to ensure BOTH colors are well represented on the map
    heavy_items = [item for item in classified if item[1] == "HEAVY"]
    moderate_items = [item for item in classified if item[1] == "MODERATE"]

    # Target roughly 55% heavy (red) and 45% moderate (yellow) up to max_segments
    target_heavy = int(max_segments * 0.55)
    target_mod = max_segments - target_heavy

    selected = heavy_items[:target_heavy] + moderate_items[:target_mod]


    # Resolve geometries with caching
    segments: List[CongestedSegment] = []
    with _CACHE_LOCK:
        for edge_id, level, speed, normal_speed, ratio in selected:
            if edge_id in _GEOMETRY_CACHE:
                geom = _GEOMETRY_CACHE[edge_id]
            else:
                geom = edge_ids_to_lonlat_geometry(gd, [edge_id])
                if geom:
                    _GEOMETRY_CACHE[edge_id] = geom

            if geom and len(geom) >= 2:
                segments.append(
                    CongestedSegment(
                        edge_id=edge_id,
                        level=level,
                        speed_kmh=round(speed * 3.6, 1),
                        normal_speed_kmh=round(normal_speed * 3.6, 1),
                        congestion_ratio=round(ratio, 2),
                        geometry=geom,
                    )
                )

    heavy_count = sum(1 for s in segments if s.level == "HEAVY")
    moderate_count = sum(1 for s in segments if s.level == "MODERATE")

    return TrafficCongestionResponse(
        total_congested_segments=len(segments),
        heavy_count=heavy_count,
        moderate_count=moderate_count,
        source=source,
        segments=segments,
    )


def _traffic_fluctuation_worker(gd: GraphData) -> None:
    """Lightweight background thread that slightly adjusts Redis speeds every 25s."""
    global _RUNNING
    client = redis_client.get_redis_client()
    while _RUNNING:
        time.sleep(25.0)
        if not _RUNNING:
            break
        try:
            if not redis_client.is_available(client):
                continue
            speeds = redis_client.read_speeds(client)
            if not speeds:
                continue

            # Pick ~5% of edges and apply slight fluctuation
            keys = list(speeds.keys())
            sample_keys = random.sample(keys, min(len(keys), max(10, len(keys) // 20)))
            updates = {}
            for k in sample_keys:
                old_spd = speeds[k]
                factor = random.uniform(0.9, 1.1)
                new_spd = round(max(1.0, min(14.0, old_spd * factor)), 2)
                updates[k] = new_spd

            if updates:
                redis_client.write_speeds(updates, client)
                logger.debug("Fluctuated %d edge speeds in Redis", len(updates))
        except Exception as exc:
            logger.debug("Error in traffic fluctuation worker: %s", exc)


def start_traffic_simulation(gd: GraphData) -> None:
    """Start dynamic traffic fluctuation background daemon."""
    global _SIMULATION_THREAD, _RUNNING
    if _SIMULATION_THREAD is not None and _SIMULATION_THREAD.is_alive():
        return
    _RUNNING = True
    _SIMULATION_THREAD = threading.Thread(
        target=_traffic_fluctuation_worker,
        args=(gd,),
        daemon=True,
        name="TrafficFluctuationDaemon",
    )
    _SIMULATION_THREAD.start()
    logger.info("Traffic fluctuation background daemon started")


def stop_traffic_simulation() -> None:
    """Stop dynamic traffic fluctuation background daemon."""
    global _RUNNING
    _RUNNING = False
