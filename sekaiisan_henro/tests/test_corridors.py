import json
import unittest

from sekaiisan_henro import corridors


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


def _te(eid, a, b, length, source=None):
    return {"id": eid, "from": a, "to": b, "length_m": length,
            "coordinates": [[0.0, 0.0], [1.0, 1.0]],
            "source_edge_id": source or ("SHE_" + eid), "provenance": {}}


def _join(jid, a, b, distance):
    return {"id": jid, "from": a, "to": b, "distance_m": distance}


def _section(result, i):
    return next(s for s in result["sections"]
                if s["id"] == "SEC_%d_%d" % (i, i + 1))


def _edges_for(te_list, sj_list):
    """Flatten to [(eid, a, b)] for the oracle."""
    return [(e["id"], e["from"], e["to"]) for e in te_list] + \
           [(j["id"], j["from"], j["to"]) for j in sj_list]


def _oracle_union(edges, s, t, usable_other_nodes):
    """Brute-force reference: union of edge ids on any simple s-t path with
    every other usable anchor node removed (never s/t)."""
    forbidden = set(usable_other_nodes)
    adj = {}
    for eid, a, b in edges:
        if a in forbidden or b in forbidden:
            continue
        adj.setdefault(a, []).append((b, eid))
        adj.setdefault(b, []).append((a, eid))
    union = set()

    def dfs(node, path_edges, path_nodes):
        if node == t:
            union.update(path_edges)
            return
        for nb, eid in adj.get(node, ()):
            if nb in path_nodes:
                continue
            dfs(nb, path_edges + [eid], path_nodes + [nb])

    dfs(s, [], [s])
    return union


def _other_anchor_nodes(usable, i):
    """Node ids of all usable temples except i and i+1."""
    out = set()
    for k in range(1, 89):
        if k == i or k == i + 1:
            continue
        if k in usable:
            out.add(usable[k])
    return out


class TestSimpleChain(unittest.TestCase):
    def test_chain_is_corridor(self):
        edges = [_te("e1", "A", "B", 10.0), _te("e2", "B", "C", 20.0)]
        result = corridors.build_corridors(_anchored(edges, [], {1: "A", 2: "C"}))
        sec = _section(result, 1)
        self.assertEqual(sec["status"], "corridor")
        self.assertEqual(sec["edge_ids"], ["e1", "e2"])
        self.assertEqual(sec["cyclomatic_number"], 0)
        self.assertEqual(sec["traversal_edge_ids"], ["e1", "e2"])
        self.assertEqual(sec["synthetic_join_ids"], [])
        self.assertEqual(sec["node_ids"], ["A", "B", "C"])
        self.assertEqual(sec["edge_count"], 2)
        self.assertEqual(sec["node_count"], 3)
        self.assertEqual(sec["shortest"]["edge_ids"], ["e1", "e2"])
        self.assertEqual(sec["shortest"]["directions"], ["forward", "forward"])
        self.assertAlmostEqual(sec["shortest"]["length_m"], 30.0, places=6)


class TestDiamond(unittest.TestCase):
    def test_both_branches_included(self):
        # s=A, t=C; diamond A-B1-C and A-B2-C.
        edges = [
            _te("ab1", "A", "B1", 10.0), _te("b1c", "B1", "C", 10.0),
            _te("ab2", "A", "B2", 10.0), _te("b2c", "B2", "C", 10.0),
        ]
        result = corridors.build_corridors(_anchored(edges, [], {1: "A", 2: "C"}))
        sec = _section(result, 1)
        self.assertEqual(sec["status"], "branched_corridor")
        self.assertEqual(sec["cyclomatic_number"], 1)
        self.assertEqual(set(sec["edge_ids"]), {"ab1", "b1c", "ab2", "b2c"})
        # oracle agreement
        self.assertEqual(set(sec["edge_ids"]),
                         _oracle_union(_edges_for(edges, []), "A", "C",
                                       _other_anchor_nodes({1: "A", 2: "C"}, 1)))


class TestDeadEndExcluded(unittest.TestCase):
    def test_dead_end_branch_excluded(self):
        # s=A, t=B; dead end B-C-D.
        edges = [_te("ab", "A", "B", 10.0), _te("bc", "B", "C", 5.0),
                 _te("cd", "C", "D", 5.0)]
        result = corridors.build_corridors(_anchored(edges, [], {1: "A", 2: "B"}))
        sec = _section(result, 1)
        self.assertEqual(sec["status"], "corridor")
        self.assertEqual(sec["edge_ids"], ["ab"])
        self.assertEqual(_oracle_union(_edges_for(edges, []), "A", "B",
                                       _other_anchor_nodes({1: "A", 2: "B"}, 1)),
                         {"ab"})


class TestLollipopExcluded(unittest.TestCase):
    def test_cycle_attached_at_one_articulation_excluded(self):
        # s=A, t=B; a lollipop cycle B-C-D-B attached through articulation B.
        edges = [_te("ab", "A", "B", 10.0),
                 _te("bc", "B", "C", 5.0), _te("cd", "C", "D", 5.0),
                 _te("db", "D", "B", 5.0)]
        result = corridors.build_corridors(_anchored(edges, [], {1: "A", 2: "B"}))
        sec = _section(result, 1)
        self.assertEqual(sec["edge_ids"], ["ab"])
        self.assertEqual(_oracle_union(_edges_for(edges, []), "A", "B",
                                       _other_anchor_nodes({1: "A", 2: "B"}, 1)),
                         {"ab"})


class TestOppositeRingExcluded(unittest.TestCase):
    def test_opposite_ring_crosses_third_anchor(self):
        # Ring A-B, B-C, C-A; temple 3 sits at C. Section 1-2 (A->B) must NOT
        # include the opposite route A-C-B because C is a forbidden anchor.
        edges = [_te("ab", "A", "B", 10.0), _te("bc", "B", "C", 10.0),
                 _te("ca", "C", "A", 10.0)]
        result = corridors.build_corridors(
            _anchored(edges, [], {1: "A", 2: "B", 3: "C"}))
        sec = _section(result, 1)
        self.assertEqual(sec["edge_ids"], ["ab"])
        self.assertEqual(sec["excluded_other_anchor_node_ids"], ["C"])
        self.assertEqual(_oracle_union(_edges_for(edges, []), "A", "B", {"C"}),
                         {"ab"})


class TestLongBranchRetained(unittest.TestCase):
    def test_long_reconnecting_branch_retained(self):
        # s=A, t=B with a short path and a long reconnecting path. Both are on a
        # simple s-t path so both are retained regardless of length.
        edges = [_te("ab", "A", "B", 10.0), _te("ac", "A", "C", 1.0),
                 _te("cd", "C", "D", 1.0), _te("de", "D", "E", 1.0),
                 _te("ef", "E", "F", 1.0), _te("fg", "F", "G", 1.0),
                 _te("gb", "G", "B", 1.0)]
        result = corridors.build_corridors(_anchored(edges, [], {1: "A", 2: "B"}))
        sec = _section(result, 1)
        # long branch edges all retained
        self.assertTrue({"ac", "cd", "de", "ef", "fg", "gb"} <= set(sec["edge_ids"]))
        # it is one biconnected block -> branched
        self.assertEqual(sec["status"], "branched_corridor")
        self.assertEqual(set(sec["edge_ids"]),
                         _oracle_union(_edges_for(edges, []), "A", "B",
                                       _other_anchor_nodes({1: "A", 2: "B"}, 1)))


class TestDisconnected(unittest.TestCase):
    def test_different_components(self):
        edges = [_te("e1", "A", "B", 10.0), _te("e2", "C", "D", 10.0)]
        result = corridors.build_corridors(_anchored(edges, [], {1: "A", 2: "C"}))
        sec = _section(result, 1)
        self.assertEqual(sec["status"], "disconnected")
        self.assertEqual(sec["edge_ids"], [])
        self.assertIsNone(sec["shortest"])


class TestReviewRequired(unittest.TestCase):
    def test_unusable_anchor(self):
        edges = [_te("e1", "A", "B", 10.0)]
        result = corridors.build_corridors(_anchored(edges, [], {1: "A"}))
        sec = _section(result, 1)  # temple 2 unusable
        self.assertEqual(sec["status"], "anchor_review_required")
        self.assertEqual(sec["edge_ids"], [])
        self.assertIsNone(sec["shortest"])


class TestSyntheticJoin(unittest.TestCase):
    def test_synthetic_join_included(self):
        te = [_te("e1", "A", "B", 5.0), _te("e2", "C", "D", 5.0)]
        j = [_join("shj1", "B", "C", 0.0)]
        result = corridors.build_corridors(_anchored(te, j, {1: "A", 2: "D"}))
        sec = _section(result, 1)
        self.assertEqual(sec["status"], "corridor")
        self.assertEqual(sec["edge_ids"], ["e1", "e2", "shj1"])
        self.assertEqual(sec["synthetic_join_ids"], ["shj1"])
        self.assertEqual(sec["traversal_edge_ids"], ["e1", "e2"])
        self.assertEqual(sec["shortest"]["edge_ids"], ["e1", "shj1", "e2"])
        self.assertAlmostEqual(sec["shortest"]["length_m"], 10.0, places=6)


class TestParallelEdges(unittest.TestCase):
    def test_parallel_edges_both_in_block(self):
        # Two parallel edges between A and B form one biconnected block.
        edges = [_te("e1", "A", "B", 5.0), _te("e2", "A", "B", 7.0)]
        result = corridors.build_corridors(_anchored(edges, [], {1: "A", 2: "B"}))
        sec = _section(result, 1)
        self.assertEqual(sec["status"], "branched_corridor")
        self.assertEqual(set(sec["edge_ids"]), {"e1", "e2"})
        self.assertEqual(sec["cyclomatic_number"], 1)
        # both parallel edges are on some simple s-t path
        self.assertEqual(_oracle_union(_edges_for(edges, []), "A", "B", set()),
                         {"e1", "e2"})


class TestSameNode(unittest.TestCase):
    def test_s_equal_t_zero_edge_corridor(self):
        edges = [_te("e1", "A", "B", 10.0)]
        # temple 1 and temple 2 share anchor node A (usable).
        result = corridors.build_corridors(
            _anchored(edges, [], {1: "A", 2: "A"}))
        sec = _section(result, 1)
        self.assertEqual(sec["status"], "corridor")
        self.assertEqual(sec["edge_ids"], [])
        self.assertEqual(sec["node_ids"], ["A"])
        self.assertEqual(sec["cyclomatic_number"], 0)
        self.assertEqual(sec["shortest"]["length_m"], 0.0)
        self.assertEqual(sec["shortest"]["edge_ids"], [])


class TestAssignment(unittest.TestCase):
    def test_assignment_once_multiple_unassigned(self):
        # Middle temple 2 sits inside a shared biconnected block so its edges
        # appear in both SEC_1_2 and SEC_2_3 (assigned_multiple); the outer
        # edges are assigned_once; a dead-end edge is unassigned.
        # Graph: A(t1)-P  {P,Q,B,R} block  R-S-C(t3), dead end Q-Z.
        edges = [
            _te("ap", "A", "P", 1.0),
            _te("pq", "P", "Q", 1.0), _te("qb", "Q", "B", 1.0),
            _te("br", "B", "R", 1.0), _te("rp", "R", "P", 1.0),
            _te("rs", "R", "S", 1.0), _te("sc", "S", "C", 1.0),
            _te("qz", "Q", "Z", 1.0),  # dead-end: unassigned
        ]
        result = corridors.build_corridors(
            _anchored(edges, [], {1: "A", 2: "B", 3: "C"}))
        sec12 = _section(result, 1)
        sec23 = _section(result, 2)
        shared = {"pq", "qb", "br", "rp"}
        self.assertEqual(set(sec12["edge_ids"]) & set(sec23["edge_ids"]), shared)
        self.assertEqual(set(sec12["edge_ids"]), shared | {"ap"})
        self.assertEqual(set(sec23["edge_ids"]), shared | {"rs", "sc"})

        cls = {rec["edge_id"]: rec for rec in result["edge_classification"]}
        for eid in shared:
            self.assertEqual(cls[eid]["classification"], "assigned_multiple")
            self.assertEqual(cls[eid]["section_ids"], ["SEC_1_2", "SEC_2_3"])
        self.assertEqual(cls["ap"]["classification"], "assigned_once")
        self.assertEqual(cls["rs"]["classification"], "assigned_once")
        self.assertEqual(cls["qz"]["classification"], "unassigned")
        self.assertEqual(cls["qz"]["section_ids"], [])


class TestEightySevenSections(unittest.TestCase):
    def test_exactly_87_and_closure(self):
        edges = [_te("e%d" % i, "n%d" % i, "n%d" % (i + 1), 10.0)
                 for i in range(1, 88)]
        usable = {i: "n%d" % i for i in range(1, 89)}
        result = corridors.build_corridors(_anchored(edges, [], usable))
        self.assertEqual(result["kind"], "section_corridors")
        self.assertEqual(len(result["sections"]), 87)
        self.assertEqual([s["id"] for s in result["sections"]],
                         ["SEC_%d_%d" % (i, i + 1) for i in range(1, 88)])
        self.assertEqual(result["closure_88_1"], {"status": "not_requested"})
        acct = result["accounting"]
        self.assertEqual(acct["sections_total"], 87)
        self.assertEqual(sum(acct["by_status"].values()), 87)
        self.assertEqual(acct["by_status"]["corridor"], 87)
        self.assertEqual(acct["by_status"]["branched_corridor"], 0)
        self.assertEqual(acct["by_status"]["disconnected"], 0)
        self.assertEqual(acct["by_status"]["anchor_review_required"], 0)


class TestDeterminism(unittest.TestCase):
    def test_byte_determinism(self):
        edges = [
            _te("ab1", "A", "B1", 10.0), _te("b1c", "B1", "C", 10.0),
            _te("ab2", "A", "B2", 10.0), _te("b2c", "B2", "C", 10.0),
        ]
        data = _anchored(edges, [], {1: "A", 2: "C"})
        first = json.dumps(corridors.build_corridors(data), sort_keys=True)
        second = json.dumps(corridors.build_corridors(data), sort_keys=True)
        self.assertEqual(first, second)
        self.assertNotIn('"timestamp"', first)


class TestOracleAgreement(unittest.TestCase):
    """Brute-force oracle: enumerates all allowed simple s-t paths and compares
    the edge union against the Tarjan/block-cut corridor for several graphs."""

    def _check(self, edges, joins, usable, pairs):
        for i in pairs:
            edges_flat = _edges_for(edges, joins)
            result = corridors.build_corridors(_anchored(edges, joins, usable))
            sec = _section(result, i)
            s, t = usable[i], usable[i + 1]
            if s == t:
                self.assertEqual(sec["edge_ids"], [], "s==t section %d" % i)
                continue
            expected = _oracle_union(edges_flat, s, t,
                                     _other_anchor_nodes(usable, i))
            if not expected:
                self.assertEqual(sec["status"], "disconnected",
                                 "section %d" % i)
            else:
                self.assertEqual(set(sec["edge_ids"]), expected,
                                 "section %d edge mismatch" % i)

    def test_small_graphs(self):
        # chain + diamond + dead end + lollipop + parallel edges
        graphs = [
            ([_te("e1", "A", "B", 1.0), _te("e2", "B", "C", 1.0),
              _te("e3", "C", "D", 1.0)], [],
             {1: "A", 2: "B", 3: "C", 4: "D"}, [1, 2, 3]),
            ([_te("ab", "A", "B", 1.0), _te("bc", "B", "C", 1.0),
              _te("ad", "A", "D", 1.0), _te("dc", "D", "C", 1.0)], [],
             {1: "A", 2: "C"}, [1]),
            ([_te("ab", "A", "B", 1.0), _te("bx", "B", "X", 1.0),
              _te("xy", "X", "Y", 1.0), _te("az", "A", "Z", 1.0),
              _te("zy", "Z", "Y", 1.0)], [],
             {1: "A", 2: "B", 3: "Y"}, [1, 2]),
            ([_te("p1", "A", "B", 1.0), _te("p2", "A", "B", 1.0),
              _te("e2", "B", "C", 1.0)], [],
             {1: "A", 2: "B", 3: "C"}, [1, 2]),
            ([_te("e1", "A", "B", 1.0), _te("e2", "B", "C", 1.0)],
             [_join("j1", "C", "D", 0.0)],
             {1: "A", 2: "B", 3: "D"}, [1, 2]),
        ]
        for edges, joins, usable, pairs in graphs:
            self._check(edges, joins, usable, pairs)


class TestValidation(unittest.TestCase):
    def _base(self):
        return _anchored([_te("e1", "A", "B", 10.0)], [], {1: "A", 2: "B"})

    def test_wrong_kind(self):
        data = self._base()
        data["kind"] = "not_anchored_route_graph"
        with self.assertRaisesRegex(ValueError, "anchored_route_graph"):
            corridors.build_corridors(data)

    def test_missing_temple_anchor(self):
        data = self._base()
        data["temple_anchors"] = data["temple_anchors"][:-1]
        with self.assertRaisesRegex(ValueError, "exactly 88 temple anchors"):
            corridors.build_corridors(data)

    def test_duplicate_edge_id(self):
        data = self._base()
        data["traversal_edges"].append(dict(data["traversal_edges"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate edge id"):
            corridors.build_corridors(data)


class TestGeoJson(unittest.TestCase):
    def test_geojson_features_and_unassigned(self):
        edges = [
            _te("ab", "A", "B", 1.0), _te("bc", "B", "C", 1.0),
            _te("zz", "Z", "W", 1.0),  # unassigned
        ]
        data = _anchored(edges, [_join("j1", "C", "D", 0.0)],
                         {1: "A", 2: "D"})
        result = corridors.build_corridors(data)
        fc = corridors.build_corridor_geojson(data, result)
        ids = [f["id"] for f in fc["features"]]
        # no duplicate feature ids
        self.assertEqual(len(ids), len(set(ids)))
        # features sorted
        self.assertEqual(ids, sorted(ids))
        # assigned feature carries the section + edge props
        by_id = {f["id"]: f for f in fc["features"]}
        sec12 = by_id["SEC_1_2:ab"]
        self.assertEqual(sec12["properties"]["section_id"], "SEC_1_2")
        self.assertEqual(sec12["properties"]["edge_id"], "ab")
        self.assertEqual(sec12["properties"]["edge_kind"], "traversal_edge")
        self.assertEqual(sec12["properties"]["source_edge_id"], "SHE_ab")
        self.assertIs(sec12["properties"]["synthetic"], False)
        # synthetic join feature
        sj = by_id["SEC_1_2:j1"]
        self.assertEqual(sj["properties"]["edge_kind"], "synthetic_join")
        self.assertIs(sj["properties"]["synthetic"], True)
        self.assertIs(sj["properties"]["applied"], True)
        self.assertEqual(len(sj["geometry"]["coordinates"]), 2)
        # unassigned feature
        un = by_id["unassigned:zz"]
        self.assertIsNone(un["properties"]["section_id"])
        self.assertEqual(un["properties"]["classification"], "unassigned")
        self.assertEqual(un["properties"]["assignment_count"], 0)

    def test_no_timestamp_in_geojson(self):
        data = _anchored([_te("ab", "A", "B", 1.0)], [], {1: "A", 2: "B"})
        result = corridors.build_corridors(data)
        fc = corridors.build_corridor_geojson(data, result)
        self.assertNotIn('"timestamp"', json.dumps(fc))


if __name__ == "__main__":
    unittest.main()