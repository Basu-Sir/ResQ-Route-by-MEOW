"""
Loads hospital data from data/hospitals.json and filters candidates
with available ICU capacity and emergency doctors.
Simulates dynamic hospital availability independently for ICU beds and emergency doctors.
"""
import json
import logging
import random
import threading
import time
from dataclasses import dataclass
from typing import List, Optional

from backend import config

logger = logging.getLogger("hospitals")


@dataclass
class Hospital:
    id: str
    name: str
    latitude: float
    longitude: float
    sumo_node_id: str
    icu_beds: int
    emergency_doctors: int = 2
    max_icu_beds: int = 10
    max_emergency_doctors: int = 5


_SIMULATION_THREAD: Optional[threading.Thread] = None
_RUNNING: bool = False
_HOSPITALS_REF: List[Hospital] = []
_SIM_LOCK = threading.Lock()
_MIN_INTERVAL: float = 4.0
_MAX_INTERVAL: float = 8.0


def _simulate_single_hospital(h: Hospital) -> None:
    """
    Simulate availability change for one hospital:
    - Randomly choose either ICU beds or Emergency doctors (never both in the same step).
    - If a resource is currently 0, allow it to recover to a reasonable non-zero value.
    - If neither resource is 0, the chosen resource can either become 0 or fluctuate within bounds.
    - If one resource becomes 0, the other resource strictly remains unchanged.
    - Both resources never become 0 at the same time.
    """
    # 1. Recovery case: if one resource is currently 0, it recovers to a non-zero value
    if h.icu_beds == 0:
        # Recover ICU beds to reasonable non-zero value; doctors remain untouched
        h.icu_beds = random.randint(1, max(2, min(h.max_icu_beds, 6)))
        return
    elif h.emergency_doctors == 0:
        # Recover emergency doctors to reasonable non-zero value; ICU beds remain untouched
        h.emergency_doctors = random.randint(1, max(2, min(h.max_emergency_doctors, 4)))
        return

    # 2. Normal fluctuation / zero-availability event:
    # Randomly choose EITHER ICU beds OR Emergency doctors
    chosen_resource = random.choice(["icu_beds", "emergency_doctors"])

    if chosen_resource == "icu_beds":
        # Chance to drop to exactly 0, otherwise fluctuate within sensible bounds
        if random.random() < 0.30:
            h.icu_beds = 0
        else:
            delta = random.choice([-2, -1, 1, 2])
            h.icu_beds = max(1, min(h.max_icu_beds, h.icu_beds + delta))
        # emergency_doctors strictly unchanged
    else:
        # Chance to drop to exactly 0, otherwise fluctuate within sensible bounds
        if random.random() < 0.30:
            h.emergency_doctors = 0
        else:
            delta = random.choice([-2, -1, 1, 2])
            h.emergency_doctors = max(1, min(h.max_emergency_doctors, h.emergency_doctors + delta))
        # icu_beds strictly unchanged


def simulate_hospital_step(hospitals: List[Hospital]) -> None:
    """
    Simulate one step of dynamic hospital availability across the given hospitals.
    Randomly selects only SOME hospitals and independently modifies either ICU beds or Emergency doctors.
    """
    if not hospitals:
        return

    with _SIM_LOCK:
        total = len(hospitals)
        if total <= 5:
            subset_size = random.randint(1, max(1, total - 1))
        else:
            subset_size = random.randint(2, min(15, max(3, total // 30)))

        selected_hospitals = random.sample(hospitals, subset_size)
        for h in selected_hospitals:
            _simulate_single_hospital(h)


def _simulation_worker() -> None:
    while _RUNNING:
        sleep_time = random.uniform(_MIN_INTERVAL, _MAX_INTERVAL)
        time.sleep(sleep_time)
        if not _RUNNING:
            break
        try:
            with _SIM_LOCK:
                targets = list(_HOSPITALS_REF)
            if targets:
                simulate_hospital_step(targets)
        except Exception as exc:
            logger.debug("Error in hospital availability simulation worker: %s", exc)


def start_hospital_simulation(
    hospitals: List[Hospital],
    min_interval: float = 4.0,
    max_interval: float = 8.0,
) -> None:
    """Start dynamic hospital availability simulation background daemon."""
    global _SIMULATION_THREAD, _RUNNING, _HOSPITALS_REF, _MIN_INTERVAL, _MAX_INTERVAL
    _MIN_INTERVAL = min_interval
    _MAX_INTERVAL = max_interval
    with _SIM_LOCK:
        _HOSPITALS_REF = hospitals
    if _SIMULATION_THREAD is not None and _SIMULATION_THREAD.is_alive():
        return
    _RUNNING = True
    _SIMULATION_THREAD = threading.Thread(
        target=_simulation_worker,
        daemon=True,
        name="HospitalAvailabilityDaemon",
    )
    _SIMULATION_THREAD.start()
    logger.info("Hospital availability background daemon started")


def stop_hospital_simulation() -> None:
    """Stop dynamic hospital availability simulation background daemon."""
    global _RUNNING
    _RUNNING = False


def load_hospitals(
    path: str = None,
    auto_start_simulation: bool = True,
) -> List[Hospital]:
    path = path or config.HOSPITALS_FILE
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    hospitals = []
    for item in raw:
        icu = int(item.get("icu_beds", 3))
        docs = int(item.get("emergency_doctors", 2))
        max_icu = max(icu, 10)
        max_docs = max(docs, 5)
        hospitals.append(
            Hospital(
                id=str(item["id"]),
                name=str(item["name"]),
                latitude=float(item["latitude"]),
                longitude=float(item["longitude"]),
                sumo_node_id=str(item["sumo_node_id"]),
                icu_beds=icu,
                emergency_doctors=docs,
                max_icu_beds=max_icu,
                max_emergency_doctors=max_docs,
            )
        )

    if auto_start_simulation:
        start_hospital_simulation(hospitals)

    return hospitals


def filter_available(hospitals: List[Hospital]) -> List[Hospital]:
    return [h for h in hospitals if h.icu_beds > 0 and h.emergency_doctors > 0]