import pytest

from backend.hospitals import Hospital
from backend.routing import (
    NoAvailableHospitalError,
    NoRouteFoundError,
    compute_edge_weight,
    compute_effective_speed,
    find_route_to_nearest_hospital,
    resolve_edge_speed,
)


def test_effective_speed_floor():
    assert compute_effective_speed(0.0) == 0.5
    assert compute_effective_speed(0.2) == 0.5
    assert compute_effective_speed(5.0) == 5.0


def test_zero_speed_edge_does_not_explode_weight():
    weight = compute_edge_weight(length=100.0, speed=0.0, alpha_emergency=1.0)
    assert weight == 100.0 / 0.5  # uses the 0.5 floor, not division by zero


def test_weight_scales_inversely_with_alpha():
    w_default = compute_edge_weight(length=100.0, speed=10.0, alpha_emergency=1.0)
    w_boosted = compute_edge_weight(length=100.0, speed=10.0, alpha_emergency=2.0)
    assert w_boosted == pytest.approx(w_default / 2.0)


def test_resolve_edge_speed_prefers_redis_then_static():
    assert resolve_edge_speed("E1", static_speed=13.9, redis_speeds={"E1": 5.0}) == 5.0
    assert resolve_edge_speed("E1", static_speed=13.9, redis_speeds={}) == 13.9


def test_routing_prefers_shorter_faster_path_over_direct_edge(graph_data):
    # A_B + B_C (10+10=20m) should beat A_C_DIRECT (30m) at equal speed
    hospitals = [Hospital(id="H1", name="H", latitude=0, longitude=0,
                           sumo_node_id="C", icu_beds=1)]
    result = find_route_to_nearest_hospital(graph_data, "A", hospitals, {}, alpha_emergency=1.0)
    assert result.edge_ids == ["A_B", "B_C"]
    assert result.distance_meters == 20.0


def test_multi_target_picks_nearest_of_several_hospitals(graph_data):
    hospitals = [
        Hospital(id="H1", name="Far", latitude=0, longitude=0, sumo_node_id="C", icu_beds=2),
        Hospital(id="H2", name="Near", latitude=0, longitude=0, sumo_node_id="H", icu_beds=2),
    ]
    result = find_route_to_nearest_hospital(graph_data, "A", hospitals, {}, alpha_emergency=1.0)
    assert result.hospital.id == "H2"
    assert result.edge_ids == ["A_B", "B_H"]


def test_live_redis_speed_changes_routing_decision(graph_data):
    # Make B_C artificially very slow via "redis" speeds so the direct edge wins
    hospitals = [Hospital(id="H1", name="H", latitude=0, longitude=0,
                           sumo_node_id="C", icu_beds=1)]
    redis_speeds = {"B_C": 0.5}  # near floor speed -> very high weight
    result = find_route_to_nearest_hospital(graph_data, "A", hospitals, redis_speeds, alpha_emergency=1.0)
    assert result.edge_ids == ["A_C_DIRECT"]


def test_no_hospital_with_valid_node_raises(graph_data):
    hospitals = [Hospital(id="H1", name="H", latitude=0, longitude=0,
                           sumo_node_id="NOT_A_NODE", icu_beds=1)]
    with pytest.raises(NoAvailableHospitalError):
        find_route_to_nearest_hospital(graph_data, "A", hospitals, {}, alpha_emergency=1.0)


def test_unreachable_source_raises(graph_data):
    hospitals = [Hospital(id="H1", name="H", latitude=0, longitude=0,
                           sumo_node_id="C", icu_beds=1)]
    with pytest.raises(NoRouteFoundError):
        find_route_to_nearest_hospital(graph_data, "NOT_A_NODE", hospitals, {}, alpha_emergency=1.0)