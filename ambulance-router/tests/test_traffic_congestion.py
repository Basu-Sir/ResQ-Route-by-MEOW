"""
Unit tests for traffic congestion generation, Redis storage, and API response.
"""
from fastapi.testclient import TestClient
from backend.main import app
from backend.models import TrafficCongestionResponse
from backend import redis_client


def test_traffic_congestion_endpoint():
    """Verify GET /traffic/congestion returns valid traffic data with segments and geometries."""
    with TestClient(app) as client:
        res = client.get("/traffic/congestion")
        assert res.status_code == 200
        data = res.json()
        assert "total_congested_segments" in data
        assert "heavy_count" in data
        assert "moderate_count" in data
        assert "source" in data
        assert isinstance(data["segments"], list)
        
        # Verify segment structure if any are present
        if data["segments"]:
            first = data["segments"][0]
            assert "edge_id" in first
            assert first["level"] in ("HEAVY", "MODERATE")
            assert "speed_kmh" in first
            assert "normal_speed_kmh" in first
            assert "geometry" in first
            assert len(first["geometry"]) >= 2
            # Geometry format is [lon, lat]
            assert len(first["geometry"][0]) == 2


def test_traffic_seed_endpoint():
    """Verify POST /traffic/seed forces re-seeding to Redis and returns refreshed segments."""
    with TestClient(app) as client:
        res = client.post("/traffic/seed")
        assert res.status_code == 200
        data = res.json()
        assert data["total_congested_segments"] > 0
        assert data["source"] in ("redis", "fallback")
        assert data["heavy_count"] > 0
        assert data["moderate_count"] > 0
