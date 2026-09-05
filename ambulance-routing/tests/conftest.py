import json
import os

import pytest

from backend.graph_loader import build_graph_from_net
from tests.fake_net import FakeNet


@pytest.fixture
def fake_net():
    return FakeNet()


@pytest.fixture
def graph_data(fake_net):
    return build_graph_from_net(fake_net)


@pytest.fixture
def hospitals_file(tmp_path):
    data = [
        {"id": "H1", "name": "Test Hospital", "latitude": 10.0, "longitude": 10.0,
         "sumo_node_id": "H", "icu_beds": 3},
        {"id": "H2", "name": "Full Hospital", "latitude": 20.0, "longitude": 20.0,
         "sumo_node_id": "C", "icu_beds": 0},
    ]
    path = tmp_path / "hospitals.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)