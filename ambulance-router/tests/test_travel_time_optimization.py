"""
Unit tests for travel time optimization and live distance/ETA calculation.
"""
import pytest
from backend.fleet import AmbulanceFleet, compute_effective_ambulance_speed
from backend.hospitals import Hospital
from backend.models import AmbulanceDestination


def test_clear_yellow_red_speed_and_eta_relationship():
    """
    Verify:
    1. CLEAR > YELLOW > RED in effective speed.
    2. Therefore clear roads always produce a shorter ETA than yellow,
       and yellow always produces a shorter ETA than red.
    """
    dist = 5000.0  # 5 km

    # 1. Clear road (typical unhindered speed ~14 m/s)
    speed_clear, cond_clear = compute_effective_ambulance_speed(dist, dist / 14.0, alpha_emergency=1.5)
    eta_clear = dist / speed_clear
    assert cond_clear == "CLEAR"

    # 2. Yellow road (moderate congestion ~5 m/s)
    speed_yellow, cond_yellow = compute_effective_ambulance_speed(dist, dist / 5.0, alpha_emergency=1.5)
    eta_yellow = dist / speed_yellow
    assert cond_yellow == "YELLOW"

    # 3. Red road (heavy congestion ~1.8 m/s)
    speed_red, cond_red = compute_effective_ambulance_speed(dist, dist / 1.8, alpha_emergency=1.5)
    eta_red = dist / speed_red
    assert cond_red == "RED"

    # Strict ordering: CLEAR > YELLOW > RED
    assert speed_clear > speed_yellow > speed_red
    # Strict ETA: ETA(CLEAR) < ETA(YELLOW) < ETA(RED)
    assert eta_clear < eta_yellow < eta_red


def test_live_remaining_distance_and_eta_decrease_as_ambulance_moves(graph_data):
    """
    Verify that:
    1. Movement speed and displayed ETA use the same timing logic.
    2. Remaining distance decreases as ambulance moves.
    3. ETA decreases as ambulance moves.
    """
    hospitals = [
        Hospital(id="H1", name="Hospital 1", latitude=0.0, longitude=0.0, sumo_node_id="A", icu_beds=5),
        Hospital(id="H2", name="Hospital 2", latitude=0.0, longitude=10.0, sumo_node_id="B", icu_beds=3),
        Hospital(id="H3", name="Hospital 3", latitude=0.0, longitude=20.0, sumo_node_id="C", icu_beds=2),
        Hospital(id="H4", name="Hospital 4", latitude=5.0, longitude=10.0, sumo_node_id="H", icu_beds=4),
    ]
    fleet = AmbulanceFleet(gd=graph_data, hospitals=hospitals)

    # Dispatch AMB-13 (standby ambulance at node A) to H3 (at node C)
    amb_model = fleet.dispatch("AMB-13", hospital_id="H3", has_patient=False, alpha_emergency=1.0)
    assert amb_model.status == "DISPATCHED"

    assert amb_model.remaining_distance_meters is not None
    assert amb_model.remaining_distance_meters > 0
    assert amb_model.eta_seconds is not None
    assert amb_model.eta_seconds > 0

    init_dist = amb_model.remaining_distance_meters
    init_eta = amb_model.eta_seconds

    # Advance simulation by 0.1s (FakeNet mock route is only 20 meters long)
    fleet.step(dt=0.1)
    updated_amb = fleet.get_by_id("AMB-13")

    # Remaining distance must strictly decrease
    assert updated_amb.remaining_distance_meters is not None
    assert updated_amb.remaining_distance_meters < init_dist
    # ETA must strictly decrease
    assert updated_amb.eta_seconds is not None
    assert updated_amb.eta_seconds < init_eta
    # Remaining distance decreased by speed * dt
    internal_amb = fleet.ambulances["AMB-13"]
    assert internal_amb.current_distance_m == pytest.approx(internal_amb.speed_mps * 0.1)




def test_roaming_ambulance_has_live_distance_and_eta(graph_data):
    """
    Verify that roaming ambulances show their current route distance and ETA.
    """
    hospitals = [
        Hospital(id="H1", name="Hospital 1", latitude=0.0, longitude=0.0, sumo_node_id="A", icu_beds=5),
        Hospital(id="H2", name="Hospital 2", latitude=0.0, longitude=10.0, sumo_node_id="B", icu_beds=3),
    ]
    fleet = AmbulanceFleet(gd=graph_data, hospitals=hospitals)

    roaming_amb = fleet.get_by_id("AMB-01")
    assert roaming_amb.is_roaming is True
    assert roaming_amb.remaining_distance_meters is not None
    assert roaming_amb.remaining_distance_meters > 0
    assert roaming_amb.eta_seconds is not None
    assert roaming_amb.eta_seconds > 0


def test_patient_to_hospital_speed_and_hierarchy(graph_data):
    """
    Verify that patient -> hospital movement uses the same speed scaling
    and strictly maintains CLEAR > YELLOW > RED.
    """
    dist = 4000.0
    spd_clear, cond_clear = compute_effective_ambulance_speed(
        dist, dist / 15.0, alpha_emergency=1.5
    )
    spd_yellow, cond_yellow = compute_effective_ambulance_speed(
        dist, dist / 5.0, alpha_emergency=1.5
    )
    spd_red, cond_red = compute_effective_ambulance_speed(
        dist, dist / 1.8, alpha_emergency=1.5
    )

    assert cond_clear == "CLEAR"
    assert cond_yellow == "YELLOW"
    assert cond_red == "RED"

    assert spd_clear > spd_yellow > spd_red
    # Check visible distinction between tiers
    assert spd_clear >= 2.0 * spd_yellow
    assert spd_yellow >= 2.0 * spd_red


def test_live_traffic_condition_updates_as_ambulance_enters_different_segments(graph_data):
    """
    Verify that traffic condition updates dynamically as ambulance moves
    through different road segments: CLEAR -> YELLOW -> RED -> CLEAR.
    """
    hosp = Hospital(id="H1", name="Hospital 1", latitude=0.0, longitude=30.0, sumo_node_id="C", icu_beds=2)
    # 3-segment route: A -> B (clear), B -> C (yellow), C -> D (red)
    live_traffic = {
        "A_B": 15.0,  # Clear
        "B_C": 5.0,   # Yellow
        "A_C_DIRECT": 1.5, # Red
    }
    fleet = AmbulanceFleet(
        gd=graph_data,
        hospitals=[hosp],
        traffic_speeds_fn=lambda: (live_traffic, "redis"),
    )

    amb = fleet.ambulances["AMB-13"]
    amb.latitude = 0.0
    amb.longitude = 0.0
    amb.current_node_id = "A"

    # Multi-edge route
    amb.status = "DISPATCHED"
    amb.target_type = "PATIENT"
    amb.route_edge_ids = ["A_B", "B_C", "A_C_DIRECT"]
    amb.edge_cumulative_distances = [0.0, 100.0, 200.0, 300.0]
    amb.total_distance_m = 300.0
    amb.current_distance_m = 0.0
    amb.alpha_emergency = 1.5
    amb.full_route_geometry = [[0.0, 0.0], [0.0, 10.0], [0.0, 20.0], [0.0, 30.0]]
    amb.cumulative_distances = [0.0, 100.0, 200.0, 300.0]
    amb.speed_mps = 50.0

    # Step into segment 1 (A_B: CLEAR) at distance 50m
    amb.current_distance_m = 50.0
    fleet.step(dt=0.1)
    assert amb.current_edge_id == "A_B"
    assert amb.traffic_condition == "CLEAR"
    clear_spd = amb.speed_mps
    clear_eta = amb.eta_seconds

    # Move into segment 2 (B_C: YELLOW) at distance 150m
    amb.current_distance_m = 150.0
    fleet.step(dt=0.1)
    assert amb.current_edge_id == "B_C"
    assert amb.traffic_condition == "YELLOW"
    yellow_spd = amb.speed_mps
    yellow_eta = amb.eta_seconds
    assert clear_spd > yellow_spd

    # Move into segment 3 (A_C_DIRECT: RED) at distance 250m
    amb.current_distance_m = 250.0
    fleet.step(dt=0.1)
    assert amb.current_edge_id == "A_C_DIRECT"
    assert amb.traffic_condition == "RED"
    red_spd = amb.speed_mps
    assert yellow_spd > red_spd

    # Back to clear segment if live traffic changes or enters clear edge
    live_traffic["A_C_DIRECT"] = 14.0
    fleet.step(dt=0.1)
    assert amb.traffic_condition == "CLEAR"
    assert amb.speed_mps > red_spd

