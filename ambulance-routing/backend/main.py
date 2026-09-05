"""
FastAPI application.

FastAPI never talks to TraCI directly. It only reads traffic speeds from
Redis (with a JSON-fallback and static-SUMO-speed fallback below that).
"""
import logging
from typing import List

from fastapi import FastAPI, HTTPException

from backend import config, redis_client
from backend.graph_loader import (
    GraphData,
    edge_ids_to_lonlat_geometry,  # NEW
    load_graph,
    nearest_node_from_latlon,
)
from backend.hospitals import load_hospitals, filter_available
from backend.models import (
    HealthResponse,
    HospitalListItem,  # NEW
    HospitalOut,
    RouteRequest,
    RouteResponse,
)
from backend.routing import (
    NoAvailableHospitalError,
    NoRouteFoundError,
    find_route_to_nearest_hospital,
)
from fallback.create_fallback import read_fallback_speeds

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main")

app = FastAPI(title="Ambulance Dynamic Routing Service")

app.state.graph_data: GraphData = None
app.state.hospitals = []


@app.on_event("startup")
def startup_event() -> None:
    logger.info("Loading SUMO network graph from %s", config.SUMO_NET_FILE)
    app.state.graph_data = load_graph(config.SUMO_NET_FILE)
    logger.info(
        "Graph loaded: %d nodes, %d edges",
        app.state.graph_data.num_nodes,
        app.state.graph_data.num_edges,
    )

    logger.info("Loading hospitals from %s", config.HOSPITALS_FILE)
    app.state.hospitals = load_hospitals(config.HOSPITALS_FILE)
    logger.info("Loaded %d hospitals", len(app.state.hospitals))


def get_traffic_speeds():
    """
    Redis -> fallback JSON -> static SUMO speeds (empty dict; routing.py
    falls back to each edge's static max_speed automatically).
    Returns (speeds_dict, source_label).
    """
    client = redis_client.get_redis_client()
    if redis_client.is_available(client):
        speeds = redis_client.read_speeds(client)
        if speeds:
            return speeds, "redis"

    fallback_speeds = read_fallback_speeds()
    if fallback_speeds:
        return fallback_speeds, "fallback"

    return {}, "static"


@app.post("/route", response_model=RouteResponse)
def route(req: RouteRequest):
    gd: GraphData = app.state.graph_data
    if gd is None:
        raise HTTPException(status_code=503, detail="Routing graph is not loaded yet")

    try:
        source_node_id = nearest_node_from_latlon(gd, req.latitude, req.longitude)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not resolve coordinates: {exc}")

    available_hospitals = filter_available(app.state.hospitals)
    if not available_hospitals:
        raise HTTPException(status_code=404, detail="No hospitals with available ICU beds")

    speeds, source_label = get_traffic_speeds()

    try:
        result = find_route_to_nearest_hospital(
            gd,
            source_node_id,
            available_hospitals,
            speeds,
            req.alpha_emergency,
        )
    except NoAvailableHospitalError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except NoRouteFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    # NEW: convert only this route's edges into a lightweight lon/lat
    # polyline for the frontend. Never touches the full network, and never
    # fails the request itself -- if geometry conversion has a problem,
    # the route response still returns with an empty route_geometry.
    try:
        geometry = edge_ids_to_lonlat_geometry(gd, result.edge_ids)
    except Exception:
        logger.exception("Failed to build route geometry; returning empty geometry")
        geometry = []

    h = result.hospital
    return RouteResponse(
        hospital=HospitalOut(
            id=h.id,
            name=h.name,
            latitude=h.latitude,
            longitude=h.longitude,
            sumo_node_id=h.sumo_node_id,
            icu_beds=h.icu_beds,
        ),
        route_edge_ids=result.edge_ids,
        distance_meters=round(result.distance_meters, 2),
        estimated_travel_time_seconds=round(result.travel_time_seconds, 2),
        traffic_source=source_label,
        source_node_id=source_node_id,
        alpha_emergency=req.alpha_emergency,
        route_geometry=geometry,  # NEW
    )


# NEW: lightweight hospital list for the frontend map. Returns only what a
# map marker needs -- no sumo_node_id, no graph internals. This is the only
# hospital-related payload the browser ever fetches in bulk.
@app.get("/hospitals", response_model=List[HospitalListItem])
def list_hospitals():
    return [
        HospitalListItem(
            id=h.id,
            name=h.name,
            latitude=h.latitude,
            longitude=h.longitude,
            icu_beds=h.icu_beds,
        )
        for h in app.state.hospitals
    ]


@app.get("/health", response_model=HealthResponse)
def health():
    gd: GraphData = app.state.graph_data
    client = redis_client.get_redis_client()
    redis_ok = redis_client.is_available(client)

    return HealthResponse(
        status="ok" if gd is not None else "degraded",
        graph_loaded=gd is not None,
        graph_nodes=gd.num_nodes if gd is not None else None,
        graph_edges=gd.num_edges if gd is not None else None,
        redis_connected=redis_ok,
        hospitals_loaded=len(app.state.hospitals) if app.state.hospitals else 0,
    )