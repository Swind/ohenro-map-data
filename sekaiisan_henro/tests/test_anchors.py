import json
import unittest

from sekaiisan_henro import anchors, graph, proximity, topology
from sekaiisan_henro.projection import LAT0, LON0, project_point, unproject_point

BASE = (LON0, LAT0)


def at(dx, dy):
    """Return a (lon, lat) coordinate dx m east / dy m north of BASE."""
    x0, y0 = project_point(*BASE)
    return unproject_point(x0 + dx, y0 + dy)


def _normalized(routes, temples, snapshot="aa" * 32):
    records = []
    for route_id, coords in routes:
        records.append({
            "id": route_id, "prefecture": "tokushima", "source_file": "t.kml",
            "source_fid": route_id, "part": 1,
            "source_identity": route_id, "source_identity_kind": "fid",
            "geometry": {"type": "LineString", "coordinates": list(coords)},
        })
    temple_records = []
    for number, coord in temples:
        temple_records.append({
            "id": "TEMPLE_%d" % number, "number": number,
            "name_jp": "寺%d" % number,
            "geometry": {"type": "Point", "coordinates": list(coord)},
            "source_file": "temple.kml",
        })
    return {
        "schema_version": 1,
        "dataset_id": "88sekaiisan-henro",
        "snapshot_sha256": snapshot,
        "routes": records,
        "temples": temple_records,
        "accounting": {
            "routes": len(routes), "linestrings": len(routes),
            "points": sum(len(coords) for _, coords in routes),
            "temples": len(temple_records), "missing_source_fid": 0,
            "by_prefecture": {},
        },
    }


def _full_temples(temples):
    """Pad the given (number, coord) specs to all 88 temples, others far away."""
    by_number = {n: at(100000, 100000) for n in range(1, 89)}
    for number, coord in temples:
        by_number[number] = coord
    return sorted(by_number.items())


def _prox_pipeline(routes, temples):
    """Build normalized (88 temples) + inventory + exact + proximity graph."""
    data = _normalized(routes, _full_temples(temples))
    inv = topology.build_inventory(data)
    exact = graph.build_graph(data, inv)
    prox = proximity.build_proximity_graph(exact, inv, data)
    return data, prox


def _anchors(routes, temples):
    data, prox = _prox_pipeline(routes, temples)
    return anchors.build_anchors_graph(prox, data), prox


def _edge_by_id(result, route_id):
    return {e["id"]: e for e in result["edges"]
            if e["provenance"]["route_id"] == route_id}


def _traversal_for_route(result, route_id):
    return [te for te in result["traversal_edges"]
            if te["provenance"]["route_id"] == route_id]


class TestUniqueNearProjectionAndSplit(unittest.TestCase):
    def test_near_anchor_splits_edge_into_two(self):
        # A spans x=0..200 along y=0; temple at (100,10) is 10m away -> near.
        result, _ = _anchors(
            [("A", [at(0, 0), at(200, 0)])],
            [(1, at(100, 10))])
        record = result["temple_anchors"][0]
        self.assertEqual(record["confidence"], "near")
        self.assertEqual(record["status"], "near")
        self.assertTrue(record["usable_for_routing"])
        self.assertEqual(record["chosen_edge_id"],
                         list(_edge_by_id(result, "A"))[0])
        self.assertAlmostEqual(record["distance_m"], 10.0, places=3)
        # projection is on the line at (100,0)
        self.assertAlmostEqual(record["projected_coordinates"][0],
                               at(100, 0)[0], places=3)
        # the edge is split into two traversal edges
        t_edges = _traversal_for_route(result, "A")
        self.assertEqual(len(t_edges), 2)
        # lengths sum to the source edge length within tolerance
        source_len = list(_edge_by_id(result, "A").values())[0]["length_m"]
        self.assertAlmostEqual(sum(te["length_m"] for te in t_edges),
                               source_len, places=3)
        # anchor node present and in traversal nodes
        self.assertIsNotNone(record["anchor_node_id"])
        self.assertIn(record["anchor_node_id"], result["traversal_nodes"])


class TestOffsetConfidence(unittest.TestCase):
    def test_offset_anchor_usable(self):
        # A spans x=0..200 along y=0; temple at (100,100) is 100m away -> offset.
        result, _ = _anchors(
            [("A", [at(0, 0), at(200, 0)])],
            [(1, at(100, 100))])
        record = result["temple_anchors"][0]
        self.assertEqual(record["confidence"], "offset")
        self.assertTrue(record["usable_for_routing"])
        self.assertAlmostEqual(record["distance_m"], 100.0, places=3)


class TestReviewExclusionOver150(unittest.TestCase):
    def test_unique_over_150_keeps_anchor_but_excludes_from_traversal(self):
        # Temple at (100,200) is 200m away -> unique, review_required.
        result, _ = _anchors(
            [("A", [at(0, 0), at(200, 0)])],
            [(1, at(100, 200))])
        record = result["temple_anchors"][0]
        self.assertEqual(record["confidence"], "review_required")
        self.assertEqual(record["status"], "review_required")
        self.assertFalse(record["usable_for_routing"])
        # retains projection + anchor node for audit
        self.assertIsNotNone(record["anchor_node_id"])
        self.assertEqual(record["chosen_edge_id"],
                         list(_edge_by_id(result, "A"))[0])
        self.assertAlmostEqual(record["distance_m"], 200.0, places=3)
        # but is NOT inserted into traversal topology (edge stays unsplit)
        t_edges = _traversal_for_route(result, "A")
        self.assertEqual(len(t_edges), 1)
        self.assertNotIn(record["anchor_node_id"], result["traversal_nodes"])


class TestUsableEndpointProjection(unittest.TestCase):
    def test_endpoint_projection_reuses_source_node(self):
        # A spans x=0..200 along y=0. Temple at (0,-5) projects exactly onto A's
        # start endpoint (measure 0) -> the anchor is the existing source node.
        result, _ = _anchors(
            [("A", [at(0, 0), at(200, 0)])],
            [(1, at(0, -5))])
        record = result["temple_anchors"][0]
        a_edge = list(_edge_by_id(result, "A").values())[0]
        self.assertEqual(record["confidence"], "near")
        self.assertTrue(record["usable_for_routing"])
        # anchor_node_id is the existing source endpoint node, not a new SHA_
        self.assertEqual(record["anchor_node_id"], a_edge["from"])
        self.assertNotIn(a_edge["from"], [n["id"] for n in result["anchor_nodes"]])
        # temple 1 created NO detached anchor node
        self.assertNotIn(1, [n["temple_number"] for n in result["anchor_nodes"]])
        # the usable anchor node belongs to traversal
        self.assertIn(record["anchor_node_id"], result["traversal_nodes"])
        # no zero-length edge: A stays a single traversal edge
        t_edges = _traversal_for_route(result, "A")
        self.assertEqual(len(t_edges), 1)
        self.assertTrue(all(te["length_m"] > 0 for te in t_edges))

    def test_endpoint_projection_at_to_node(self):
        # Temple at (200,-5) projects exactly onto A's end endpoint.
        result, _ = _anchors(
            [("A", [at(0, 0), at(200, 0)])],
            [(1, at(200, -5))])
        record = result["temple_anchors"][0]
        a_edge = list(_edge_by_id(result, "A").values())[0]
        self.assertTrue(record["usable_for_routing"])
        self.assertEqual(record["anchor_node_id"], a_edge["to"])
        self.assertIn(record["anchor_node_id"], result["traversal_nodes"])
        self.assertEqual(len(_traversal_for_route(result, "A")), 1)


class TestUsableAnchorInvariant(unittest.TestCase):
    def test_all_usable_anchor_nodes_in_traversal(self):
        # Temples at an interior point (100,5), a start endpoint (0,-5) and an
        # end endpoint (200,5); every usable anchor must resolve to a traversal
        # node (interior SHA_ or reused source endpoint).
        result, _ = _anchors(
            [("A", [at(0, 0), at(300, 0)])],
            [(1, at(100, 5)), (2, at(0, -5)), (3, at(300, 5))])
        traversal_nodes = set(result["traversal_nodes"])
        usable = [t for t in result["temple_anchors"] if t["usable_for_routing"]]
        self.assertEqual(len(usable), 3)
        for rec in usable:
            self.assertIn(rec["anchor_node_id"], traversal_nodes)
        # source nodes are unchanged (endpoint reuse never duplicates them)
        self.assertEqual(len([n for n in result["nodes"]
                              if n["id"].startswith("SHA_")]), 0)
        # no zero-length traversal edges anywhere
        self.assertTrue(all(te["length_m"] > 0
                            for te in result["traversal_edges"]))


class TestTiedNearestAmbiguity(unittest.TestCase):
    def test_tied_nearest_is_review_required_with_no_anchor(self):
        # Two parallel edges A (y=0) and B (y=10); temple at (100,5) is 5m from
        # both -> tied -> review_required, no usable anchor, lists both edges.
        result, _ = _anchors(
            [("A", [at(0, 0), at(200, 0)]),
             ("B", [at(0, 10), at(200, 10)])],
            [(1, at(100, 5))])
        record = result["temple_anchors"][0]
        self.assertEqual(record["confidence"], "review_required")
        self.assertFalse(record["usable_for_routing"])
        self.assertEqual(len(record["candidate_edge_ids"]), 2)
        self.assertNotIn("chosen_edge_id", record)
        self.assertNotIn("anchor_node_id", record)
        # neither candidate edge is split by this review-required anchor
        for eid in record["candidate_edge_ids"]:
            self.assertNotIn("SHA_", [te["from"] for te in result["traversal_edges"]
                                      if te["source_edge_id"] == eid])


class TestSharedNodeTieResolution(unittest.TestCase):
    def _shared_node(self, result):
        """Find the node shared by route A's end and route B's start."""
        a = list(_edge_by_id(result, "A").values())[0]
        b = list(_edge_by_id(result, "B").values())[0]
        shared = set((a["from"], a["to"])) & set((b["from"], b["to"]))
        self.assertEqual(len(shared), 1)
        return next(iter(shared))

    def test_two_candidates_meeting_at_node_resolve_usable(self):
        # A = x:0..100, B = x:100..200 sharing the exact node at (100,0).
        # Temple at (100,5) is 5m from both and both projections land on the
        # shared node -> a single unambiguous shared-node tie.
        result, _ = _anchors(
            [("A", [at(0, 0), at(100, 0)]),
             ("B", [at(100, 0), at(200, 0)])],
            [(1, at(100, 5))])
        record = result["temple_anchors"][0]
        shared = self._shared_node(result)
        self.assertEqual(record["confidence"], "near")
        self.assertEqual(record["status"], "near")
        self.assertTrue(record["usable_for_routing"])
        self.assertEqual(len(record["candidate_edge_ids"]), 2)
        self.assertEqual(record["resolution"], "shared_node_tie")
        self.assertEqual(record["resolved_edge_ids"], record["candidate_edge_ids"])
        # the existing shared source node is reused, NOT a new SHA_ node
        self.assertEqual(record["anchor_node_id"], shared)
        self.assertIn(shared, [n["id"] for n in result["nodes"]])
        self.assertNotIn(shared, [n["id"] for n in result["anchor_nodes"]])
        # projected coordinate is the shared node coordinate
        node = next(n for n in result["nodes"] if n["id"] == shared)
        self.assertEqual(record["projected_coordinates"], node["coordinates"])
        # no chosen edge, no singular measure
        self.assertNotIn("chosen_edge_id", record)
        self.assertNotIn("measure_m", record)
        # no new SHA_ anchor node was fabricated
        self.assertNotIn(1, [n["temple_number"] for n in result["anchor_nodes"]])
        # usable anchor node is in the traversal topology
        self.assertIn(shared, result["traversal_nodes"])
        # neither edge is split (the node is already an existing junction)
        self.assertEqual(len(_traversal_for_route(result, "A")), 1)
        self.assertEqual(len(_traversal_for_route(result, "B")), 1)
        # no zero-length traversal edges anywhere
        self.assertTrue(all(te["length_m"] > 0 for te in result["traversal_edges"]))

    def test_candidates_share_node_but_interior_projections_remain_review(self):
        # A = x:0..100, B = x:100 vertical (0..100). They share node (100,0).
        # Temple at (50,50) is 50m from both but projects onto A's interior
        # (50,0) and B's interior (100,50) -- NOT the shared node -> review.
        result, _ = _anchors(
            [("A", [at(0, 0), at(100, 0)]),
             ("B", [at(100, 0), at(100, 100)])],
            [(1, at(50, 50))])
        record = result["temple_anchors"][0]
        self.assertEqual(record["confidence"], "review_required")
        self.assertEqual(record["status"], "review_required")
        self.assertFalse(record["usable_for_routing"])
        self.assertEqual(len(record["candidate_edge_ids"]), 2)
        # no node/projection selection was made
        self.assertNotIn("anchor_node_id", record)
        self.assertNotIn("projected_coordinates", record)
        self.assertNotIn("resolution", record)

    def test_three_incident_candidates_all_same_node_deterministic(self):
        # A=(100,0), B=(0,100), C=(-100,0) all start at the shared node (0,0).
        # Temple at (0,0) is distance 0 from all three; all project to the node.
        result, _ = _anchors(
            [("A", [at(0, 0), at(100, 0)]),
             ("B", [at(0, 0), at(0, 100)]),
             ("C", [at(0, 0), at(-100, 0)])],
            [(1, at(0, 0))])
        record = result["temple_anchors"][0]
        self.assertEqual(record["confidence"], "near")
        self.assertTrue(record["usable_for_routing"])
        self.assertEqual(record["resolution"], "shared_node_tie")
        self.assertEqual(len(record["candidate_edge_ids"]), 3)
        # deterministic: candidates and resolved list are sorted and identical
        self.assertEqual(record["candidate_edge_ids"],
                         sorted(record["candidate_edge_ids"]))
        self.assertEqual(record["resolved_edge_ids"], record["candidate_edge_ids"])
        # every candidate edge is incident to the shared anchor node
        shared = record["anchor_node_id"]
        edge_by_id = {e["id"]: e for e in result["edges"]}
        for eid in record["candidate_edge_ids"]:
            self.assertIn(shared, (edge_by_id[eid]["from"], edge_by_id[eid]["to"]))
        self.assertIn(shared, result["traversal_nodes"])

    def test_shared_node_tie_over_150_remains_review_but_keeps_audit_location(self):
        # Temple at (100,200) is 200m from both A and B (both project to the
        # shared node (100,0)) -> resolved shared-node tie, but >150m so it
        # retains the audit node/projection yet stays unusable.
        result, _ = _anchors(
            [("A", [at(0, 0), at(100, 0)]),
             ("B", [at(100, 0), at(200, 0)])],
            [(1, at(100, 200))])
        record = result["temple_anchors"][0]
        shared = self._shared_node(result)
        self.assertEqual(record["confidence"], "review_required")
        self.assertEqual(record["status"], "review_required")
        self.assertFalse(record["usable_for_routing"])
        self.assertEqual(record["resolution"], "shared_node_tie")
        # audit location/node retained
        self.assertEqual(record["anchor_node_id"], shared)
        self.assertIn("projected_coordinates", record)
        # not usable, so sections/corridors will treat it as review_required
        self.assertNotIn("chosen_edge_id", record)


class TestTempleCoordinatesUnchangedNoConnector(unittest.TestCase):
    def test_temple_point_preserved_and_no_offset_connector(self):
        result, _ = _anchors(
            [("A", [at(0, 0), at(200, 0)])],
            [(1, at(100, 10))])
        record = result["temple_anchors"][0]
        # original temple point preserved verbatim (the temple is not moved)
        self.assertEqual(record["coordinates"], list(at(100, 10)))
        # the temple-to-route offset line is never an edge: no synthetic join
        # was added and no edge references the temple point as an endpoint
        self.assertEqual(result["synthetic_joins"], [])
        all_edges = result["edges"] + result["traversal_edges"]
        temple_lonlat = tuple(record["coordinates"])
        for edge in all_edges:
            self.assertNotIn(temple_lonlat, edge["coordinates"])


class TestMultipleAnchorsOneEdge(unittest.TestCase):
    def test_two_near_anchors_split_edge_into_three(self):
        # A spans x=0..300; temples at (100,5) and (200,5) -> two near anchors.
        result, _ = _anchors(
            [("A", [at(0, 0), at(300, 0)])],
            [(1, at(100, 5)), (2, at(200, 5))])
        t_edges = _traversal_for_route(result, "A")
        self.assertEqual(len(t_edges), 3)
        source_len = list(_edge_by_id(result, "A").values())[0]["length_m"]
        self.assertAlmostEqual(sum(te["length_m"] for te in t_edges),
                               source_len, places=3)
        # both near temples get usable anchor nodes in the traversal
        anchors = {t["temple_number"]: t for t in result["temple_anchors"]}
        self.assertTrue(anchors[1]["usable_for_routing"])
        self.assertTrue(anchors[2]["usable_for_routing"])
        self.assertIn(anchors[1]["anchor_node_id"], result["traversal_nodes"])
        self.assertIn(anchors[2]["anchor_node_id"], result["traversal_nodes"])


class TestSyntheticTAttachmentIncluded(unittest.TestCase):
    def test_synthetic_t_node_splits_edge_with_anchor(self):
        # Y spans x=0..200 along y=0. X.start (100,4) is 4m from Y interior ->
        # proximity creates a synthetic T node attached to Y. Temple at (150,5)
        # is a near anchor on Y. Y should be split at the T node AND the anchor
        # -> 3 traversal edges, and the T node is in traversal connectivity.
        result, prox = _anchors(
            [("Y", [at(0, 0), at(200, 0)]),
             ("X", [at(100, 4), at(100, 40)])],
            [(1, at(150, 5))])
        # proximity built exactly one synthetic T join
        self.assertEqual(prox["accounting"]["synthetic_joins"], 1)
        self.assertEqual(prox["accounting"]["synthetic_nodes"], 1)
        syn_node = result["synthetic_nodes"][0]
        self.assertIn("synthetic_t", syn_node["kinds"])
        # the synthetic T node is attached to Y and is a traversal node
        self.assertEqual(syn_node["attached"]["route_id"], "Y")
        self.assertIn(syn_node["id"], result["traversal_nodes"])
        # Y is split into 3 traversal edges (T node + anchor + 2 gaps)
        t_edges = _traversal_for_route(result, "Y")
        self.assertEqual(len(t_edges), 3)
        source_len = list(_edge_by_id(result, "Y").values())[0]["length_m"]
        self.assertAlmostEqual(sum(te["length_m"] for te in t_edges),
                               source_len, places=3)
        # the synthetic join is preserved value-identically
        self.assertEqual(result["synthetic_joins"], prox["synthetic_joins"])


class TestSourcePreservation(unittest.TestCase):
    def test_source_geometry_and_lengths_preserved(self):
        routes = [("A", [at(0, 0), at(200, 0)])]
        temples = [(1, at(100, 10))]
        result, prox = _anchors(routes, temples)
        self.assertEqual(result["nodes"], prox["nodes"])
        self.assertEqual(result["edges"], prox["edges"])
        self.assertEqual(result["synthetic_nodes"], prox["synthetic_nodes"])
        self.assertEqual(result["synthetic_joins"], prox["synthetic_joins"])
        self.assertEqual(result["route_sources"], prox["route_sources"])
        self.assertEqual(result["components_before"], prox["components"])
        self.assertEqual(result["accounting"]["lengths"],
                         prox["accounting"]["lengths"])
        self.assertEqual(result["kind"], "anchored_route_graph")


class TestComponentCountUnchanged(unittest.TestCase):
    def test_component_count_identical_before_after(self):
        result, prox = _anchors(
            [("A", [at(0, 0), at(300, 0)]),
             ("B", [at(0, 5), at(300, 5)])],
            [(1, at(100, 2)), (2, at(200, 2))])
        acct = result["accounting"]
        # anchoring only subdivides edges, so component count is unchanged
        self.assertEqual(acct["components_before"], acct["components_after"])
        self.assertEqual(acct["components_before"], len(prox["components"]))


class TestDeterminism(unittest.TestCase):
    def test_byte_determinism(self):
        routes = [("A", [at(0, 0), at(200, 0)]),
                  ("B", [at(100, 4), at(100, 40)])]
        temples = [(1, at(150, 5))]
        data, prox = _prox_pipeline(routes, temples)
        first = json.dumps(anchors.build_anchors_graph(prox, data), sort_keys=True)
        second = json.dumps(anchors.build_anchors_graph(prox, data), sort_keys=True)
        self.assertEqual(first, second)
        self.assertIn('"kind": "anchored_route_graph"', first)
        self.assertIn('"id": "SHA_', first)
        self.assertIn('"id": "STE_', first)
        self.assertNotIn("timestamp", first)


class TestValidation(unittest.TestCase):
    def _data(self):
        return _normalized([("A", [at(0, 0), at(200, 0)])], _full_temples([(1, at(100, 10))]))

    def test_graph_kind_required(self):
        data = self._data()
        inv = topology.build_inventory(data)
        exact = graph.build_graph(data, inv)
        prox = proximity.build_proximity_graph(exact, inv, data)
        prox["kind"] = "not_proximity_route_graph"
        with self.assertRaisesRegex(ValueError, "proximity_route_graph"):
            anchors.build_anchors_graph(prox, data)

    def test_snapshot_mismatch_fails(self):
        data = self._data()
        inv = topology.build_inventory(data)
        exact = graph.build_graph(data, inv)
        prox = proximity.build_proximity_graph(exact, inv, data)
        data["snapshot_sha256"] = "bb" * 32
        with self.assertRaisesRegex(ValueError, "snapshot mismatch"):
            anchors.build_anchors_graph(prox, data)

    def test_missing_temple_fails(self):
        data = self._data()
        inv = topology.build_inventory(data)
        exact = graph.build_graph(data, inv)
        prox = proximity.build_proximity_graph(exact, inv, data)
        data["temples"] = []
        with self.assertRaisesRegex(ValueError, "temple numbers missing"):
            anchors.build_anchors_graph(prox, data)


if __name__ == "__main__":
    unittest.main()