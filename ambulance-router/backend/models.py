"""
Pydantic request/response models for the FastAPI service.
"""
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator


class RouteRequest(BaseModel):
    latitude: float = Field(..., description="Ambulance latitude (WGS84)")
    longitude: float = Field(..., description="Ambulance longitude (WGS84)")
    alpha_emergency: float = Field(1.0, description="Emergency speed multiplier, must be > 0")

    @field_validator("latitude")
    @classmethod
    def validate_lat(cls, v: float) -> float:
        if not (-90.0 <= v <= 90.0):
            raise ValueError("latitude must be between -90 and 90")
        return v

    @field_validator("longitude")
    @classmethod
    def validate_lon(cls, v: float) -> float:
        if not (-180.0 <= v <= 180.0):
            raise ValueError("longitude must be between -180 and 180")
        return v

    @field_validator("alpha_emergency")
    @classmethod
    def validate_alpha(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("alpha_emergency must be greater than 0")
        return v


class HospitalOut(BaseModel):
    id: str
    name: str
    latitude: float
    longitude: float
    sumo_node_id: str
    icu_beds: int


# NEW: slim projection of HospitalOut for GET /hospitals. Deliberately
# omits sumo_node_id -- the browser has no use for SUMO internals, and
# dropping it keeps the ~930-hospital payload smaller.
class HospitalListItem(BaseModel):
    id: str
    name: str
    latitude: float
    longitude: float
    icu_beds: int


class RouteResponse(BaseModel):
    hospital: HospitalOut
    route_edge_ids: List[str]
    distance_meters: float
    estimated_travel_time_seconds: float
    traffic_source: str
    source_node_id: str
    alpha_emergency: float
    # NEW: [longitude, latitude] polyline for the selected route only,
    # derived from route_edge_ids. Never the full SUMO network.
    route_geometry: List[List[float]] = []


class HealthResponse(BaseModel):
    status: str
    graph_loaded: bool
    graph_nodes: Optional[int] = None
    graph_edges: Optional[int] = None
    redis_connected: bool
    hospitals_loaded: Optional[int] = None
    ambulances_loaded: Optional[int] = None


class AmbulanceDestination(BaseModel):
    hospital_id: str
    hospital_name: str
    latitude: float
    longitude: float


class AmbulanceState(BaseModel):
    ambulance_id: str
    latitude: float
    longitude: float
    status: str  # "AVAILABLE", "BUSY", "DISPATCHED"
    has_patient: bool
    is_roaming: bool = False
    destination: Optional[AmbulanceDestination] = None
    eta_seconds: Optional[float] = None
    remaining_distance_meters: Optional[float] = None
    route_geometry: List[List[float]] = []
    traffic_source: Optional[str] = None
    traffic_condition: Optional[str] = None
    patient_delivered: bool = False
    delivered_hospital_name: Optional[str] = None



class AmbulanceDispatchRequest(BaseModel):
    hospital_id: Optional[str] = None
    has_patient: bool = False
    alpha_emergency: float = 1.5


class EmergencyRequest(BaseModel):
    latitude: float = Field(..., description="Emergency latitude")
    longitude: float = Field(..., description="Emergency longitude")
    alpha_emergency: float = Field(1.5, description="Emergency priority multiplier, > 0")

    @field_validator("latitude")
    @classmethod
    def validate_lat(cls, v: float) -> float:
        if not (-90.0 <= v <= 90.0):
            raise ValueError("latitude must be between -90 and 90")
        return v

    @field_validator("longitude")
    @classmethod
    def validate_lon(cls, v: float) -> float:
        if not (-180.0 <= v <= 180.0):
            raise ValueError("longitude must be between -180 and 180")
        return v

    @field_validator("alpha_emergency")
    @classmethod
    def validate_alpha(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("alpha_emergency must be greater than 0")
        return v


class EmergencyResponse(BaseModel):
    ambulance: AmbulanceState
    travel_time_seconds: float
    distance_meters: float
    patient_latitude: float
    patient_longitude: float


class FleetSummary(BaseModel):
    total: int
    roaming: int
    standby: int
    available: int
    dispatched: int
    with_patient: int


class SimulationStepRequest(BaseModel):
    seconds: float = 1.0


class CongestedSegment(BaseModel):
    edge_id: str
    level: str  # "HEAVY" (red) or "MODERATE" (yellow)
    speed_kmh: float
    normal_speed_kmh: float
    congestion_ratio: float
    geometry: List[List[float]]  # [[lon, lat], ...]


class TrafficCongestionResponse(BaseModel):
    total_congested_segments: int
    heavy_count: int
    moderate_count: int
    source: str
    segments: List[CongestedSegment]