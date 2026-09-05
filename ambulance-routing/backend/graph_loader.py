"""
Parses a SUMO .net.xml file with sumolib and builds an in-memory
rustworkx.PyDiGraph, plus SUMO<->rustworkx index mappings.

The graph is loaded ONCE at FastAPI startup and reused for every request.
"""
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import rustworkx as rx

from backend import config

config.ensure_sumo_tools_on_path()
import sumolib  # noqa: E402  (import after sys.path fix-up)


@dataclass
class EdgeStatic:
    edge_id: str
    length: float
    max_speed: float
    from_node: str
    to_node: str


@dataclass
class GraphData:
    graph: rx.PyDiGraph
    node_index: Dict[str, int] = field(default_factory=dict)
    index_node: Dict[int, str] = field(default_factory=dict)
    node_coords: Dict[str, Tuple[float, float]] = field(default_factory=dict)
    edge_lookup: Dict[Tuple[int, int], str] = field(default_factory=dict)
    edge_static: Dict[str, EdgeStatic] = field(default_factory=dict)
    net: Optional[object] = None  # sumolib.net.Net, kept for coordinate conversion

    @property
    def num_nodes(self) -> int:
        return self.graph.num_nodes()

    @property
    def num_edges(self) -> int:
        return self.graph.num_edges()


def build_graph_from_net(net) -> GraphData:
    """
    Build a GraphData from an already-parsed sumolib Net-like object.
    Kept separate from load_graph() so tests can pass in fakes without
    touching disk.
    """
    graph = rx.PyDiGraph(multigraph=True)
    gd = GraphData(graph=graph, net=net)

    for node in net.getNodes():
        node_id = node.getID()
        idx = graph.add_node({"node_id": node_id})
        gd.node_index[node_id] = idx
        gd.index_node[idx] = node_id
        gd.node_coords[node_id] = tuple(node.getCoord())

    for edge in net.getEdges():
        edge_id = edge.getID()
        if edge_id.startswith(":"):
            # internal junction edge, not part of the routable graph
            continue

        from_id = edge.getFromNode().getID()
        to_id = edge.getToNode().getID()
        if from_id not in gd.node_index or to_id not in gd.node_index:
            continue

        u = gd.node_index[from_id]
        v = gd.node_index[to_id]

        length = float(edge.getLength())
        max_speed = float(edge.getSpeed())

        payload = {
            "edge_id": edge_id,
            "length": length,
            "max_speed": max_speed,
        }
        graph.add_edge(u, v, payload)

        gd.edge_static[edge_id] = EdgeStatic(
            edge_id=edge_id,
            length=length,
            max_speed=max_speed,
            from_node=from_id,
            to_node=to_id,
        )
        # first edge registered between (u, v) wins for path reconstruction
        gd.edge_lookup.setdefault((u, v), edge_id)

    return gd


def load_graph(net_file: str = None) -> GraphData:
    """Parse city.net.xml with sumolib and build the routable graph."""
    net_file = net_file or config.SUMO_NET_FILE
    net = sumolib.net.readNet(net_file)
    return build_graph_from_net(net)


def latlon_to_xy(gd: GraphData, latitude: float, longitude: float) -> Tuple[float, float]:
    """Convert latitude/longitude to SUMO x/y."""
    if gd.net is None:
        raise RuntimeError("GraphData has no associated sumolib net")

    try:
        x, y = gd.net.convertLonLat2XY(longitude, latitude)
        return x, y
    except Exception:
        # Dummy network has no geographic projection.
        # For dummy testing, coordinates are already x/y.
        return longitude, latitude

def get_nearest_node(gd: GraphData, x: float, y: float) -> str:
    """Brute-force nearest-node search by Euclidean distance in network coordinates."""
    if not gd.node_coords:
        raise RuntimeError("Graph has no nodes")

    best_node = None
    best_dist = math.inf
    for node_id, (nx_, ny_) in gd.node_coords.items():
        d = (nx_ - x) ** 2 + (ny_ - y) ** 2
        if d < best_dist:
            best_dist = d
            best_node = node_id
    return best_node


def nearest_node_from_latlon(gd: GraphData, latitude: float, longitude: float) -> str:
    x, y = latlon_to_xy(gd, latitude, longitude)
    return get_nearest_node(gd, x, y)


# ---------------------------------------------------------------------------
# NEW: route geometry for the frontend.
#
# The browser must never receive the full SUMO network. This converts only
# the edges of ONE already-computed route (typically tens to a few hundred
# edges) into a lightweight [lon, lat] polyline using the same sumolib Net
# object that's already resident in memory (gd.net). It does not touch
# routing, rustworkx, or the graph-building logic above in any way.
# ---------------------------------------------------------------------------
def edge_ids_to_lonlat_geometry(
    gd: GraphData, edge_ids: List[str]
) -> List[List[float]]:
    """
    Convert a list of SUMO edge IDs (as returned by the routing pipeline)
    into an ordered list of [longitude, latitude] points suitable for
    drawing a single polyline on a web map.

    Consecutive duplicate points (shared junctions between edges) are
    collapsed so the returned list stays compact.
    """
    if gd.net is None or not edge_ids:
        return []

    if not hasattr(gd.net, "getEdge"):
        return []

    coords: List[List[float]] = []
    for edge_id in edge_ids:
        try:
            edge = gd.net.getEdge(edge_id)
        except Exception:
            # Edge not found or net lookup issue -- skip rather than fail
            continue

        shape = getattr(edge, "getShape", lambda: [])()
        for pt in shape:
            try:
                x, y = pt[0], pt[1]
                if hasattr(gd.net, "convertXY2LonLat"):
                    lon, lat = gd.net.convertXY2LonLat(x, y)
                else:
                    lon, lat = x, y
                point = [round(float(lon), 6), round(float(lat), 6)]
                if coords and coords[-1] == point:
                    continue
                coords.append(point)
            except Exception:
                continue

    return coords