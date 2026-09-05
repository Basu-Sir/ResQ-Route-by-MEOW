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


def test_congested_shorter_route_loses_to_less_congested_longer_route(graph_data):
    # Under static conditions:
    # Path 1: A -> B -> C: length 10m + 10m = 20m, speed 10 m/s -> travel time = 2.0s
    # Path 2: A -> C (direct): length 30m, speed 10 m/s -> travel time = 3.0s
    # When B_C is congested (speed = 0.5 m/s):
    # Path 1 travel time becomes 1.0s + 20.0s = 21.0s.
    # Path 2 travel time is 3.0s, so the longer 30m route wins!
    hospitals = [Hospital(id="H_C", name="Hospital C", latitude=0, longitude=0, sumo_node_id="C", icu_beds=1)]
    redis_speeds = {"B_C": 0.5}
    result = find_route_to_nearest_hospital(graph_data, "A", hospitals, redis_speeds, alpha_emergency=1.0)
    assert result.edge_ids == ["A_C_DIRECT"]
    assert result.distance_meters == 30.0
    assert result.travel_time_seconds == pytest.approx(3.0)


def test_live_redis_speed_values_affect_route_selection(graph_data):
    # When all roads are free, the 20m path (A_B + B_C) is chosen
    hospitals = [Hospital(id="H_C", name="Hospital C", latitude=0, longitude=0, sumo_node_id="C", icu_beds=1)]
    free_result = find_route_to_nearest_hospital(graph_data, "A", hospitals, {}, alpha_emergency=1.0)
    assert free_result.edge_ids == ["A_B", "B_C"]

    # When live Redis reports congestion on A_B (0.5 m/s), A_C_DIRECT is chosen
    congested_result = find_route_to_nearest_hospital(graph_data, "A", hospitals, {"A_B": 0.5}, alpha_emergency=1.0)
    assert congested_result.edge_ids == ["A_C_DIRECT"]


def test_fallback_to_static_sumo_speed_when_redis_has_no_value(graph_data):
    # Empty redis_speeds dict falls back to static speeds on each edge
    hospitals = [Hospital(id="H_C", name="Hospital C", latitude=0, longitude=0, sumo_node_id="C", icu_beds=1)]
    result = find_route_to_nearest_hospital(graph_data, "A", hospitals, redis_speeds={}, alpha_emergency=1.0)
    assert result.edge_ids == ["A_B", "B_C"]
    assert result.travel_time_seconds == pytest.approx(2.0)  # (10/10) + (10/10) = 2.0s


def test_zero_and_invalid_speed_handling():
    # Negative speeds clamped to MIN_EFFECTIVE_SPEED
    assert compute_effective_speed(-10.0) == 0.5
    # Zero speed clamped
    assert compute_effective_speed(0.0) == 0.5
    # NaN and inf clamped
    assert compute_effective_speed(float("nan")) == 0.5
    assert compute_effective_speed(float("inf")) == 0.5
    # Non-numeric string clamped
    assert compute_effective_speed("bad_speed") == 0.5
    # None clamped
    assert compute_effective_speed(None) == 0.5

    # resolve_edge_speed falls back to static when redis value is None or invalid
    assert resolve_edge_speed("E1", static_speed=13.9, redis_speeds={"E1": None}) == 13.9
    assert resolve_edge_speed("E1", static_speed=13.9, redis_speeds={"E1": "invalid"}) == 13.9
    # resolve_edge_speed clamps zero in redis to MIN_EFFECTIVE_SPEED
    assert resolve_edge_speed("E1", static_speed=13.9, redis_speeds={"E1": 0.0}) == 0.5


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