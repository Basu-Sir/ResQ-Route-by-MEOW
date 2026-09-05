"""
Minimal fakes that mimic the sumolib.net.Net / Node / Edge interface used
by backend/graph_loader.py, so graph-loading logic can be unit-tested
without parsing a real .net.xml file or requiring SUMO to be installed.
"""


class FakeNode:
    def __init__(self, node_id, x, y):
        self._id = node_id
        self._coord = (x, y)

    def getID(self):
        return self._id

    def getCoord(self):
        return self._coord


class FakeEdge:
    def __init__(self, edge_id, from_node, to_node, length, speed):
        self._id = edge_id
        self._from = from_node
        self._to = to_node
        self._length = length
        self._speed = speed

    def getID(self):
        return self._id

    def getFromNode(self):
        return self._from

    def getToNode(self):
        return self._to

    def getLength(self):
        return self._length

    def getSpeed(self):
        return self._speed

    def getShape(self):
        return [self._from.getCoord(), self._to.getCoord()]


class FakeNet:
    """
    A 4-node diamond network:
        A --10m/10mps--> B --15m/10mps--> C
        A --30m/10mps------------------> C   (slower/longer detour)
    plus a hospital branch B -> H
    """

    def __init__(self):
        self.node_a = FakeNode("A", 0, 0)
        self.node_b = FakeNode("B", 10, 0)
        self.node_c = FakeNode("C", 20, 0)
        self.node_h = FakeNode("H", 10, 5)

        self._nodes = [self.node_a, self.node_b, self.node_c, self.node_h]
        self._edges = [
            FakeEdge("A_B", self.node_a, self.node_b, length=10.0, speed=10.0),
            FakeEdge("B_C", self.node_b, self.node_c, length=10.0, speed=10.0),
            FakeEdge("A_C_DIRECT", self.node_a, self.node_c, length=30.0, speed=10.0),
            FakeEdge("B_H", self.node_b, self.node_h, length=5.0, speed=10.0),
            FakeEdge(":junction_internal", self.node_b, self.node_b, length=1.0, speed=5.0),
        ]

    def getNodes(self):
        return self._nodes

    def getEdges(self):
        return self._edges

    def getEdge(self, edge_id):
        for edge in self._edges:
            if edge.getID() == edge_id:
                return edge
        raise KeyError(edge_id)

    def convertLonLat2XY(self, lon, lat):
        # trivial deterministic mapping for tests: treat lon/lat as x/y directly
        return lon, lat

    def convertXY2LonLat(self, x, y):
        # trivial deterministic mapping for tests: treat x/y as lon/lat directly
        return x, y