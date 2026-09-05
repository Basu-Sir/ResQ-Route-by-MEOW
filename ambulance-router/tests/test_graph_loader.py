from backend.graph_loader import edge_ids_to_lonlat_geometry, get_nearest_node


def test_graph_has_expected_nodes(graph_data):
    assert graph_data.num_nodes == 4
    assert set(graph_data.node_index.keys()) == {"A", "B", "C", "H"}


def test_internal_edges_are_skipped(graph_data):
    assert ":junction_internal" not in graph_data.edge_static


def test_regular_edges_are_loaded(graph_data):
    assert graph_data.num_edges == 4
    assert "A_B" in graph_data.edge_static
    assert graph_data.edge_static["A_B"].length == 10.0
    assert graph_data.edge_static["A_B"].max_speed == 10.0


def test_edge_lookup_maps_node_pairs_to_edge_ids(graph_data):
    u = graph_data.node_index["A"]
    v = graph_data.node_index["B"]
    assert graph_data.edge_lookup[(u, v)] == "A_B"


def test_get_nearest_node_returns_closest_by_coordinates(graph_data):
    # (9, 1) is closest to node B at (10, 0)
    nearest = get_nearest_node(graph_data, x=9, y=1)
    assert nearest == "B"


def test_edge_ids_to_lonlat_geometry_returns_points(graph_data):
    coords = edge_ids_to_lonlat_geometry(graph_data, ["A_B", "B_H"])
    assert coords == [[0.0, 0.0], [10.0, 0.0], [10.0, 5.0]]


def test_edge_ids_to_lonlat_geometry_handles_empty_or_unknown(graph_data):
    assert edge_ids_to_lonlat_geometry(graph_data, []) == []
    assert edge_ids_to_lonlat_geometry(graph_data, ["UNKNOWN_EDGE"]) == []
