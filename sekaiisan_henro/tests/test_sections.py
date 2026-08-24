import json
import unittest

from sekaiisan_henro import sections


def _anchored(traversal_edges, synthetic_joins, usable):
    """Minimal anchored_route_graph fixture.

    ``traversal_edges`` / ``synthetic_joins`` are lists of edge dicts (with
    ``from``/``to``/``id`` and a weight). ``usable`` maps a temple number to the
    anchor node id it routes from; all other temples are review_required.
    """
    node_ids = set()
    for te in traversal_edges:
        node_ids.add(te["from"])
        node_ids.add(te["to"])
    for join in synthetic_joins:
        node_ids.add(join["from"])
        node_ids.add(join["to"])
    for nid in usable.values():
        node_ids.add(nid)
    nodes = [{
        "id": nid, "lon": 0.0, "lat": 0.0, "coordinates": [0.0, 0.0],
        "kinds": [], "source_refs": [],
    } for nid in sorted(node_ids)]
    temple_anchors = []
    for number in range(1, 89):
        if number in usable:
            temple_anchors.append({
                "temple_number": number, "temple_id": "TEMPLE_%d" % number,
                "confidence": "near", "status": "near",
                "usable_for_routing": True, "distance_m": 5.0,
                "anchor_node_id": usable[number],
            })
        else:
            temple_anchors.append({
                "temple_number": number, "temple_id": "TEMPLE_%d" % number,
                "confidence": "review_required", "status": "review_required",
                "usable_for_routing": False, "distance_m": 200.0,
            })
    return {
        "schema_version": 1,
        "kind": "anchored_route_graph",
        "dataset_id": "88sekaiisan-henro",
        "snapshot_sha256": "aa" * 32,
        "projection": {"kind": "equirectangular", "R": 6371008.8,
                       "lon0": 133.75, "lat0": 33.65},
        "limitation": "test fixture",
        "note": "test fixture",
        "nodes": nodes,
        "synthetic_nodes": [],
        "anchor_nodes": [],
        "edges": [],
        "synthetic_joins": synthetic_joins,
        "temple_anchors": temple_anchors,
        "traversal_edges": traversal_edges,
        "components": [],
        "accounting": {},
    }


def _te(eid, a, b, length):
    return {"id": eid, "from": a, "to": b, "length_m": length,
            "coordinates": [], "source_edge_id": "SHE_x", "provenance": {}}


def _join(jid, a, b, distance):
    return {"id": jid, "from": a, "to": b, "distance_m": distance}


def _section(result, i):
    return next(s for s in result["sections"] if s["id"] == "SEC_%d_%d" % (i, i + 1))


class TestUniqueShortestPathAndDirection(unittest.TestCase):
    def test_single_path_forward(self):
        edges = [_te("e1", "A", "B", 10.0), _te("e2", "B", "C", 20.0)]
        result = sections.build_sections(_anchored(edges, [], {1: "A", 2: "C"}))
        sec = _section(result, 1)
        self.assertEqual(sec["status"], "candidate")
        self.assertEqual(sec["primary"]["edge_ids"], ["e1", "e2"])
        self.assertEqual(sec["primary"]["directions"], ["forward", "forward"])
        self.assertAlmostEqual(sec["primary"]["length_m"], 30.0, places=6)
        self.assertNotIn("alternative", sec)

    def test_reverse_direction_recorded(self):
        # e1 stored B->A so traversing A->B is reverse; e2 stored B->C forward.
        edges = [_te("e1", "B", "A", 10.0), _te("e2", "B", "C", 20.0)]
        result = sections.build_sections(_anchored(edges, [], {1: "A", 2: "C"}))
        sec = _section(result, 1)
        self.assertEqual(sec["primary"]["edge_ids"], ["e1", "e2"])
        self.assertEqual(sec["primary"]["directions"], ["reverse", "forward"])
        self.assertAlmostEqual(sec["primary"]["length_m"], 30.0, places=6)


class TestDisconnected(unittest.TestCase):
    def test_different_components_no_path(self):
        edges = [_te("e1", "A", "B", 10.0), _te("e2", "C", "D", 10.0)]
        result = sections.build_sections(_anchored(edges, [], {1: "A", 2: "C"}))
        sec = _section(result, 1)
        self.assertEqual(sec["status"], "disconnected")
        self.assertNotIn("primary", sec)
        self.assertNotIn("alternative", sec)


class TestReviewRequired(unittest.TestCase):
    def test_unusable_anchor_skips_inference(self):
        edges = [_te("e1", "A", "B", 10.0)]
        result = sections.build_sections(_anchored(edges, [], {1: "A"}))
        sec = _section(result, 1)  # temple 2 is review_required
        self.assertEqual(sec["status"], "anchor_review_required")
        self.assertNotIn("primary", sec)
        self.assertEqual(sec["anchors"]["to"]["usable_for_routing"], False)


class TestReplacementWithinThresholdAmbiguous(unittest.TestCase):
    def test_near_equal_alternative_kept(self):
        # Primary A->B->C = 20; alternative A->D->C = 21 (ratio 1.05 <= 1.15).
        edges = [
            _te("ab", "A", "B", 10.0), _te("bc", "B", "C", 10.0),
            _te("ad", "A", "D", 20.0), _te("dc", "D", "C", 1.0),
        ]
        result = sections.build_sections(_anchored(edges, [], {1: "A", 2: "C"}))
        sec = _section(result, 1)
        self.assertEqual(sec["status"], "ambiguous")
        self.assertEqual(sec["primary"]["edge_ids"], ["ab", "bc"])
        self.assertAlmostEqual(sec["primary"]["length_m"], 20.0, places=6)
        self.assertEqual(sec["alternative"]["edge_ids"], ["ad", "dc"])
        self.assertAlmostEqual(sec["alternative"]["length_m"], 21.0, places=6)
        self.assertIn("diagnostics", sec)
        self.assertAlmostEqual(sec["diagnostics"]["alternative_to_primary_ratio"],
                               1.05, places=6)


class TestReplacementOverThresholdStaysCandidate(unittest.TestCase):
    def test_long_alternative_kept_out(self):
        # Primary A->B->C = 20; alternative A->D->C = 200 (ratio 10 > 1.15).
        edges = [
            _te("ab", "A", "B", 10.0), _te("bc", "B", "C", 10.0),
            _te("ad", "A", "D", 100.0), _te("dc", "D", "C", 100.0),
        ]
        result = sections.build_sections(_anchored(edges, [], {1: "A", 2: "C"}))
        sec = _section(result, 1)
        self.assertEqual(sec["status"], "candidate")
        self.assertEqual(sec["primary"]["edge_ids"], ["ab", "bc"])
        self.assertNotIn("alternative", sec)
        # diagnostics still report the rejected alternative
        self.assertIn("diagnostics", sec)
        self.assertAlmostEqual(sec["diagnostics"]["best_rejected_alternative_length_m"],
                               200.0, places=6)


class TestNoReplacement(unittest.TestCase):
    def test_single_route_no_alternative(self):
        edges = [_te("e1", "A", "B", 10.0), _te("e2", "B", "C", 20.0)]
        result = sections.build_sections(_anchored(edges, [], {1: "A", 2: "C"}))
        sec = _section(result, 1)
        self.assertEqual(sec["status"], "candidate")
        self.assertNotIn("alternative", sec)
        self.assertNotIn("diagnostics", sec)


class TestSyntheticJoinPath(unittest.TestCase):
    def test_path_uses_synthetic_join(self):
        # Two traversal edges in separate pieces joined by a synthetic join.
        edges = [_te("e1", "A", "B", 5.0), _te("e2", "C", "D", 5.0)]
        joins = [_join("shj1", "B", "C", 0.0)]
        result = sections.build_sections(_anchored(edges, joins, {1: "A", 2: "D"}))
        sec = _section(result, 1)
        self.assertEqual(sec["status"], "candidate")
        self.assertEqual(sec["primary"]["edge_ids"], ["e1", "shj1", "e2"])
        self.assertEqual(sec["primary"]["directions"],
                         ["forward", "forward", "forward"])
        self.assertAlmostEqual(sec["primary"]["length_m"], 10.0, places=6)
        self.assertGreaterEqual(result["accounting"]["paths_using_synthetic_joins"], 1)


class TestSubEpsilonTieBreak(unittest.TestCase):
    def test_replacement_prefers_lexicographically_smaller_within_epsilon(self):
        # Primary A-B-C-Z = 300. Two replacement paths within _TIE_EPS of each
        # other: R1 = [a1,a2,e2,e3] w=310 (lexicographically smaller but
        # microscopically heavier) and R2 = [e1,e2,z1,z2] w=309.9999995 (lighter
        # but lexicographically larger). The replacement must pick R1 because
        # the deterministic ordering tie-breaks on the edge sequence.
        edges = [
            _te("e1", "A", "B", 100.0),
            _te("e2", "B", "C", 100.0),
            _te("e3", "C", "Z", 100.0),
            _te("a1", "A", "D", 55.0),
            _te("a2", "D", "B", 55.0),
            _te("z1", "C", "E", 54.9999995),
            _te("z2", "E", "Z", 55.0),
        ]
        result = sections.build_sections(_anchored(edges, [], {1: "A", 2: "Z"}))
        sec = _section(result, 1)
        self.assertEqual(sec["status"], "ambiguous")
        self.assertEqual(sec["primary"]["edge_ids"], ["e1", "e2", "e3"])
        # lexicographically smaller replacement (R1) wins despite being
        # microscopically heavier than R2.
        self.assertEqual(sec["alternative"]["edge_ids"], ["a1", "a2", "e2", "e3"])
        self.assertAlmostEqual(sec["alternative"]["length_m"], 310.0, places=3)
        diag = sec["diagnostics"]
        # accepted ambiguous diagnostics use alternative_length_m + ratio, not
        # the rejected-alternative key.
        self.assertIn("alternative_length_m", diag)
        self.assertAlmostEqual(diag["alternative_length_m"], 310.0, places=3)
        self.assertIn("alternative_to_primary_ratio", diag)
        self.assertNotIn("best_rejected_alternative_length_m", diag)


class TestDeterministicEqualCostTie(unittest.TestCase):
    def test_lexicographically_smallest_primary_selected(self):
        # Two equal-cost paths A->B1->C and A->B2->C, both 20m. The primary must
        # pick the lexicographically smallest edge sequence [ab1,b1c]; the other
        # becomes the equal-cost alternative -> ambiguous.
        edges = [
            _te("ab1", "A", "B1", 10.0), _te("b1c", "B1", "C", 10.0),
            _te("ab2", "A", "B2", 10.0), _te("b2c", "B2", "C", 10.0),
        ]
        result = sections.build_sections(_anchored(edges, [], {1: "A", 2: "C"}))
        sec = _section(result, 1)
        self.assertEqual(sec["status"], "ambiguous")
        self.assertEqual(sec["primary"]["edge_ids"], ["ab1", "b1c"])
        self.assertEqual(sec["alternative"]["edge_ids"], ["ab2", "b2c"])

    def test_byte_determinism(self):
        edges = [
            _te("ab1", "A", "B1", 10.0), _te("b1c", "B1", "C", 10.0),
            _te("ab2", "A", "B2", 10.0), _te("b2c", "B2", "C", 10.0),
        ]
        first = json.dumps(sections.build_sections(_anchored(edges, [], {1: "A", 2: "C"})),
                           sort_keys=True)
        second = json.dumps(sections.build_sections(_anchored(edges, [], {1: "A", 2: "C"})),
                            sort_keys=True)
        self.assertEqual(first, second)
        self.assertNotIn('"timestamp"', first)  # no actual timestamp field


class TestEightySevenSectionsAndClosure(unittest.TestCase):
    def test_exactly_87_and_closure(self):
        # A single connected chain of 88 nodes -> 87 candidate sections.
        edges = [_te("e%d" % i, "n%d" % i, "n%d" % (i + 1), 10.0)
                 for i in range(1, 88)]
        usable = {"n%d" % i: "n%d" % i for i in range(1, 89)}
        # build usable as temple_number -> node_id
        usable_by_temple = {i: "n%d" % i for i in range(1, 89)}
        result = sections.build_sections(_anchored(edges, [], usable_by_temple))
        self.assertEqual(result["kind"], "temple_sections")
        self.assertEqual(len(result["sections"]), 87)
        self.assertEqual([s["id"] for s in result["sections"]],
                         ["SEC_%d_%d" % (i, i + 1) for i in range(1, 88)])
        self.assertEqual(result["closure_88_1"], {"status": "not_requested"})
        acct = result["accounting"]
        self.assertEqual(acct["sections_total"], 87)
        self.assertEqual(sum(acct["by_status"].values()), 87)
        self.assertEqual(acct["by_status"]["candidate"], 87)
        self.assertEqual(acct["by_status"]["disconnected"], 0)
        self.assertEqual(acct["by_status"]["anchor_review_required"], 0)
        self.assertEqual(acct["by_status"]["ambiguous"], 0)
        # every section carries anchor summaries with temple numbers
        self.assertEqual([s["anchors"]["from"]["temple_number"] for s in result["sections"]],
                         list(range(1, 88)))
        self.assertEqual([s["anchors"]["to"]["temple_number"] for s in result["sections"]],
                         list(range(2, 89)))


class TestAnchorSummary(unittest.TestCase):
    def test_summary_fields_and_node_id(self):
        edges = [_te("e1", "A", "B", 10.0)]
        result = sections.build_sections(_anchored(edges, [], {1: "A", 2: "B"}))
        sec = _section(result, 1)
        frm = sec["anchors"]["from"]
        self.assertEqual(frm["temple_number"], 1)
        self.assertEqual(frm["confidence"], "near")
        self.assertEqual(frm["status"], "near")
        self.assertTrue(frm["usable_for_routing"])
        self.assertAlmostEqual(frm["distance_m"], 5.0, places=6)
        self.assertEqual(frm["node_id"], "A")


class TestValidation(unittest.TestCase):
    def _base(self):
        return _anchored([_te("e1", "A", "B", 10.0)], [], {1: "A", 2: "B"})

    def test_wrong_kind(self):
        data = self._base()
        data["kind"] = "not_anchored_route_graph"
        with self.assertRaisesRegex(ValueError, "anchored_route_graph"):
            sections.build_sections(data)

    def test_missing_temple_anchor(self):
        data = self._base()
        data["temple_anchors"] = data["temple_anchors"][:-1]
        with self.assertRaisesRegex(ValueError, "exactly 88 temple anchors"):
            sections.build_sections(data)

    def test_duplicate_temple_number(self):
        data = self._base()
        data["temple_anchors"][0]["temple_number"] = 2
        with self.assertRaisesRegex(ValueError, "duplicate temple anchor number"):
            sections.build_sections(data)

    def test_duplicate_edge_id(self):
        data = self._base()
        data["traversal_edges"].append(dict(data["traversal_edges"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate edge id"):
            sections.build_sections(data)

    def test_negative_weight(self):
        data = self._base()
        data["traversal_edges"][0]["length_m"] = -1.0
        with self.assertRaisesRegex(ValueError, "negative weight"):
            sections.build_sections(data)

    def test_nonfinite_weight(self):
        data = self._base()
        data["traversal_edges"][0]["length_m"] = float("inf")
        with self.assertRaisesRegex(ValueError, "non-finite"):
            sections.build_sections(data)

    def test_endpoint_not_in_universe(self):
        data = self._base()
        data["traversal_edges"][0]["to"] = "GHOST"
        with self.assertRaisesRegex(ValueError, "not in node universe"):
            sections.build_sections(data)

    def test_usable_anchor_without_valid_node(self):
        data = self._base()
        data["temple_anchors"][0]["anchor_node_id"] = "GHOST"
        with self.assertRaisesRegex(ValueError, "no valid anchor_node_id"):
            sections.build_sections(data)


if __name__ == "__main__":
    unittest.main()