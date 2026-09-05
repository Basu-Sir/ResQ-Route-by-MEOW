import pytest

from backend.fleet import (
    AmbulanceFleet,
    AmbulanceHasPatientError,
    haversine_meters,
)
from backend.hospitals import Hospital


@pytest.fixture
def mock_fleet(graph_data):
    # Create 4 test hospitals located at nodes A, B, C, H
    hospitals = [
        Hospital(id="H1", name="Hospital 1", latitude=0.0, longitude=0.0, sumo_node_id="A", icu_beds=5),
        Hospital(id="H2", name="Hospital 2", latitude=0.0, longitude=10.0, sumo_node_id="B", icu_beds=3),
        Hospital(id="H3", name="Hospital 3", latitude=0.0, longitude=20.0, sumo_node_id="C", icu_beds=2),
        Hospital(id="H4", name="Hospital 4", latitude=5.0, longitude=10.0, sumo_node_id="H", icu_beds=4),
    ]
    fleet = AmbulanceFleet(gd=graph_data, hospitals=hospitals)
    return fleet


def test_haversine_meters_basic():
    # Same point should be 0 distance
    assert haversine_meters(72.8777, 19.0760, 72.8777, 19.0760) == pytest.approx(0.0)
    # Approx distance between two Mumbai points (approx 1.1 km for 0.01 deg lat)
    d = haversine_meters(72.8777, 19.0760, 72.8777, 19.0860)
    assert 1000 < d < 1200


def test_fleet_initialization_creates_30_ambulances(mock_fleet):
    assert len(mock_fleet.ambulances) == 30
    for i in range(1, 31):
        amb_id = f"AMB-{i:02d}"
        assert amb_id in mock_fleet.ambulances
        amb = mock_fleet.ambulances[amb_id]
        assert amb.latitude is not None
        assert amb.longitude is not None
        assert amb.status in ("AVAILABLE", "BUSY", "DISPATCHED")


def test_fleet_initial_state_breakdown(mock_fleet):
    available = [a for a in mock_fleet.ambulances.values() if a.status == "AVAILABLE"]
    roaming = [a for a in mock_fleet.ambulances.values() if a.is_roaming]
    standby = [a for a in mock_fleet.ambulances.values() if not a.is_roaming and a.status == "AVAILABLE"]

    # Exactly 10 roaming + 20 standby, all available without patients
    assert len(available) == 30
    assert len(roaming) == 10
    assert len(standby) == 20

    for a in mock_fleet.ambulances.values():
        assert a.has_patient is False
        assert a.status == "AVAILABLE"

    # Roaming ambulances have active routes
    for r in roaming:
        assert r.is_roaming is True
        assert len(r.full_route_geometry) >= 2

    # Standby ambulances are stationary
    for s in standby:
        assert s.is_roaming is False


def test_cannot_dispatch_ambulance_with_patient(mock_fleet):
    amb = mock_fleet.ambulances["AMB-01"]
    amb.has_patient = True
    amb.status = "BUSY"
    with pytest.raises(AmbulanceHasPatientError):
        mock_fleet.dispatch("AMB-01", hospital_id="H2")


def test_dispatch_available_ambulance_progresses_route(mock_fleet):
    # AMB-13 is a standby ambulance located at node A
    amb = mock_fleet.ambulances["AMB-13"]
    amb.is_roaming = False
    assert amb.status == "AVAILABLE"
    assert amb.has_patient is False

    dispatched = mock_fleet.dispatch("AMB-13", hospital_id="H3", has_patient=False, alpha_emergency=1.0)
    assert dispatched.status == "DISPATCHED"
    assert dispatched.has_patient is False
    assert dispatched.destination is not None
    assert dispatched.destination.hospital_id == "H3"
    assert dispatched.eta_seconds > 0
    assert len(dispatched.route_geometry) >= 2

    # Verify ambulance in fleet object is moving
    fleet_amb = mock_fleet.ambulances["AMB-13"]
    assert fleet_amb.total_distance_m > 0

    # Step simulation forward by 0.5 seconds
    mock_fleet.step(dt=0.5)
    # Position should change progressively
    assert fleet_amb.current_distance_m > 0
    assert fleet_amb.current_distance_m == pytest.approx(fleet_amb.speed_mps * 0.5)


def test_progressive_movement_no_teleportation(mock_fleet):
    amb = mock_fleet.ambulances["AMB-13"]
    amb.status = "AVAILABLE"
    amb.has_patient = False
    amb.is_roaming = False

    mock_fleet.dispatch("AMB-13", hospital_id="H3", alpha_emergency=1.0)
    fleet_amb = mock_fleet.ambulances["AMB-13"]

    pos_0 = (fleet_amb.latitude, fleet_amb.longitude)
    mock_fleet.step(dt=0.2)
    pos_1 = (fleet_amb.latitude, fleet_amb.longitude)
    mock_fleet.step(dt=0.2)
    pos_2 = (fleet_amb.latitude, fleet_amb.longitude)

    # Positions should progress smoothly
    assert pos_0 != pos_1
    assert pos_1 != pos_2


def test_multiple_ambulances_move_independently(mock_fleet):
    amb1 = mock_fleet.ambulances["AMB-13"]
    amb2 = mock_fleet.ambulances["AMB-17"]
    amb1.status = "AVAILABLE"
    amb1.has_patient = False
    amb1.is_roaming = False
    amb2.status = "AVAILABLE"
    amb2.has_patient = False
    amb2.is_roaming = False

    mock_fleet.dispatch("AMB-13", hospital_id="H3", alpha_emergency=1.0)
    mock_fleet.dispatch("AMB-17", hospital_id="H4", alpha_emergency=2.0)

    speed1 = mock_fleet.ambulances["AMB-13"].speed_mps
    speed2 = mock_fleet.ambulances["AMB-17"].speed_mps

    mock_fleet.step(dt=0.1)
    dist1 = mock_fleet.ambulances["AMB-13"].current_distance_m
    dist2 = mock_fleet.ambulances["AMB-17"].current_distance_m

    assert dist1 == pytest.approx(speed1 * 0.1)
    assert dist2 == pytest.approx(speed2 * 0.1)
    assert dist1 != dist2  # different speeds -> different distances



def test_emergency_request_and_patient_pickup(mock_fleet):
    # Patient location near node H (hospital H4 at lat=5.0, lon=10.0)
    resp = mock_fleet.request_ambulance(patient_lat=5.0, patient_lon=10.0, alpha_emergency=1.5)
    assert resp.ambulance.status == "DISPATCHED"
    assert resp.ambulance.has_patient is False
    assert resp.travel_time_seconds >= 0

    selected_id = resp.ambulance.ambulance_id
    fleet_amb = mock_fleet.ambulances[selected_id]
    assert fleet_amb.status == "DISPATCHED"
    assert fleet_amb.is_roaming is False  # Stopped roaming
    assert fleet_amb.target_type == "PATIENT"

    # Step simulation to simulate arriving at patient
    mock_fleet.step(dt=1000.0)

    # Patient Pickup must transition ambulance to BUSY with has_patient=True
    assert fleet_amb.status == "BUSY"
    assert fleet_amb.has_patient is True


def test_patient_transport_dropoff_resumes_normal_fleet_behavior(graph_data):
    hospital = Hospital(
        id="H4",
        name="Hospital 4",
        latitude=5.0,
        longitude=10.0,
        sumo_node_id="H",
        icu_beds=4,
    )
    fleet = AmbulanceFleet(gd=graph_data, hospitals=[hospital])
    amb = fleet.ambulances["AMB-01"]
    amb.latitude = 0.0
    amb.longitude = 0.0
    amb.current_node_id = "A"
    amb.is_roaming = True
    amb.original_roaming = True
    amb.status = "DISPATCHED"
    amb.target_type = "PATIENT"
    amb.full_route_geometry = [[0.0, 0.0]]
    amb.route_geometry = [[0.0, 0.0]]
    amb.cumulative_distances = [0.0]
    amb.total_distance_m = 0.0
    amb.current_distance_m = 0.0

    # Pickup immediately routes the same ambulance to the hospital.
    fleet.step(1.0)
    assert amb.status == "BUSY"
    assert amb.has_patient is True
    assert amb.target_type == "HOSPITAL"
    assert amb.destination is not None
    assert amb.destination.hospital_id == "H4"
    assert amb.total_distance_m > 0

    position_before_transport = (amb.latitude, amb.longitude)
    fleet.step(0.2)
    assert (amb.latitude, amb.longitude) != position_before_transport

    # Arrival drops the patient and assigns a fresh roaming route.
    fleet.step(100.0)
    assert amb.status == "AVAILABLE"
    assert amb.has_patient is False
    assert amb.target_type == "ROAMING"
    assert amb.is_roaming is True
    assert amb.destination is not None
    assert amb.destination.hospital_id != "H4"
    assert amb.total_distance_m > 0


def test_fleet_summary(mock_fleet):
    summary = mock_fleet.get_summary()
    assert summary.total == 30
    assert summary.roaming == 10
    assert summary.standby == 20
    assert summary.available == 30
    assert summary.dispatched == 0
    assert summary.with_patient == 0


def test_fleet_reset(mock_fleet):
    mock_fleet.step(dt=100.0)
    mock_fleet.reset()
    assert len(mock_fleet.ambulances) == 30
    available = [a for a in mock_fleet.ambulances.values() if a.status == "AVAILABLE"]
    assert len(available) == 30
    roaming = [a for a in mock_fleet.ambulances.values() if a.is_roaming]
    assert len(roaming) == 10

