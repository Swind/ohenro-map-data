import json
import unittest

from datasets.sekaiisan_henro import graph, proximity, topology
from datasets.sekaiisan_henro.projection import LAT0, LON0, project_point, unproject_point

BASE = (LON0, LAT0)


def at(dx, dy):
    """Return a (lon, lat) coordinate dx m east / dy m north of BASE."""
    x0, y0 = project_point(*BASE)
    return unproject_point(x0 + dx, y0 + dy)


def _normalized(routes, snapshot="aa" * 32):
    records = []
    for route_id, coords in routes:
        records.append({
            "id": route_id, "prefecture": "tokushima", "source_file": "t.kml",
            "source_fid": route_id, "part": 1,
            "source_identity": route_id, "source_identity_kind": "fid",
            "geometry": {"type": "LineString", "coordinates": list(coords)},
        })
    return {
        "schema_version": 1,
        "dataset_id": "88sekaiisan-henro",
        "snapshot_sha256": snapshot,
        "routes": records,
        "temples": [],
        "accounting": {
            "routes": len(routes), "linestrings": len(routes),
            "points": sum(len(coords) for _, coords in routes),
            "temples": 0, "missing_source_fid": 0, "by_prefecture": {},
        },
    }


def _prox(routes):
    data = _normalized(routes)
    inv = topology.build_inventory(data)
    exact = graph.build_graph(data, inv)
    return proximity.build_proximity_graph(exact, inv, data), exact


class TestEndpointClusterApplied(unittest.TestCase):
    def test_unambiguous_two_endpoint_cluster_joins(self):
        # A.start (0,0) and B.start (-3,-3) are 4.24m apart; B's stub points away
        # so the only <=5m relation is the two endpoints (cluster of exactly 2).
        result, exact = _prox([
            ("A", [at(0, 0), at(100, 0)]),
            ("B", [at(-3, -3), at(-3, -80)]),
        ])
        acct = result["accounting"]
        self.assertEqual(acct["synthetic_joins"], 1)
        self.assertEqual(acct["synthetic_nodes"], 0)
        self.assertEqual(acct["components_before"], 2)
        self.assertEqual(acct["components_after"], 1)
        prox = acct["proximity"]
        self.assertEqual(prox["endpoint_clusters_applied"], 1)
        self.assertEqual(prox["endpoint_clusters_rejected_ambiguous"], 0)
        join = result["synthetic_joins"][0]
        self.assertEqual(join["kind"], "endpoint_cluster")
        self.assertLessEqual(join["distance_m"], 5.0)
        # every applied join is reported as applied
        applied = [r for r in result["proximity_report"] if r["applied"]]
        self.assertEqual(len(applied), 1)
        self.assertEqual(applied[0]["kind"], "endpoint_cluster")


class TestEndpointToLineApplied(unittest.TestCase):
    def test_unique_endpoint_to_interior_t_join(self):
        # X.start (50,4) is 4m from Y interior (50,0). Y is the only target and
        # X.start the only endpoint -> unique -> applied as synthetic T join.
        result, exact = _prox([
            ("Y", [at(0, 0), at(100, 0)]),
            ("X", [at(50, 4), at(50, 40)]),
        ])
        acct = result["accounting"]
        self.assertEqual(acct["synthetic_joins"], 1)
        self.assertEqual(acct["synthetic_nodes"], 1)
        self.assertEqual(acct["components_before"], 2)
        self.assertEqual(acct["components_after"], 1)
        prox = acct["proximity"]
        self.assertEqual(prox["endpoint_to_line_applied"], 1)
        self.assertEqual(prox["endpoint_to_line_rejected_competing"], 0)
        join = result["synthetic_joins"][0]
        self.assertEqual(join["kind"], "endpoint_to_line")
        self.assertEqual(join["target_route"], "Y")
        node = result["synthetic_nodes"][0]
        self.assertIn("synthetic_t", node["kinds"])
        self.assertEqual(node["attached"]["route_id"], "Y")
        # projected point on Y interior, 4m from X.start
        self.assertLessEqual(join["distance_m"], 5.0)
        # the synthetic node sits at Y's interior (50,0)
        self.assertAlmostEqual(node["coordinates"][0], at(50, 0)[0], places=6)
        self.assertAlmostEqual(node["coordinates"][1], at(50, 0)[1], places=6)
        # source edge for Y is preserved unsplit (still one edge)
        y_edges = [e for e in result["edges"] if e["provenance"]["route_id"] == "Y"]
        self.assertEqual(len(y_edges), 1)


class TestGapsRejected(unittest.TestCase):
    def test_5_20m_gaps_reported_not_joined(self):
        # B.start (10,-8) is 12.8m from A.start and 8m from A interior -> gaps.
        result, exact = _prox([
            ("A", [at(0, 0), at(100, 0)]),
            ("B", [at(10, -8), at(10, -90)]),
        ])
        acct = result["accounting"]
        self.assertEqual(acct["synthetic_joins"], 0)
        self.assertEqual(acct["components_before"], 2)
        self.assertEqual(acct["components_after"], 2)
        prox = acct["proximity"]
        self.assertGreaterEqual(prox["gaps_5_20m_reported"], 1)
        gaps = [r for r in result["proximity_report"]
                if r["kind"] in ("endpoint_pair_gap", "endpoint_to_line_gap")]
        self.assertGreaterEqual(len(gaps), 1)
        self.assertTrue(all(not r["applied"] for r in gaps))


class TestCompetitionRejected(unittest.TestCase):
    def test_endpoint_targets_two_lines_rejected(self):
        # X.start (50,4) is 4m from Y1 interior (50,0) and 4m from Y2 interior
        # (50,8) -> competing -> both rejected.
        result, exact = _prox([
            ("Y1", [at(0, 0), at(100, 0)]),
            ("Y2", [at(0, 8), at(100, 8)]),
            ("X", [at(50, 4), at(50, 40)]),
        ])
        acct = result["accounting"]
        self.assertEqual(acct["synthetic_joins"], 0)
        prox = acct["proximity"]
        self.assertEqual(prox["endpoint_to_line_rejected_competing"], 2)
        rejected = [r for r in result["proximity_report"]
                    if r["kind"] == "endpoint_to_line" and not r["applied"]]
        self.assertEqual(len(rejected), 2)
        self.assertTrue(all("competing" in r["reason"] for r in rejected))

    def test_line_targeted_by_two_endpoints_rejected(self):
        # X1.start (30,4) and X2.start (70,3) both target Y interior within 5m
        # (at different projected points) -> line targeted by two endpoints ->
        # competing -> both rejected. The endpoints are far apart (40m), so no
        # endpoint cluster forms.
        result, exact = _prox([
            ("Y", [at(0, 0), at(100, 0)]),
            ("X1", [at(30, 4), at(30, 30)]),
            ("X2", [at(70, 3), at(70, 30)]),
        ])
        acct = result["accounting"]
        self.assertEqual(acct["synthetic_joins"], 0)
        prox = acct["proximity"]
        self.assertEqual(prox["endpoint_to_line_rejected_competing"], 2)
        self.assertEqual(prox["endpoint_to_line_applied"], 0)


class TestChainCompetitionRejected(unittest.TestCase):
    def test_chain_ab_bc_no_join_because_b_degree_two(self):
        # A-B <=5m and B-C <=5m but A-C >5m (error chain). B has two <=5m
        # candidates (degree 2), so both A-B and B-C are competing and must be
        # rejected without any join.
        result, exact = _prox([
            ("A", [at(0, 0), at(0, 200)]),
            ("B", [at(4, 0), at(4, -200)]),
            ("C", [at(8, 0), at(200, 0)]),
        ])
        acct = result["accounting"]
        self.assertEqual(acct["synthetic_joins"], 0)
        self.assertEqual(acct["components_before"], 3)
        self.assertEqual(acct["components_after"], 3)
        prox = acct["proximity"]
        self.assertEqual(prox["endpoint_clusters_applied"], 0)
        # exactly the two candidate edges (A-B and B-C) are rejected
        self.assertEqual(prox["endpoint_clusters_rejected_ambiguous"], 2)
        rejected = [r for r in result["proximity_report"]
                    if r["kind"] == "endpoint_cluster" and not r["applied"]]
        self.assertEqual(len(rejected), 2)
        self.assertTrue(all("competing" in r["reason"] for r in rejected))


class TestAmbiguousClusterRetained(unittest.TestCase):
    def test_three_endpoint_cluster_ambiguous_not_joined(self):
        # A.start (0,0), B.start (3,0), C.start (1.5,3) are all mutually <=5m
        # (diameter <=5) but form a 3-endpoint cluster -> ambiguous, not joined.
        # The three routes extend away in distinct directions (west / east /
        # north), so their far ends create no other near relations.
        result, exact = _prox([
            ("A", [at(0, 0), at(-200, 0)]),
            ("B", [at(3, 0), at(200, 0)]),
            ("C", [at(1.5, 3), at(1.5, 200)]),
        ])
        acct = result["accounting"]
        self.assertEqual(acct["synthetic_joins"], 0)
        prox = acct["proximity"]
        self.assertEqual(prox["endpoint_clusters_rejected_ambiguous"], 3)
        self.assertEqual(prox["endpoint_clusters_applied"], 0)
        self.assertEqual(acct["components_before"], 3)
        self.assertEqual(acct["components_after"], 3)
        rejected = [r for r in result["proximity_report"]
                    if r["kind"] == "endpoint_cluster" and not r["applied"]]
        self.assertEqual(len(rejected), 3)
        self.assertTrue(all("ambiguous" in r["reason"] for r in rejected))


class TestAmbiguousCrossingRetained(unittest.TestCase):
    def test_ambiguous_crossing_reported_not_joined(self):
        # G and H cross interior/interior without a shared vertex.
        result, exact = _prox([
            ("G", [at(0, 0), at(100, 0)]),
            ("H", [at(50, -20), at(50, 20)]),
        ])
        acct = result["accounting"]
        self.assertEqual(acct["synthetic_joins"], 0)
        prox = acct["proximity"]
        self.assertEqual(prox["ambiguous_crossings_total"], 1)
        self.assertEqual(prox["ambiguous_crossings_connected"], 0)
        crossings = [r for r in result["proximity_report"]
                     if r["kind"] == "ambiguous_crossing"]
        self.assertEqual(len(crossings), 1)
        self.assertFalse(crossings[0]["applied"])


class TestPreservationAndDeterminism(unittest.TestCase):
    def _routes(self):
        return [
            ("A", [at(0, 0), at(100, 0)]),
            ("B", [at(-3, -3), at(-3, -80)]),
        ]

    def test_source_edges_nodes_and_lengths_preserved(self):
        result, exact = _prox(self._routes())
        self.assertEqual(result["nodes"], exact["nodes"])
        self.assertEqual(result["edges"], exact["edges"])
        self.assertEqual(result["components_before"], exact["components"])
        self.assertEqual(result["route_sources"], exact["route_sources"])
        self.assertEqual(result["accounting"]["lengths"],
                         exact["accounting"]["lengths"])
        self.assertEqual(result["kind"], "proximity_route_graph")

    def test_byte_determinism(self):
        data = _normalized(self._routes())
        inv = topology.build_inventory(data)
        exact = graph.build_graph(data, inv)
        first = json.dumps(
            proximity.build_proximity_graph(exact, inv, data), sort_keys=True)
        second = json.dumps(
            proximity.build_proximity_graph(exact, inv, data), sort_keys=True)
        self.assertEqual(first, second)
        self.assertIn('"kind": "proximity_route_graph"', first)
        self.assertIn('"id": "SHJ_', first)
        self.assertNotIn("timestamp", first)

    def test_snapshot_mismatch_fails(self):
        data = _normalized(self._routes())
        inv = topology.build_inventory(data)
        exact = graph.build_graph(data, inv)
        inv["snapshot_sha256"] = "bb" * 32
        with self.assertRaisesRegex(ValueError, "snapshot mismatch"):
            proximity.build_proximity_graph(exact, inv, data)

    def test_graph_kind_required(self):
        data = _normalized(self._routes())
        inv = topology.build_inventory(data)
        exact = graph.build_graph(data, inv)
        exact["kind"] = "not_exact_route_graph"
        with self.assertRaisesRegex(ValueError, "exact_route_graph"):
            proximity.build_proximity_graph(exact, inv, data)


if __name__ == "__main__":
    unittest.main()