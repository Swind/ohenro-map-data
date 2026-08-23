import json
import os
import tempfile
import unittest

from sekaiisan_henro import topology
from sekaiisan_henro.projection import LAT0, LON0, project_point, unproject_point

BASE = (LON0, LAT0)


def at(dx, dy):
    """Return a (lon, lat) coordinate that is dx metres east / dy metres north of BASE."""
    x0, y0 = project_point(*BASE)
    return unproject_point(x0 + dx, y0 + dy)


def _normalized(routes, snapshot="aa" * 32):
    return {
        "schema_version": 1,
        "dataset_id": "88sekaiisan-henro",
        "snapshot_sha256": snapshot,
        "routes": [
            {"id": route_id, "prefecture": "tokushima", "source_file": "t.kml",
             "source_fid": route_id, "part": 1,
             "geometry": {"type": "LineString", "coordinates": list(coords)}}
            for route_id, coords in routes
        ],
        "temples": [],
        "accounting": {
            "routes": len(routes), "linestrings": len(routes),
            "points": sum(len(coords) for _, coords in routes),
            "temples": 0, "missing_source_fid": 0, "by_prefecture": {},
        },
    }


def _ids(inventory, key):
    return [(r["route_a"], r["route_b"]) for r in inventory[key]]


class TestExactConnections(unittest.TestCase):
    def test_shared_endpoint_and_vertex_classifications(self):
        data = _normalized([
            ("A", [at(0, 0), at(100, 0)]),
            ("B", [at(0, 0), at(0, 100)]),                 # shared start with A
            ("C", [at(200, 0), at(300, 0), at(400, 0)]),
            ("D", [at(300, 0), at(300, 60)]),              # D.start == C interior vertex
            ("E", [at(500, 0), at(600, 0), at(700, 0)]),
            ("F", [at(550, 0), at(600, 0), at(650, 0)]),   # shares interior vertex with E
        ])
        inv = topology.build_inventory(data)
        exact = inv["exact_connections"]
        self.assertEqual(exact["summary"]["shared_endpoints"], 1)
        self.assertEqual(exact["summary"]["endpoint_to_vertex"], 1)
        self.assertEqual(exact["summary"]["shared_internal_vertices"], 1)
        self.assertEqual(_ids(exact, "shared_endpoints"), [("A", "B")])
        self.assertEqual(_ids(exact, "endpoint_to_vertex"), [("C", "D")])
        self.assertEqual(_ids(exact, "shared_internal_vertices"), [("E", "F")])

    def test_source_not_mutated_and_duplicates_counted(self):
        data = _normalized([
            ("A", [at(0, 0), at(0, 0), at(50, 0)]),
        ])
        original = [tuple(c) for c in data["routes"][0]["geometry"]["coordinates"]]
        inv = topology.build_inventory(data)
        aa = inv["analysis_accounting"]
        self.assertEqual(aa["consecutive_duplicate_points"], 1)
        self.assertEqual(aa["source_points"], 3)
        self.assertEqual(aa["cleaned_points"], 2)
        # raw normalized data untouched
        self.assertEqual(
            [tuple(c) for c in data["routes"][0]["geometry"]["coordinates"]], original)
        self.assertEqual(len(data["routes"][0]["geometry"]["coordinates"]), 3)


class TestProximityCandidates(unittest.TestCase):
    def test_endpoint_pair_buckets(self):
        data = _normalized([
            ("N", [at(0, 0), at(100, 0)]),
            ("O", [at(3, 0), at(103, 0)]),    # starts 3 m apart, ends 3 m apart
            ("P", [at(10, 0), at(110, 0)]),   # starts 10 m apart
        ])
        inv = topology.build_inventory(data)
        pairs = inv["proximity_candidates"]["endpoint_pairs"]
        le5 = {(r["route_a"], r["route_b"]) for r in pairs["<=5m"]}
        gt5 = {(r["route_a"], r["route_b"]) for r in pairs["5-20m"]}
        self.assertIn(("N", "O"), le5)
        self.assertIn(("N", "P"), gt5)
        for rec in pairs["<=5m"]:
            self.assertLessEqual(rec["distance_m"], 5.0)
        for rec in pairs["5-20m"]:
            self.assertGreater(rec["distance_m"], 5.0)
            self.assertLessEqual(rec["distance_m"], 20.0)

    def test_endpoint_to_line_interior_buckets(self):
        data = _normalized([
            ("Q", [at(0, 0), at(100, 0)]),
            ("R", [at(3, 3), at(3, 50)]),      # R.start is 3 m from Q interior
            ("S", [at(10, 10), at(10, 50)]),   # S.start is 10 m from Q interior
        ])
        inv = topology.build_inventory(data)
        e2l = inv["proximity_candidates"]["endpoint_to_line"]
        by_target = {(r["endpoint_route"], r["target_route"]): r
                     for r in e2l["<=5m"] + e2l["5-20m"]}
        self.assertIn(("R", "Q"), by_target)
        self.assertIn(("S", "Q"), by_target)
        self.assertLessEqual(by_target[("R", "Q")]["distance_m"], 5.0)
        self.assertGreater(by_target[("S", "Q")]["distance_m"], 5.0)
        self.assertLessEqual(by_target[("S", "Q")]["distance_m"], 20.0)
        # projection must be interior of Q (x in 0..100, y~0)
        lon, lat = by_target[("R", "Q")]["projected_coordinates"]
        x, y = project_point(lon, lat)
        self.assertGreater(x, 0.0)
        self.assertLess(x, 100.0)
        self.assertAlmostEqual(y, 0.0, delta=1e-6)
        # endpoint_coordinates is a flat [lon, lat], not nested [[lon, lat]]
        for rec in e2l["<=5m"] + e2l["5-20m"]:
            self.assertEqual(len(rec["endpoint_coordinates"]), 2)
            self.assertIsInstance(rec["endpoint_coordinates"][0], float)
            self.assertEqual(len(rec["endpoint_coordinates"]), 2)


class TestIntersections(unittest.TestCase):
    def test_ambiguous_interior_crossing_not_exact_connected(self):
        data = _normalized([
            ("G", [at(0, 0), at(100, 0)]),
            ("H", [at(50, -20), at(50, 20)]),   # crosses G interior, no shared vertex
        ])
        inv = topology.build_inventory(data)
        self.assertEqual(inv["intersections"]["summary"]["ambiguous_crossings"], 1)
        self.assertEqual(_ids(inv["intersections"], "ambiguous_crossings"), [("G", "H")])
        # no exact shared vertex between G and H
        exact = inv["exact_connections"]["summary"]
        self.assertEqual(exact["shared_endpoints"] + exact["endpoint_to_vertex"]
                         + exact["shared_internal_vertices"], 0)

    def test_duplicate_geometry_detected(self):
        data = _normalized([
            ("I", [at(0, 0), at(100, 0)]),
            ("J", [at(0, 0), at(100, 0)]),
        ])
        inv = topology.build_inventory(data)
        self.assertEqual(inv["intersections"]["summary"]["duplicate_geometries"], 1)
        self.assertEqual(_ids(inv["intersections"], "duplicate_geometries"), [("I", "J")])

    def test_duplicate_detected_with_extra_collinear_vertex(self):
        # J is topologically equal to I but has an extra collinear vertex.
        data = _normalized([
            ("I", [at(0, 0), at(100, 0)]),
            ("J", [at(0, 0), at(50, 0), at(100, 0)]),
        ])
        inv = topology.build_inventory(data)
        self.assertEqual(inv["intersections"]["summary"]["duplicate_geometries"], 1)
        self.assertEqual(_ids(inv["intersections"], "duplicate_geometries"), [("I", "J")])

    def test_duplicate_detected_with_reversed_direction(self):
        data = _normalized([
            ("I", [at(0, 0), at(100, 0)]),
            ("J", [at(100, 0), at(0, 0)]),
        ])
        inv = topology.build_inventory(data)
        self.assertEqual(inv["intersections"]["summary"]["duplicate_geometries"], 1)
        self.assertEqual(_ids(inv["intersections"], "duplicate_geometries"), [("I", "J")])

    def test_geometry_collection_intersection_flattened(self):
        # A mixed GeometryCollection (linear + point) must be flattened into
        # both components rather than silently ignored. Synthetic fixture fed
        # straight to the flatten helper (two simple source lines do not
        # naturally yield a mixed collection).
        from shapely.geometry import GeometryCollection, LineString, Point
        linear, points = [], []
        gc = GeometryCollection([LineString([(0, 0), (10, 0)]), Point((5, 5))])
        topology._flatten_intersection(gc, linear, points)
        self.assertEqual(len(linear), 1)
        self.assertEqual(len(points), 1)
        self.assertAlmostEqual(linear[0].length, 10.0)
        self.assertEqual((points[0].x, points[0].y), (5.0, 5.0))
        # MultiLineString linear parts are each flattened, not ignored.
        from shapely.geometry import MultiLineString
        linear, points = [], []
        topology._flatten_intersection(
            MultiLineString([LineString([(0, 0), (5, 0)]),
                             LineString([(5, 0), (10, 0)])]), linear, points)
        self.assertEqual(len(linear), 2)
        self.assertEqual(points, [])

    def test_multiline_overlap_sums_to_single_record(self):
        # B overlaps A as a MultiLineString (split at a shared vertex); the
        # inventory must emit ONE overlap record with summed length.
        data = _normalized([
            ("A", [at(0, 0), at(100, 0)]),
            ("B", [at(0, 0), at(30, 0), at(60, 0), at(60, 30)]),
        ])
        inv = topology.build_inventory(data)
        overlaps = inv["intersections"]["linear_overlaps"]
        self.assertEqual(len(overlaps), 1)
        self.assertEqual(overlaps[0]["route_a"], "A")
        self.assertEqual(overlaps[0]["route_b"], "B")
        self.assertAlmostEqual(overlaps[0]["length_m"], 60.0, places=3)

    def test_linear_overlap_detected(self):
        data = _normalized([
            ("L", [at(0, 0), at(100, 0)]),
            ("M", [at(30, 0), at(70, 0)]),
        ])
        inv = topology.build_inventory(data)
        self.assertEqual(inv["intersections"]["summary"]["linear_overlaps"], 1)
        self.assertEqual(_ids(inv["intersections"], "linear_overlaps"), [("L", "M")])


class TestDiagnosticComponents(unittest.TestCase):
    def test_endpoint_to_interior_vertex_not_joined_in_diagnostic(self):
        # D.start lands exactly on C's interior vertex (a T-junction). Because
        # the endpoint-only diagnostic joins routes ONLY by endpoint-to-endpoint
        # pairs, C and D must remain separate at every tolerance.
        data = _normalized([
            ("C", [at(200, 0), at(300, 0), at(400, 0)]),
            ("D", [at(300, 0), at(300, 60)]),
        ])
        inv = topology.build_inventory(data)
        # The T-junction IS detected in exact connections...
        self.assertEqual(inv["exact_connections"]["summary"]["endpoint_to_vertex"], 1)
        self.assertEqual(_ids(inv["exact_connections"], "endpoint_to_vertex"), [("C", "D")])
        # ...but is deliberately excluded from the endpoint-only components.
        for tolerance in ("0m", "1m", "5m", "10m"):
            comp = inv["diagnostic_components"]["tolerances"][tolerance]
            self.assertEqual(comp, {"component_count": 2, "largest_component_lines": 1,
                                    "isolated_lines": 2},
                             "T-junction must not join endpoint-only component at %s" % tolerance)

    def test_tiny_nonzero_endpoint_pair_kept_for_diagnostics_only(self):
        # Two endpoints with tiny nonzero projected separation (<= EPS, ~8e-10 m)
        # that the canonical WGS84 exact mapping cannot reconstruct (they are
        # WGS84-distinct). They must be ABSENT from the proximity detail lists,
        # but their edge must be kept for the component diagnostic with its TRUE
        # tiny distance: it connects at tolerances >= its distance (1/5/10 m)
        # but NOT at 0 m (0 m uses only exactly-coincident endpoints, matching
        # the endpoint-node model).
        data = _normalized([
            ("A", [(134.389506401751, 33.65104139415405), (134.4, 33.65)]),
            ("B", [(134.389506401751, 33.65104139415404), (134.41, 33.66)]),
        ])
        inv = topology.build_inventory(data)
        self.assertEqual(_ids(inv["exact_connections"], "shared_endpoints"), [])
        pairs = inv["proximity_candidates"]["endpoint_pairs"]
        self.assertNotIn(("A", "B"),
                         {(r["route_a"], r["route_b"]) for r in pairs["<=5m"]})
        self.assertNotIn(("A", "B"),
                         {(r["route_a"], r["route_b"]) for r in pairs["5-20m"]})
        tols = inv["diagnostic_components"]["tolerances"]
        self.assertEqual(tols["0m"]["component_count"], 2)   # not connected at 0 m
        self.assertEqual(tols["1m"]["component_count"], 1)   # connected at 1 m
        self.assertEqual(tols["5m"]["component_count"], 1)
        self.assertEqual(tols["10m"]["component_count"], 1)

    def test_exact_endpoint_overrides_nonzero_endpoint_pair(self):
        # A route pair with one exact endpoint match AND another nonzero
        # endpoint pair must use the exact zero and connect at 0 m (bug 2 fix).
        data = _normalized([
            ("A", [at(0, 0), at(100, 0)]),
            ("B", [at(0, 0), at(100, 3)]),     # shared start exactly; ends 3 m apart
        ])
        inv = topology.build_inventory(data)
        # exact shared endpoint is detected...
        self.assertEqual(_ids(inv["exact_connections"], "shared_endpoints"), [("A", "B")])
        # ...and overrides the 3 m endpoint pair, connecting at 0 m.
        for tolerance in ("0m", "1m", "5m", "10m"):
            self.assertEqual(inv["diagnostic_components"]["tolerances"][tolerance]
                             ["component_count"], 1,
                             "exact endpoint must connect pair at %s" % tolerance)

    def test_endpoint_only_component_stats(self):
        data = _normalized([
            ("L1", [at(0, 0), at(100, 0)]),
            ("L2", [at(100, 0), at(200, 0)]),     # exact share with L1
            ("L3", [at(0, 0), at(0, 100)]),       # exact share start with L1
            ("L4", [at(300, 0), at(400, 0)]),     # isolated
            ("L5", [at(3, 0), at(103, 0)]),       # 3 m from L1/L3 starts
        ])
        inv = topology.build_inventory(data)
        tols = inv["diagnostic_components"]["tolerances"]
        # 0m: only exact endpoint pairs -> {L1,L2,L3}, {L4}, {L5}
        self.assertEqual(tols["0m"], {"component_count": 3, "largest_component_lines": 3,
                                      "isolated_lines": 2})
        # 1m: same as 0m (3 m gap too far)
        self.assertEqual(tols["1m"]["component_count"], 3)
        # 5m: L5 joins via 3 m endpoint pair -> {L1,L2,L3,L5}, {L4}
        self.assertEqual(tols["5m"], {"component_count": 2, "largest_component_lines": 4,
                                      "isolated_lines": 1})
        self.assertEqual(tols["10m"], tols["5m"])


class TestDeterminismAndFailure(unittest.TestCase):
    def _fixture(self):
        return _normalized([
            ("A", [at(0, 0), at(100, 0)]),
            ("B", [at(0, 0), at(0, 100)]),
            ("C", [at(200, 0), at(300, 0), at(400, 0)]),
            ("D", [at(300, 0), at(300, 60)]),
            ("E", [at(3, 3), at(3, 50)]),
            ("F", [at(50, -20), at(50, 20)]),
        ])

    def test_byte_identical_repeated_runs(self):
        data = self._fixture()
        first = json.dumps(topology.build_inventory(data), sort_keys=True)
        second = json.dumps(topology.build_inventory(data), sort_keys=True)
        self.assertEqual(first, second)

    def test_deterministic_list_ordering(self):
        data = self._fixture()
        inv = topology.build_inventory(data)
        exact = inv["exact_connections"]["shared_endpoints"]
        keys = [(tuple(r["coordinates"]), r["route_a"], r["route_b"]) for r in exact]
        self.assertEqual(keys, sorted(keys))
        self.assertNotIn("timestamp", json.dumps(inv))

    def test_negative_timestamp_absent(self):
        self.assertNotIn("timestamp", json.dumps(topology.build_inventory(self._fixture())))

    def test_schema_version_is_one(self):
        self.assertEqual(topology.build_inventory(self._fixture())["schema_version"], 1)

    def test_route_sources_mapping(self):
        data = self._fixture()
        inv = topology.build_inventory(data)
        route_sources = inv["route_sources"]
        self.assertEqual(set(route_sources), {r["id"] for r in data["routes"]})
        for route_id, info in route_sources.items():
            self.assertEqual(info["prefecture"], "tokushima")
            self.assertEqual(info["source_file"], "t.kml")
            self.assertEqual(info["part"], 1)
            self.assertIn("source_fid", info)
        # deterministic: stable under re-run and sorted JSON
        self.assertEqual(route_sources,
                         topology.build_inventory(data)["route_sources"])
        self.assertIn("route_sources", json.dumps(inv))

    def test_source_accounting_mismatch_fails(self):
        data = self._fixture()
        data["accounting"]["linestrings"] += 1  # deliberately wrong
        with self.assertRaisesRegex(ValueError, "source accounting mismatch"):
            topology.build_inventory(data)
        data = self._fixture()
        data["accounting"]["points"] += 1
        with self.assertRaisesRegex(ValueError, "source accounting mismatch"):
            topology.build_inventory(data)

    def test_source_accounting_validated_fields_preserved(self):
        inv = topology.build_inventory(self._fixture())
        validated = inv["analysis_accounting"]["source_accounting_validated"]
        self.assertEqual(validated, {"route_records_match": True,
                                     "source_points_match": True, "validated": True})

    def test_degenerate_line_fails(self):
        data = _normalized([("X", [at(0, 0), at(0, 0)])])
        with self.assertRaisesRegex(ValueError, "degenerate"):
            topology.build_inventory(data)

    def test_malformed_schema_fails(self):
        with self.assertRaisesRegex(ValueError, "required key"):
            topology.build_inventory({"schema_version": 1})
        partial = {"schema_version": 1, "dataset_id": "x", "snapshot_sha256": "x",
                   "accounting": {}}
        with self.assertRaisesRegex(ValueError, "routes"):
            topology.build_inventory(partial)
        with self.assertRaisesRegex(ValueError, "routes"):
            topology.build_inventory(dict(partial, routes="not-a-list"))

    def test_atomic_failure_preserves_prior_output(self):
        data_dir = tempfile.mkdtemp()
        bad_input = os.path.join(data_dir, "bad.json")
        with open(bad_input, "w", encoding="utf-8") as stream:
            json.dump(_normalized([("X", [at(0, 0), at(0, 0)])]), stream)  # degenerate
        output = os.path.join(data_dir, "out.json")
        with open(output, "w", encoding="utf-8") as stream:
            stream.write("SENTINEL")
        with self.assertRaises(ValueError):
            topology.run_inventory(bad_input, output)
        with open(output, encoding="utf-8") as stream:
            self.assertEqual(stream.read(), "SENTINEL")

    def test_successful_write_is_atomic_and_well_formed(self):
        data_dir = tempfile.mkdtemp()
        good_input = os.path.join(data_dir, "good.json")
        with open(good_input, "w", encoding="utf-8") as stream:
            json.dump(self._fixture(), stream)
        output = os.path.join(data_dir, "out.json")
        result = topology.run_inventory(good_input, output)
        self.assertEqual(result["kind"], "topology_inventory")
        with open(output, encoding="utf-8") as stream:
            loaded = json.load(stream)
        self.assertEqual(loaded["snapshot_sha256"], result["snapshot_sha256"])
        self.assertFalse(os.path.exists(output + ".tmp"))


if __name__ == "__main__":
    unittest.main()