import pytest
from fastapi.testclient import TestClient

from backend import main as backend_main
from backend.hospitals import Hospital


@pytest.fixture
def client(graph_data, monkeypatch):
    # Bypass real file loading in the startup event: inject the test graph
    # and hospitals directly instead of parsing city.net.xml / hospitals.json.
    monkeypatch.setattr(backend_main, "load_graph", lambda net_file: graph_data)
    monkeypatch.setattr(
        backend_main,
        "load_hospitals",
        lambda path: [
            Hospital(id="H1", name="Test Hospital", latitude=10.0, longitude=10.0,
                      sumo_node_id="H", icu_beds=3),
            Hospital(id="H2", name="Full Hospital", latitude=20.0, longitude=20.0,
                      sumo_node_id="C", icu_beds=0),
        ],
    )
    monkeypatch.setattr(backend_main, "get_traffic_speeds", lambda: ({}, "static"))

    with TestClient(backend_main.app) as c:
        yield c


def test_health_endpoint(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["graph_loaded"] is True
    assert body["graph_nodes"] == 4


def test_route_endpoint_happy_path(client):
    resp = client.post("/route", json={"latitude": 0.0, "longitude": 0.0, "alpha_emergency": 1.0})
    assert resp.status_code == 200
    body = resp.json()
    assert body["hospital"]["id"] == "H1"
    assert body["hospital"]["icu_beds"] == 3
    assert body["traffic_source"] == "static"
    assert body["route_edge_ids"] == ["A_B", "B_H"]
    assert body["route_geometry"] == [[0.0, 0.0], [10.0, 0.0], [10.0, 5.0]]


def test_route_endpoint_rejects_invalid_latitude(client):
    resp = client.post("/route", json={"latitude": 999.0, "longitude": 0.0})
    assert resp.status_code == 422


def test_route_endpoint_rejects_invalid_alpha(client):
    resp = client.post("/route", json={"latitude": 0.0, "longitude": 0.0, "alpha_emergency": 0})
    assert resp.status_code == 422


def test_route_endpoint_full_hospitals_are_excluded(client, monkeypatch):
    # Only the zero-ICU hospital exists -> 404
    monkeypatch.setattr(
        backend_main,
        "load_hospitals",
        lambda path: [Hospital(id="H2", name="Full", latitude=20.0, longitude=20.0,
                                 sumo_node_id="C", icu_beds=0)],
    )
    with TestClient(backend_main.app) as c:
        resp = c.post("/route", json={"latitude": 0.0, "longitude": 0.0})
        assert resp.status_code == 404