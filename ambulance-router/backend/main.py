"""
FastAPI application.

FastAPI never talks to TraCI directly. It only reads traffic speeds from
Redis (with a JSON-fallback and static-SUMO-speed fallback below that).
"""
import logging
from typing import List, Optional

from fastapi import FastAPI, HTTPException

from backend import config, redis_client
from backend.graph_loader import (
    GraphData,
    edge_ids_to_lonlat_geometry,  # NEW
    load_graph,
    nearest_node_from_latlon,
)
from backend.fleet import AmbulanceFleet, AmbulanceHasPatientError
from backend.hospitals import load_hospitals, filter_available
from backend.models import (
    AmbulanceDispatchRequest,
    AmbulanceState,
    EmergencyRequest,
    EmergencyResponse,
    FleetSummary,
    HealthResponse,
    HospitalListItem,  # NEW
    HospitalOut,
    RouteRequest,
    RouteResponse,
    SimulationStepRequest,
    CongestedSegment,
    TrafficCongestionResponse,
)
from backend.routing import (
    NoAvailableHospitalError,
    NoRouteFoundError,
    find_route_to_nearest_hospital,
)
from backend.traffic_service import (
    get_congested_segments,
    seed_traffic_in_redis,
    start_traffic_simulation,
    stop_traffic_simulation,
)
from fallback.create_fallback import read_fallback_speeds


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main")

app = FastAPI(title="Ambulance Dynamic Routing Service")

app.state.graph_data: GraphData = None
app.state.hospitals = []
app.state.fleet: AmbulanceFleet = None


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

    logger.info("Initializing ambulance fleet (60 simulated ambulances)...")
    app.state.fleet = AmbulanceFleet(
        gd=app.state.graph_data,
        hospitals=app.state.hospitals,
        traffic_speeds_fn=get_traffic_speeds,
        num_ambulances=60,
        num_roaming=20,
    )
    app.state.fleet.start_background_simulation(interval=1.0)
    logger.info("Ambulance fleet initialized: %d ambulances", len(app.state.fleet.ambulances))

    logger.info("Seeding live traffic congestion into Redis...")
    seed_traffic_in_redis(app.state.graph_data)
    start_traffic_simulation(app.state.graph_data)


@app.on_event("shutdown")
def shutdown_event() -> None:
    stop_traffic_simulation()
    if hasattr(app.state, "fleet") and app.state.fleet:
        app.state.fleet.stop_background_simulation()



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
            emergency_doctors=h.emergency_doctors,
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
            emergency_doctors=h.emergency_doctors,
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
        ambulances_loaded=len(app.state.fleet.ambulances) if hasattr(app.state, "fleet") and app.state.fleet else 0,
    )


@app.get("/ambulances", response_model=List[AmbulanceState])
def list_ambulances():
    if not hasattr(app.state, "fleet") or app.state.fleet is None:
        raise HTTPException(status_code=503, detail="Ambulance fleet is not initialized")
    return app.state.fleet.get_all()


@app.get("/ambulances/summary", response_model=FleetSummary)
def get_fleet_summary():
    """Returns live fleet breakdown: total, roaming, standby, available, dispatched, with_patient."""
    if not hasattr(app.state, "fleet") or app.state.fleet is None:
        raise HTTPException(status_code=503, detail="Ambulance fleet is not initialized")
    return app.state.fleet.get_summary()


@app.get("/ambulances/{ambulance_id}", response_model=AmbulanceState)
def get_ambulance(ambulance_id: str):
    if not hasattr(app.state, "fleet") or app.state.fleet is None:
        raise HTTPException(status_code=503, detail="Ambulance fleet is not initialized")
    amb = app.state.fleet.get_by_id(ambulance_id)
    if amb is None:
        raise HTTPException(status_code=404, detail=f"Ambulance '{ambulance_id}' not found")
    return amb



@app.post("/ambulances/{ambulance_id}/dispatch", response_model=AmbulanceState)
def dispatch_ambulance(ambulance_id: str, req: Optional[AmbulanceDispatchRequest] = None):
    if not hasattr(app.state, "fleet") or app.state.fleet is None:
        raise HTTPException(status_code=503, detail="Ambulance fleet is not initialized")
    req = req or AmbulanceDispatchRequest()
    try:
        return app.state.fleet.dispatch(
            ambulance_id=ambulance_id,
            hospital_id=req.hospital_id,
            has_patient=req.has_patient,
            alpha_emergency=req.alpha_emergency,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Ambulance '{ambulance_id}' not found")
    except AmbulanceHasPatientError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except (NoRouteFoundError, NoAvailableHospitalError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Failed to dispatch ambulance %s: %s", ambulance_id, exc)
        raise HTTPException(status_code=500, detail=f"Dispatch failed: {exc}")


@app.post("/ambulances/reset", response_model=List[AmbulanceState])
def reset_ambulances():
    if not hasattr(app.state, "fleet") or app.state.fleet is None:
        raise HTTPException(status_code=503, detail="Ambulance fleet is not initialized")
    return app.state.fleet.reset()


@app.post("/ambulances/step", response_model=List[AmbulanceState])
def step_simulation(req: Optional[SimulationStepRequest] = None):
    if not hasattr(app.state, "fleet") or app.state.fleet is None:
        raise HTTPException(status_code=503, detail="Ambulance fleet is not initialized")
    seconds = req.seconds if req else 1.0
    app.state.fleet.step(seconds)
    return app.state.fleet.get_all()


@app.post("/ambulances/request", response_model=EmergencyResponse)
def request_emergency_ambulance(req: EmergencyRequest):
    """
    Emergency request endpoint:
    1. Considers all available ambulances (both roaming and standby).
    2. Calculates actual SUMO/rustworkx road travel time to the patient.
    3. Dispatches the closest/best ambulance to the patient.
    4. Stops its roaming behavior and starts moving toward patient.
    """
    if not hasattr(app.state, "fleet") or app.state.fleet is None:
        raise HTTPException(status_code=503, detail="Ambulance fleet is not initialized")
    try:
        return app.state.fleet.request_ambulance(
            patient_lat=req.latitude,
            patient_lon=req.longitude,
            alpha_emergency=req.alpha_emergency,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.exception("Failed to dispatch emergency ambulance: %s", exc)
        raise HTTPException(status_code=500, detail=f"Emergency dispatch failed: {exc}")


@app.get("/traffic/congestion", response_model=TrafficCongestionResponse)
def get_traffic_congestion_endpoint(limit: int = 400):
    """
    Returns active traffic congestion road segments (RED: heavy, YELLOW: moderate)
    read directly from Redis (`traffic:speeds`) with polyline geometries for map rendering.
    """
    gd: GraphData = app.state.graph_data
    if gd is None:
        raise HTTPException(status_code=503, detail="Routing graph is not loaded yet")
    return get_congested_segments(gd, max_segments=limit)


@app.post("/traffic/seed", response_model=TrafficCongestionResponse)
def seed_traffic_endpoint(limit: int = 400):
    """
    Manually triggers re-seeding of realistic traffic congestion corridors
    into Redis (`traffic:speeds`).
    """
    gd: GraphData = app.state.graph_data
    if gd is None:
        raise HTTPException(status_code=503, detail="Routing graph is not loaded yet")
    seed_traffic_in_redis(gd, force=True)
    return get_congested_segments(gd, max_segments=limit)

