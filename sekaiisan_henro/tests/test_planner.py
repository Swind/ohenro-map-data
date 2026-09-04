import math
import unittest

from sekaiisan_henro import planner, projection

# Node coordinates (lon, lat) near the projection centre (Shikoku).
COORDS = {
    "A": (133.0, 33.0),
    "B": (133.001, 33.0),
    "C": (133.002, 33.0),
    "D": (133.0005, 33.0007),
    "E": (133.003, 33.0),
    "F": (133.004, 33.0),
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


class FakeSampler:
    """Deterministic elevation: rises 50 m per 0.001 deg east of lon 133."""

    def sample(self, lat, lon):
        return 100.0 + (lon - 133.0) * 50000.0


def _route(graph, points, snap_max_m=500.0):
    report, _ = planner.plan_route(graph, points, FakeSampler(),
                                   sample_interval_m=50.0, snap_max_m=snap_max_m)
    return report


class TestShortestBranch(unittest.TestCase):
    def test_shortest_path_picks_short_branch(self):
        # Direct A->B->C is short; detour A->D->C is longer.
        graph = _graph([
            _te("e1", "A", "B"), _te("e2", "B", "C"),
            _te("e3", "A", "D"), _te("e4", "D", "C"),
        ])
        short = _len_m("A", "B") + _len_m("B", "C")
        detour = _len_m("A", "D") + _len_m("D", "C")
        self.assertGreater(detour, short)
        report = _route(graph, [COORDS["A"], COORDS["C"]])
        self.assertEqual(report["path"]["status"], "candidate")
        self.assertAlmostEqual(report["path"]["length_m"], short, delta=0.5)
        self.assertEqual(report["legs"][0]["status"], "candidate")


class TestWaypointForcesPath(unittest.TestCase):
    def test_waypoint_uses_longer_detour(self):
        graph = _graph([
            _te("e1", "A", "B"), _te("e2", "B", "C"),
            _te("e3", "A", "D"), _te("e4", "D", "C"),
        ])
        short = _len_m("A", "B") + _len_m("B", "C")
        detour = _len_m("A", "D") + _len_m("D", "C")
        self.assertGreater(detour, short)
        # Without waypoint the short branch wins; forcing D selects the detour.
        report = _route(graph, [COORDS["A"], COORDS["D"], COORDS["C"]])
        self.assertEqual(report["path"]["status"], "candidate")
        self.assertAlmostEqual(report["path"]["length_m"], detour, delta=0.5)
        self.assertEqual(report["legs"][0]["status"], "candidate")
        self.assertEqual(report["legs"][1]["status"], "candidate")


class TestSameEdgePoints(unittest.TestCase):
    def test_two_points_on_same_edge_connect_directly(self):
        graph = _graph([_te("e1", "A", "B")])
        mid = (133.0005, 33.0)  # halfway along e1
        report = _route(graph, [COORDS["A"], mid])
        self.assertEqual(report["path"]["status"], "candidate")
        self.assertAlmostEqual(report["path"]["length_m"], _len_m("A", "B") / 2, delta=1.0)


class TestDisconnected(unittest.TestCase):
    def test_disconnected_components_no_path(self):
        graph = _graph([
            _te("e1", "A", "B"),
            _te("e5", "E", "F"),
        ])
        report = _route(graph, [COORDS["A"], COORDS["E"]])
        self.assertEqual(report["path"]["status"], "disconnected")
        self.assertIsNone(report["path"]["length_m"])
        self.assertEqual(report["legs"][0]["status"], "disconnected")


class TestElevationStats(unittest.TestCase):
    def test_gain_loss_computed(self):
        # A -> C rises 100 m over the run (FakeSampler); eastbound = net gain.
        graph = _graph([_te("e1", "A", "B"), _te("e2", "B", "C")])
        report = _route(graph, [COORDS["A"], COORDS["C"]])
        self.assertAlmostEqual(report["elevation"]["start_m"], 100.0, delta=0.01)
        self.assertAlmostEqual(report["elevation"]["end_m"], 200.0, delta=0.01)
        self.assertGreater(report["elevation"]["gain_m"], 99.0)
        self.assertEqual(report["elevation"]["loss_m"], 0.0)


class TestDensePath(unittest.TestCase):
    def test_geojson_uses_full_path_vertices(self):
        # An edge with intermediate vertices must keep them in the drawn path.
        edge = _te("e1", "A", "C")
        edge["coordinates"] = [
            list(COORDS["A"]), [133.0005, 33.0], [133.001, 33.0],
            [133.0015, 33.0], list(COORDS["C"]),
        ]
        graph = _graph([edge])
        report, profile = planner.plan_route(
            graph, [COORDS["A"], COORDS["C"]], FakeSampler(),
            sample_interval_m=50.0, snap_max_m=500.0)
        dense = report["dense_path"]
        self.assertEqual(len(dense), len(edge["coordinates"]))
        geojson = planner.build_plan_geojson(report, profile)
        route = next(f for f in geojson["features"]
                     if f["properties"]["kind"] == "planned_route")
        self.assertEqual(route["geometry"]["coordinates"], dense)
        self.assertTrue(all(len(c) == 3 for c in route["geometry"]["coordinates"]))


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


class TestSnapTooFar(unittest.TestCase):
    def test_point_far_from_route_rejected(self):
        graph = _graph([_te("e1", "A", "B")])
        far = (132.0, 33.0)  # ~90 km away
        with self.assertRaises(ValueError):
            _route(graph, [COORDS["A"], far], snap_max_m=500.0)


if __name__ == "__main__":
    unittest.main()