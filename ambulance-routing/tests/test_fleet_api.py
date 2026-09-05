import pytest
from fastapi.testclient import TestClient

from backend import main as backend_main
from backend.hospitals import Hospital


@pytest.fixture
def client(graph_data, monkeypatch):
    monkeypatch.setattr(backend_main, "load_graph", lambda net_file: graph_data)
    monkeypatch.setattr(
        backend_main,
        "load_hospitals",
        lambda path: [
            Hospital(id="H1", name="Test Hospital", latitude=10.0, longitude=10.0,
                      sumo_node_id="H", icu_beds=3),
            Hospital(id="H2", name="Full Hospital", latitude=20.0, longitude=20.0,
                      sumo_node_id="C", icu_beds=0),
            Hospital(id="H3", name="Second Hospital", latitude=0.0, longitude=10.0,
                      sumo_node_id="B", icu_beds=2),
        ],
    )
    monkeypatch.setattr(backend_main, "get_traffic_speeds", lambda: ({}, "static"))

    with TestClient(backend_main.app) as c:
        yield c


def test_get_all_ambulances_endpoint(client):
    resp = client.get("/ambulances")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 30

    ids = [a["ambulance_id"] for a in data]
    assert "AMB-01" in ids
    assert "AMB-30" in ids

    # Check status distribution: 10 roaming, 20 standby, all 30 available
    available = [a for a in data if a["status"] == "AVAILABLE"]
    roaming = [a for a in data if a.get("is_roaming") is True]
    standby = [a for a in data if not a.get("is_roaming")]

    assert len(available) == 30
    assert len(roaming) == 10
    assert len(standby) == 20

    for a in data:
        assert a["has_patient"] is False


def test_get_single_ambulance_endpoint(client):
    resp = client.get("/ambulances/AMB-01")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ambulance_id"] == "AMB-01"
    assert "latitude" in data
    assert "longitude" in data
    assert "status" in data


def test_get_nonexistent_ambulance_endpoint(client):
    resp = client.get("/ambulances/AMB-999")
    assert resp.status_code == 404


def test_dispatch_ambulance_endpoint(client):
    resp = client.post(
        "/ambulances/AMB-13/dispatch",
        json={"hospital_id": "H3", "has_patient": False, "alpha_emergency": 1.5},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ambulance_id"] == "AMB-13"
    assert data["status"] == "DISPATCHED"
    assert data["destination"]["hospital_id"] == "H3"
    assert data["eta_seconds"] is not None


def test_dispatch_ambulance_with_patient_fails(client):
    # Mark AMB-13 as having a patient
    backend_main.app.state.fleet.ambulances["AMB-13"].has_patient = True
    backend_main.app.state.fleet.ambulances["AMB-13"].status = "BUSY"

    resp = client.post(
        "/ambulances/AMB-13/dispatch",
        json={"hospital_id": "H3"},
    )
    assert resp.status_code == 400
    assert "already carrying a patient" in resp.json()["detail"]



def test_emergency_request_endpoint(client):
    # Request ambulance for patient at lat=10.0, lon=10.0
    resp = client.post(
        "/ambulances/request",
        json={"latitude": 10.0, "longitude": 10.0, "alpha_emergency": 1.5},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "ambulance" in data
    assert data["ambulance"]["status"] == "DISPATCHED"
    assert data["ambulance"]["has_patient"] is False
    assert data["travel_time_seconds"] >= 0
    assert data["distance_meters"] >= 0
    assert data["patient_latitude"] == 10.0
    assert data["patient_longitude"] == 10.0


def test_fleet_summary_endpoint(client):
    # Reset first to clean state
    client.post("/ambulances/reset")
    resp = client.get("/ambulances/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 30
    assert data["roaming"] == 10
    assert data["standby"] == 20
    assert data["available"] == 30
    assert data["dispatched"] == 0
    assert data["with_patient"] == 0


def test_step_simulation_endpoint(client):
    resp = client.post("/ambulances/step", json={"seconds": 2.0})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 30


def test_reset_simulation_endpoint(client):
    resp = client.post("/ambulances/reset")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 30
    available = [a for a in data if a["status"] == "AVAILABLE"]
    assert len(available) == 30


def test_health_reports_ambulances(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ambulances_loaded"] == 30

