import json
import os
import tempfile
import unittest

from datasets.sekaiisan_henro import graph, topology
from datasets.sekaiisan_henro.projection import LAT0, LON0, project_point, unproject_point

BASE = (LON0, LAT0)


def at(dx, dy):
    """Return a (lon, lat) coordinate dx m east / dy m north of BASE."""
    x0, y0 = project_point(*BASE)
    return unproject_point(x0 + dx, y0 + dy)


def _normalized(routes, snapshot="aa" * 32, fidless=False):
    records = []
    for route_id, coords in routes:
        rec = {
            "id": route_id, "prefecture": "tokushima", "source_file": "t.kml",
            "source_fid": route_id, "part": 1,
            "source_identity": route_id, "source_identity_kind": "fid",
            "geometry": {"type": "LineString", "coordinates": list(coords)},
        }
        if fidless:
            rec.update({"source_fid": None, "source_identity": "geometry_abcdef",
                        "source_identity_kind": "geometry_sha256",
                        "geometry_sha256": "1b5f5b8c49cb43ddb50a5a8e61f6d05964ec6255dcd5f34ccc01ef778de578de"})
        records.append(rec)
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


def _build(routes, **kwargs):
    data = _normalized(routes, **kwargs)
    inventory = topology.build_inventory(data)
    return graph.build_graph(data, inventory)


def _coord(seg, index):
    return tuple(seg[index])


class TestSharedEndpointChain(unittest.TestCase):
    def test_shared_endpoint_one_node_one_component(self):
        result = _build([
            ("A", [at(0, 0), at(100, 0)]),
            ("B", [at(100, 0), at(200, 0)]),
        ])
        # 4 route endpoints -> nodes, but (100,0) shared -> 3 nodes.
        self.assertEqual(result["accounting"]["nodes"], 3)
        self.assertEqual(result["accounting"]["edges"], 2)
        self.assertEqual(result["accounting"]["components"], 1)
        shared = [n for n in result["nodes"] if n["coordinates"] == list(at(100, 0))]
        self.assertEqual(len(shared), 1)
        self.assertIn("endpoint", shared[0]["kinds"])
        self.assertIn("shared_vertex", shared[0]["kinds"])
        self.assertEqual(len(shared[0]["source_refs"]), 2)
        self.assertEqual({r["route_id"] for r in shared[0]["source_refs"]}, {"A", "B"})


class TestSharedInternalVertex(unittest.TestCase):
    def test_shared_internal_vertex_splits_and_connects(self):
        result = _build([
            ("E", [at(0, 0), at(100, 0), at(200, 0)]),
            ("F", [at(100, 0), at(100, 60)]),
        ])
        # E split at interior vertex -> 2 edges; F one edge.
        e_edges = [e for e in result["edges"] if e["provenance"]["route_id"] == "E"]
        self.assertEqual(len(e_edges), 2)
        # shared node at (100,0) is a shared internal vertex + T junction.
        shared = [n for n in result["nodes"] if n["coordinates"] == list(at(100, 0))]
        self.assertEqual(len(shared), 1)
        self.assertIn("shared_vertex", shared[0]["kinds"])
        self.assertIn("exact_t_junction", shared[0]["kinds"])
        self.assertEqual(result["accounting"]["components"], 1)
        # length preserved (A 200 + F 60)
        total = sum(e["length_m"] for e in result["edges"])
        self.assertAlmostEqual(total, 260.0, places=3)


class TestEndpointTouchTNode(unittest.TestCase):
    def test_endpoint_on_interior_creates_t_node_and_preserves_length(self):
        result = _build([
            ("A", [at(0, 0), at(100, 0)]),
            ("B", [at(50, 0), at(50, 60)]),   # B.start lands exactly on A interior
        ])
        acct = result["accounting"]
        self.assertEqual(acct["exact_connections_consumed"]["endpoint_touches_applied"], 1)
        # A split into 2 edges at the interior touch; B one edge -> 3 edges.
        self.assertEqual(acct["edges"], 3)
        # one T junction node at (50,0)
        t = [n for n in result["nodes"] if n["coordinates"] == list(at(50, 0))]
        self.assertEqual(len(t), 1)
        self.assertIn("exact_t_junction", t[0]["kinds"])
        self.assertEqual(len(t[0]["source_refs"]), 2)
        self.assertEqual({r["route_id"] for r in t[0]["source_refs"]}, {"A", "B"})
        # total length preserved (A 100 + B 60)
        total = sum(e["length_m"] for e in result["edges"])
        self.assertAlmostEqual(total, 160.0, places=3)
        self.assertEqual(acct["components"], 1)
        # exactly one ambiguous crossing connected (none)
        self.assertEqual(acct["ambiguous_crossings_connected"], 0)
        self.assertEqual(acct["proximity_connections_applied"], 0)


class TestAmbiguousCrossing(unittest.TestCase):
    def test_ambiguous_crossing_stays_two_components_no_cut(self):
        result = _build([
            ("G", [at(0, 0), at(100, 0)]),
            ("H", [at(50, -20), at(50, 20)]),   # crosses G interior, no shared vertex
        ])
        acct = result["accounting"]
        self.assertEqual(acct["ambiguous_crossings_total"], 1)
        self.assertEqual(acct["ambiguous_crossings_connected"], 0)
        self.assertEqual(acct["components"], 2)
        # the crossing point (50,0) must NOT be a node
        crossing = [n for n in result["nodes"]
                    if abs(n["coordinates"][0] - at(50, 0)[0]) < 1e-9
                    and abs(n["coordinates"][1] - at(50, 0)[1]) < 1e-9]
        self.assertEqual(crossing, [])
        # G not split -> one edge
        g_edges = [e for e in result["edges"] if e["provenance"]["route_id"] == "G"]
        self.assertEqual(len(g_edges), 1)


class TestIsolatedRoute(unittest.TestCase):
    def test_isolated_route(self):
        result = _build([("I", [at(0, 0), at(100, 0)])])
        self.assertEqual(result["accounting"]["nodes"], 2)
        self.assertEqual(result["accounting"]["edges"], 1)
        self.assertEqual(result["accounting"]["components"], 1)
        # a route with two endpoints joined by an edge is a normal component,
        # not an "isolated component" (that is a degree-0 single-node component).
        self.assertEqual(result["accounting"]["isolated_components"], 0)


class TestMultipleCutsAndPreservation(unittest.TestCase):
    def test_cuts_ordered_and_intermediate_vertices_preserved(self):
        result = _build([
            ("A", [at(0, 0), at(100, 0), at(200, 0)]),
            ("B", [at(100, 0), at(100, 60)]),        # shared interior vertex
            ("D", [at(150, 0), at(150, 50)]),        # T target on A interior
        ])
        a_edges = sorted(
            [e for e in result["edges"] if e["provenance"]["route_id"] == "A"],
            key=lambda e: e["provenance"]["source_start_measure"])
        self.assertEqual(len(a_edges), 3)
        # ordered from source start: first edge starts at A.start
        self.assertEqual(a_edges[0]["coordinates"][0], list(at(0, 0)))
        self.assertEqual(a_edges[-1]["coordinates"][-1], list(at(200, 0)))
        # intermediate source vertex (100,0) preserved exactly on both sides
        self.assertEqual(a_edges[0]["coordinates"][-1], list(at(100, 0)))
        self.assertEqual(a_edges[1]["coordinates"][0], list(at(100, 0)))
        # T interpolation point at (150,0)
        self.assertEqual(a_edges[1]["coordinates"][-1][0], at(150, 0)[0])
        self.assertEqual(a_edges[2]["coordinates"][0][0], at(150, 0)[0])
        # length preserved
        total = sum(e["length_m"] for e in result["edges"])
        self.assertAlmostEqual(total, 200.0 + 60.0 + 50.0, places=3)


class TestDirectionAndIDs(unittest.TestCase):
    def test_source_direction_retained(self):
        result = _build([
            ("A", [at(0, 0), at(100, 0)]),
            ("B", [at(100, 0), at(200, 0)]),
        ])
        a_edge = [e for e in result["edges"] if e["provenance"]["route_id"] == "A"][0]
        b_edge = [e for e in result["edges"] if e["provenance"]["route_id"] == "B"][0]
        # edges retain source direction (from = earlier vertex in source order)
        self.assertEqual(a_edge["coordinates"][0], list(at(0, 0)))
        self.assertEqual(a_edge["coordinates"][-1], list(at(100, 0)))
        self.assertEqual(b_edge["coordinates"][0], list(at(100, 0)))
        self.assertEqual(b_edge["coordinates"][-1], list(at(200, 0)))

    def test_deterministic_ids_and_byte_output(self):
        data = _normalized([
            ("A", [at(0, 0), at(100, 0)]),
            ("B", [at(100, 0), at(200, 0)]),
            ("C", [at(50, 0), at(50, 60)]),
        ])
        inv = topology.build_inventory(data)
        first = json.dumps(graph.build_graph(data, inv), sort_keys=True)
        second = json.dumps(graph.build_graph(data, inv), sort_keys=True)
        self.assertEqual(first, second)
        self.assertIn('"id": "SHN_', first)
        self.assertIn('"id": "SHE_', first)
        self.assertNotIn("timestamp", first)


class TestAccounting(unittest.TestCase):
    def test_accounting_and_length_reconstruction(self):
        result = _build([
            ("A", [at(0, 0), at(100, 0)]),
            ("B", [at(100, 0), at(200, 0)]),
        ])
        acct = result["accounting"]
        self.assertEqual(acct["source_linestrings"], 2)
        self.assertEqual(acct["source_points"], 4)
        self.assertEqual(acct["nodes"], 3)
        self.assertEqual(acct["edges"], 2)
        self.assertEqual(acct["components"], 1)
        self.assertEqual(acct["proximity_connections_applied"], 0)
        self.assertEqual(acct["ambiguous_crossings_connected"], 0)
        lens = acct["lengths"]
        self.assertAlmostEqual(lens["global_original_m"], 200.0, places=3)
        self.assertAlmostEqual(lens["global_reconstructed_m"], 200.0, places=3)
        self.assertLess(lens["max_absolute_error_m"], 1e-5)


class TestFailureAndAtomicity(unittest.TestCase):
    def _fixture_routes(self):
        return [
            ("A", [at(0, 0), at(100, 0)]),
            ("B", [at(100, 0), at(200, 0)]),
        ]

    def test_snapshot_mismatch_fails(self):
        data = _normalized(self._fixture_routes())
        inv = topology.build_inventory(data)
        inv["snapshot_sha256"] = "bb" * 32
        with self.assertRaisesRegex(ValueError, "snapshot mismatch"):
            graph.build_graph(data, inv)

    def test_dataset_mismatch_fails(self):
        data = _normalized(self._fixture_routes())
        inv = topology.build_inventory(data)
        inv["dataset_id"] = "other"
        with self.assertRaisesRegex(ValueError, "dataset mismatch"):
            graph.build_graph(data, inv)

    def test_inventory_kind_required(self):
        data = _normalized(self._fixture_routes())
        inv = topology.build_inventory(data)
        inv["kind"] = "not_topology_inventory"
        with self.assertRaisesRegex(ValueError, "topology_inventory"):
            graph.build_graph(data, inv)

    def test_source_accounting_mismatch_fails(self):
        data = _normalized(self._fixture_routes())
        inv = topology.build_inventory(data)
        inv["source_accounting"]["linestrings"] += 1
        with self.assertRaisesRegex(ValueError, "accounting mismatch"):
            graph.build_graph(data, inv)

    def test_duplicate_geometry_explicit_failure(self):
        data = _normalized([
            ("I", [at(0, 0), at(100, 0)]),
            ("J", [at(0, 0), at(100, 0)]),
        ])
        inv = topology.build_inventory(data)
        self.assertEqual(inv["intersections"]["summary"]["duplicate_geometries"], 1)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            graph.build_graph(data, inv)

    def test_linear_overlap_explicit_failure(self):
        data = _normalized([
            ("L", [at(0, 0), at(100, 0)]),
            ("M", [at(30, 0), at(70, 0)]),
        ])
        inv = topology.build_inventory(data)
        self.assertEqual(inv["intersections"]["summary"]["linear_overlaps"], 1)
        with self.assertRaisesRegex(ValueError, "overlap"):
            graph.build_graph(data, inv)

    def test_atomic_failure_preserves_prior_output(self):
        tmp = tempfile.mkdtemp()
        data = _normalized(self._fixture_routes())
        inv = topology.build_inventory(data)
        bad_data = dict(data, snapshot_sha256="bb" * 32)  # mismatched
        data_path = os.path.join(tmp, "n.json")
        inv_path = os.path.join(tmp, "i.json")
        out_path = os.path.join(tmp, "g.json")
        with open(data_path, "w", encoding="utf-8") as stream:
            json.dump(bad_data, stream)
        with open(inv_path, "w", encoding="utf-8") as stream:
            json.dump(inv, stream)
        with open(out_path, "w", encoding="utf-8") as stream:
            stream.write("SENTINEL")
        with self.assertRaises(ValueError):
            graph.run_graph(data_path, inv_path, out_path)
        with open(out_path, encoding="utf-8") as stream:
            self.assertEqual(stream.read(), "SENTINEL")

    def test_successful_run_is_atomic(self):
        tmp = tempfile.mkdtemp()
        data = _normalized(self._fixture_routes())
        inv = topology.build_inventory(data)
        data_path = os.path.join(tmp, "n.json")
        inv_path = os.path.join(tmp, "i.json")
        out_path = os.path.join(tmp, "g.json")
        with open(data_path, "w", encoding="utf-8") as stream:
            json.dump(data, stream)
        with open(inv_path, "w", encoding="utf-8") as stream:
            json.dump(inv, stream)
        result = graph.run_graph(data_path, inv_path, out_path)
        self.assertEqual(result["kind"], "exact_route_graph")
        with open(out_path, encoding="utf-8") as stream:
            self.assertEqual(json.load(stream)["kind"], "exact_route_graph")
        self.assertFalse(os.path.exists(out_path + ".tmp"))


class TestFidlessProvenance(unittest.TestCase):
    def test_fidless_route_provenance_retained(self):
        result = _build([
            ("A", [at(0, 0), at(100, 0)]),
        ], fidless=True)
        a_edge = [e for e in result["edges"] if e["provenance"]["route_id"] == "A"][0]
        prov = a_edge["provenance"]
        self.assertIsNone(prov["source_fid"])
        self.assertEqual(prov["source_identity"], "geometry_abcdef")
        self.assertEqual(prov["source_identity_kind"], "geometry_sha256")
        self.assertIn("geometry_sha256", prov)
        self.assertEqual(result["route_sources"]["A"]["source_identity_kind"],
                         "geometry_sha256")
        self.assertIn("geometry_sha256", result["route_sources"]["A"])


class TestPerRouteLengths(unittest.TestCase):
    def test_per_route_present_and_sums_match(self):
        result = _build([
            ("A", [at(0, 0), at(100, 0)]),
            ("B", [at(100, 0), at(100, 60)]),
        ])
        per_route = result["accounting"]["lengths"]["per_route"]
        # every source route is present
        self.assertEqual(set(per_route), {"A", "B"})
        for route_id, rec in per_route.items():
            self.assertIn("original_m", rec)
            self.assertIn("reconstructed_m", rec)
            self.assertIn("error_m", rec)
        # sums match global
        self.assertAlmostEqual(
            sum(r["original_m"] for r in per_route.values()),
            result["accounting"]["lengths"]["global_original_m"], places=6)
        self.assertAlmostEqual(
            sum(r["reconstructed_m"] for r in per_route.values()),
            result["accounting"]["lengths"]["global_reconstructed_m"], places=6)
        # per-route reconstruction matches edge sums
        for route_id, rec in per_route.items():
            edge_sum = sum(e["length_m"] for e in result["edges"]
                           if e["provenance"]["route_id"] == route_id)
            self.assertAlmostEqual(rec["reconstructed_m"], edge_sum, places=6)


class TestComponents(unittest.TestCase):
    def test_component_edge_membership(self):
        result = _build([
            ("A", [at(0, 0), at(100, 0)]),
            ("B", [at(100, 0), at(200, 0)]),
            ("C", [at(500, 0), at(600, 0)]),     # isolated component
        ])
        all_edge_ids = [e["id"] for e in result["edges"]]
        all_node_ids = [n["id"] for n in result["nodes"]]
        seen_edges = set()
        for comp in result["components"]:
            # counts match list lengths
            self.assertEqual(comp["node_count"], len(comp["nodes"]))
            self.assertEqual(comp["edge_count"], len(comp["edges"]))
            # lists are sorted
            self.assertEqual(comp["nodes"], sorted(comp["nodes"]))
            self.assertEqual(comp["edges"], sorted(comp["edges"]))
            # nodes belong to component
            for eid in comp["edges"]:
                edge = next(e for e in result["edges"] if e["id"] == eid)
                self.assertIn(edge["from"], comp["nodes"])
                self.assertIn(edge["to"], comp["nodes"])
                seen_edges.add(eid)
        # every graph edge appears in exactly one component
        self.assertEqual(seen_edges, set(all_edge_ids))
        self.assertEqual(len(seen_edges), len(all_edge_ids))

    def test_largest_component_accounting(self):
        result = _build([
            ("A", [at(0, 0), at(100, 0)]),
            ("B", [at(100, 0), at(200, 0)]),
            ("C", [at(500, 0), at(600, 0)]),
        ])
        acct = result["accounting"]
        largest = max(result["components"], key=lambda c: (c["node_count"], c["id"]))
        self.assertEqual(acct["largest_component_nodes"], largest["node_count"])
        self.assertEqual(acct["largest_component_edges"], largest["edge_count"])
        self.assertGreater(acct["largest_component_nodes"], 2)


class TestCutDedupeAndConflict(unittest.TestCase):
    def _fake_entry(self):
        x0, y0 = project_point(*at(0, 0))
        metric = [(x0 + dx, y0) for dx in (0, 50, 100)]
        return {
            "id": "A",
            "wgs84": [at(0, 0), at(50, 0), at(100, 0)],
            "metric": metric,
            "cum": [0.0, 50.0, 100.0],
        }

    def _target_cut(self, s, group):
        return {"s": s, "point": (0.0, 0.0), "wgs84": group,
                "group": group, "kind": "exact_t_junction", "is_vertex": False}

    def test_same_group_dedupe_keeps_one(self):
        entry = self._fake_entry()
        cuts = graph._route_cuts(entry, set(), [
            self._target_cut(50.0, at(50, 0)),
            self._target_cut(50.0, at(50, 0)),   # identical position + group
        ])
        # start + end + one deduped target
        self.assertEqual(len(cuts), 3)
        same = [c for c in cuts if abs(c["s"] - 50.0) < 1e-9]
        self.assertEqual(len(same), 1)
        self.assertEqual(same[0]["kind"], "exact_t_junction")

    def test_same_group_dedupe_keeps_stronger_kind_and_vertex(self):
        entry = self._fake_entry()
        # a shared-vertex cut (is_vertex=True) colliding with a target cut
        shared = {"s": 50.0, "point": entry["metric"][1], "wgs84": at(50, 0),
                  "group": at(50, 0), "kind": "shared_vertex", "is_vertex": True}
        target = self._target_cut(50.0, at(50, 0))
        cuts = graph._route_cuts(entry, set(), [shared, target])
        same = [c for c in cuts if abs(c["s"] - 50.0) < 1e-9]
        self.assertEqual(len(same), 1)
        # strongest kind preserved (exact_t_junction > shared_vertex) and the
        # exact source vertex coordinate is retained.
        self.assertEqual(same[0]["kind"], "exact_t_junction")
        self.assertTrue(same[0]["is_vertex"])
        self.assertEqual(same[0]["wgs84"], at(50, 0))

    def test_conflicting_groups_at_same_position_fails(self):
        entry = self._fake_entry()
        with self.assertRaisesRegex(ValueError, "conflicting cuts"):
            graph._route_cuts(entry, set(), [
                self._target_cut(50.0, at(50, 0)),
                self._target_cut(50.0, at(60, 0)),   # same position, different group
            ])


if __name__ == "__main__":
    unittest.main()