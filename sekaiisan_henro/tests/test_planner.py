import math
import unittest

from sekaiisan_henro import planner, projection

# Node coordinates (lon, lat) near the projection centre (Shikoku).
COORDS = {
    "A": (133.0, 33.0),
    "B": (133.001, 33.0),
    "C": (133.002, 33.0),
    "D": (133.0005, 33.0007),
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
            self.assertEqual(len(edge["coordinates"]), 2)
        for join in compact["synthetic_joins"]:
            self.assertEqual(len(join["coordinates"]), 2)


if __name__ == "__main__":
    unittest.main()
