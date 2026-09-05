"""
Loads hospital data from data/hospitals.json and filters candidates
with available ICU capacity.
"""
import json
from dataclasses import dataclass
from typing import List

from backend import config


@dataclass
class Hospital:
    id: str
    name: str
    latitude: float
    longitude: float
    sumo_node_id: str
    icu_beds: int


def load_hospitals(path: str = None) -> List[Hospital]:
    path = path or config.HOSPITALS_FILE
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    hospitals = []
    for item in raw:
        hospitals.append(
            Hospital(
                id=str(item["id"]),
                name=str(item["name"]),
                latitude=float(item["latitude"]),
                longitude=float(item["longitude"]),
                sumo_node_id=str(item["sumo_node_id"]),
                icu_beds=int(item["icu_beds"]),
            )
        )
    return hospitals


def filter_available(hospitals: List[Hospital]) -> List[Hospital]:
    return [h for h in hospitals if h.icu_beds > 0]