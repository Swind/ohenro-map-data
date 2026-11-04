import math
import unittest

from datasets.sekaiisan_henro import planner, projection

# Node coordinates (lon, lat) near the projection centre (Shikoku).
COORDS = {
    "A": (133.0, 33.0),
    "B": (133.001, 33.0),
    "C": (133.002, 33.0),
    "D": (133.0005, 33.0007),
    "E": (133.0005, 33.0),
    "F": (133.0015, 33.0),
}


def _len_m(a, b):
    ax, ay = projection.project_point(*COORDS[a])
    bx, by = projection.project_point(*COORDS[b])
    return math.hypot(bx - ax, by - ay)


def _te(eid, a, b):
    length = _len_m(a, b)
    return {"id": eid, "from": a, "to": b, "length_m": length,
            "coordinates": [list(COORDS[a]), list(COORDS[b])],
            "source_edge_id": "SHE_" + eid, "provenance": {}}


def _graph(edges, joins=()):
    node_ids = set()
    for edge in edges:
        node_ids.add(edge["from"])
        node_ids.add(edge["to"])
    for join in joins:
        node_ids.add(join["from"])
        node_ids.add(join["to"])
    nodes = [{"id": nid, "lon": COORDS[nid][0], "lat": COORDS[nid][1],
              "coordinates": list(COORDS[nid]), "kinds": [], "source_refs": []}
             for nid in sorted(node_ids)]
    temple_anchors = [{
        "temple_number": number, "temple_id": "TEMPLE_%d" % number,
        "confidence": "review_required", "status": "review_required",
        "usable_for_routing": False, "distance_m": 200.0,
    } for number in range(1, 89)]
    return {
        "schema_version": 1, "kind": "anchored_route_graph",
        "dataset_id": "88sekaiisan-henro", "snapshot_sha256": "aa" * 32,
        "projection": {"kind": "equirectangular", "R": 6371008.8,
                       "lon0": 133.75, "lat0": 33.65},
        "limitation": "test fixture", "note": "test fixture",
        "nodes": nodes, "synthetic_nodes": [], "anchor_nodes": [],
        "edges": [], "synthetic_joins": list(joins),
        "temple_anchors": temple_anchors, "traversal_edges": edges,
        "components": [], "accounting": {},
    }


class TestExportPlanGraph(unittest.TestCase):
    def test_shared_endpoint_contacts_emit_one_bridge(self):
        # Two edges in one component both touch an endpoint of another.
        edges = [
            {"id": "a", "from": "A", "to": "B", "coordinates": [[133, 33], [133.001, 33]]},
            {"id": "b", "from": "A", "to": "C", "coordinates": [[133, 33], [133, 33.001]]},
            {"id": "c", "from": "D", "to": "E", "coordinates": [[133, 33], [132.999, 32.999]]},
        ]
        _, joins, _ = planner._bridge_overlaps(edges, 5, lambda i, j: i < 2 and j < 2)
        self.assertEqual(len(joins), 1)
        self.assertEqual({joins[0]["from"], joins[0]["to"]}, {"A", "D"})
        self.assertEqual(joins[0]["distance_m"], 0)

    def test_compact_graph_preserves_routing_topology(self):
        graph = _graph(
            [_te("e1", "A", "B"), _te("e2", "B", "C")],
            joins=[{"id": "SHJ_1", "from": "A", "to": "D",
                    "distance_m": 5.0, "coordinates": [list(COORDS["A"]), list(COORDS["D"])]}],
        )
        compact = planner.build_plan_graph(graph)
        self.assertEqual(compact["kind"], "plan_graph")
        self.assertEqual([e["id"] for e in compact["traversal_edges"]], ["e1", "e2"])
        self.assertEqual([e["id"] for e in compact["synthetic_joins"]], ["SHJ_1"])
        node_ids = {n["id"] for n in compact["nodes"]}
        self.assertEqual(node_ids, {"A", "B", "C", "D"})
        for node in compact["nodes"]:
            self.assertIn("lon", node)
            self.assertIn("lat", node)
        for edge in compact["traversal_edges"]:
            self.assertNotIn("coordinates", edge)
            self.assertEqual(edge["from"] in node_ids, True)
        for join in compact["synthetic_joins"]:
            self.assertNotIn("coordinates", join)
        self.assertEqual(set(compact["edge_geometry"]),
                         {"e1", "e2", "SHJ_1"})
        self.assertEqual(len(compact["edge_geometry"]["e1"]), 2)
        self.assertEqual(len(compact["edge_geometry"]["SHJ_1"]), 2)
        self.assertEqual(compact["schema_version"], 2)

    def test_bridge_connects_overlapping_disconnected_lines(self):
        # Two disconnected edges whose interiors pass within ~3m of each other
        # get bridged into one component when bridge_m is large enough.
        e1 = _te("e1", "A", "C")  # A(133.0,33.0) -> C(133.002,33.0)
        # e2 runs 3m south of the A-C line, crossing it inside.
        e2_coords = [
            [133.0005, 33.0 - 0.00003], [133.0015, 33.0 - 0.00003],
        ]
        ax, _ = projection.project_point(e2_coords[0][0], e2_coords[0][1])
        bx, _ = projection.project_point(e2_coords[1][0], e2_coords[1][1])
        e2 = {
            "id": "e2", "from": "E", "to": "F",
            "length_m": bx - ax,
            "coordinates": e2_coords,
            "source_edge_id": "SHE_e2", "provenance": {},
        }
        graph = _graph([e1, e2])

        merged = planner.build_plan_graph(graph, bridge_m=5.0)
        parent = {n["id"]: n["id"] for n in merged["nodes"]}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x, y):
            rx, ry = find(x), find(y)
            if rx != ry:
                parent[ry] = rx

        for edge in merged["traversal_edges"]:
            union(edge["from"], edge["to"])
        for join in merged["synthetic_joins"]:
            union(join["from"], join["to"])
        roots = {find(n["id"]) for n in merged["nodes"]}
        self.assertEqual(len(roots), 1, "overlapping lines should be bridged")

        # Without bridging they stay disconnected.
        plain = planner.build_plan_graph(graph, bridge_m=0.0)
        parent2 = {n["id"]: n["id"] for n in plain["nodes"]}

        def find2(x):
            while parent2[x] != x:
                parent2[x] = parent2[parent2[x]]
                x = parent2[x]
            return x

        def union2(x, y):
            rx, ry = find2(x), find2(y)
            if rx != ry:
                parent2[ry] = rx

        for edge in plain["traversal_edges"]:
            union2(edge["from"], edge["to"])
        for join in plain["synthetic_joins"]:
            union2(join["from"], join["to"])
        roots2 = {find2(n["id"]) for n in plain["nodes"]}
        self.assertEqual(len(roots2), 2, "without bridging they stay separate")


if __name__ == "__main__":
    unittest.main()
