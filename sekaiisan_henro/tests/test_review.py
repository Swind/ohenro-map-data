import json
import os
import tempfile
import unittest

from sekaiisan_henro import review
from sekaiisan_henro.__main__ import build_parser, dispatch
from sekaiisan_henro.projection import LAT0, LON0, project_point, unproject_point

BASE = (LON0, LAT0)
SNAPSHOT = "bb" * 32
DATASET = "88sekaiisan-henro"
LENGTHS = {"global_original_m": 100.0, "global_reconstructed_m": 100.0,
           "max_absolute_error_m": 0.0, "per_route": {}}


def at(dx, dy):
    x0, y0 = project_point(*BASE)
    return unproject_point(x0 + dx, y0 + dy)


# Deterministic node coordinates (metric offsets east/north of the projection
# centre) reused across fixtures so geometry and reports stay consistent.
A, B, C, D = at(0, 0), at(100, 0), at(200, 0), at(300, 0)
E, F = at(500, 0), at(600, 0)
T1 = at(250, 0)


def _node(nid, coord):
    return {"id": nid, "coordinates": [coord[0], coord[1]],
            "lon": coord[0], "lat": coord[1], "kinds": [], "source_refs": []}


def _te(eid, a, b, length, coord_a, coord_b):
    return {"id": eid, "from": a, "to": b, "length_m": length,
            "coordinates": [list(coord_a), list(coord_b)],
            "source_edge_id": "SHE_x", "provenance": {}}


def _join(jid, a, b, distance, coord_a, coord_b, kind="endpoint_cluster", **kw):
    rec = {"id": jid, "kind": kind, "from": a, "to": b,
           "distance_m": distance, "coordinates": [list(coord_a), list(coord_b)]}
    rec.update(kw)
    return rec


def _normalized():
    return {
        "schema_version": 1, "dataset_id": DATASET, "snapshot_sha256": SNAPSHOT,
        "routes": [], "temples": [],
        "accounting": {"routes": 0, "linestrings": 0, "points": 0,
                       "temples": 88, "missing_source_fid": 0,
                       "by_prefecture": {}},
    }


def _inventory(etl_gaps=None):
    etl_buckets = {"<=5m": [], "5-20m": list(etl_gaps or [])}
    return {
        "schema_version": 1, "kind": "topology_inventory",
        "dataset_id": DATASET, "snapshot_sha256": SNAPSHOT,
        "source_accounting": _normalized()["accounting"],
        "route_sources": {},
        "analysis_accounting": {"route_records": 0, "source_points": 0},
        "proximity_candidates": {
            "endpoint_pairs": {"<=5m": [], "5-20m": []},
            "endpoint_to_line": etl_buckets,
            "summary": {"endpoint_pairs_<=5m": 0, "endpoint_pairs_5-20m": 0,
                        "endpoint_to_line_<=5m": 0,
                        "endpoint_to_line_5-20m": len(etl_buckets["5-20m"])},
        },
        "intersections": {"summary": {"ambiguous_crossings": 0}},
        "exact_connections": {}, "diagnostic_components": {},
    }


def _anchored(tied_88=True):
    nodes = [_node(nid, coord) for nid, coord in (
        ("A", A), ("B", B), ("C", C), ("D", D), ("E", E), ("F", F))]
    synthetic_nodes = [_node("T1", T1)]
    traversal_edges = [
        _te("te1", "A", "B", 10.0, A, B),
        _te("te2", "B", "C", 20.0, B, C),
        _te("te3", "D", "C", 30.0, D, C),  # stored D->C -> reverse for C->D
        _te("te4", "E", "F", 40.0, E, F),
    ]
    synthetic_joins = [
        _join("shj_primary", "A", "C", 25.0, A, C),
        _join("shj_alt2", "A", "B", 8.0, A, B),
        _join("shj_unused", "E", "F", 5.0, E, F),
        _join("shj_etl", "A", "T1", 4.0, A, T1, kind="endpoint_to_line",
              endpoint_route="RA", target_route="RB", target_edge="SHE_t",
              projected_coordinates=list(T1)),
    ]

    def anchor(number, usable, coord, conf, candidate, chosen=None,
               projected=None):
        rec = {
            "temple_number": number, "temple_id": "TEMPLE_%d" % number,
            "name_jp": "寺%d" % number, "coordinates": [coord[0], coord[1]],
            "distance_m": 5.0 if usable else 200.0, "confidence": conf,
            "status": conf, "candidate_edge_ids": list(candidate),
            "usable_for_routing": usable,
        }
        if chosen is not None:
            rec["chosen_edge_id"] = chosen
            rec["projected_coordinates"] = list(projected)
            rec["anchor_node_id"] = {"A": "A", "C": "C", "D": "D",
                                     "F": "F"}.get(chosen, "AN_x")
            rec["measure_m"] = 0.0
        return rec

    anchors = []
    anchors.append(anchor(1, True, A, "near", ["SHE_a"], chosen="A", projected=A))
    anchors.append(anchor(2, True, C, "near", ["SHE_c"], chosen="C", projected=C))
    anchors.append(anchor(3, True, D, "near", ["SHE_d"], chosen="D", projected=D))
    anchors.append(anchor(4, True, F, "near", ["SHE_f"], chosen="F", projected=F))
    for number in range(5, 88):
        coord = at(0, number * 10.0)
        anchors.append(anchor(number, False, coord, "review_required",
                              ["SHE_z"], chosen="SHE_z", projected=at(1, number * 10.0)))
    coord = at(0, 880.0)
    if tied_88:
        anchors.append(anchor(88, False, coord, "review_required", ["SHE_x", "SHE_y"]))
    else:
        anchors.append(anchor(88, False, coord, "review_required",
                              ["SHE_z"], chosen="SHE_z", projected=at(1, 880.0)))

    return {
        "schema_version": 1, "kind": "anchored_route_graph",
        "dataset_id": DATASET, "snapshot_sha256": SNAPSHOT,
        "projection": {"kind": "equirectangular", "R": 6371008.8,
                       "lon0": LON0, "lat0": LAT0},
        "limitation": "test fixture", "note": "test fixture",
        "nodes": nodes, "synthetic_nodes": synthetic_nodes, "anchor_nodes": [],
        "edges": [], "route_sources": {},
        "synthetic_joins": synthetic_joins,
        "temple_anchors": anchors, "traversal_edges": traversal_edges,
        "components": [], "components_before": [],
        "accounting": {
            "temple_anchors": 88, "anchors_usable": 4,
            "anchors_review_required": 84, "traversal_edges": len(traversal_edges),
            "components_after": 1, "nodes": len(nodes),
            "synthetic_nodes": len(synthetic_nodes),
            "synthetic_joins": len(synthetic_joins),
            "lengths": dict(LENGTHS),
            "source_routes": 0, "source_linestrings": 0, "source_points": 0,
        },
    }


def _prox(anchored, report):
    """Build a proximity graph carrying the SAME source payload as ``anchored``
    (nodes/synthetic_nodes/edges/synthetic_joins/route_sources/components) plus
    the supplied report, so cross-input validation passes."""
    return {
        "schema_version": 2, "kind": "proximity_route_graph",
        "dataset_id": DATASET, "snapshot_sha256": SNAPSHOT,
        "projection": {"kind": "equirectangular", "R": 6371008.8,
                       "lon0": LON0, "lat0": LAT0},
        "limitation": "test fixture", "note": "test fixture",
        "route_sources": dict(anchored["route_sources"]),
        "nodes": anchored["nodes"], "synthetic_nodes": anchored["synthetic_nodes"],
        "edges": anchored["edges"], "synthetic_joins": anchored["synthetic_joins"],
        "components": anchored["components_before"], "components_before": [],
        "proximity_report": report,
        "accounting": {
            "source_routes": 0, "source_linestrings": 0, "source_points": 0,
            "nodes": len(anchored["nodes"]), "edges": len(anchored["edges"]),
            "synthetic_nodes": len(anchored["synthetic_nodes"]),
            "synthetic_joins": len(anchored["synthetic_joins"]),
            "components_after": 1, "components_before": 1,
            "lengths": dict(anchored["accounting"]["lengths"]),
            "proximity": {"endpoint_clusters_applied": 3,
                          "endpoint_clusters_rejected_ambiguous": 1,
                          "endpoint_to_line_applied": 1,
                          "endpoint_to_line_rejected_competing": 1,
                          "gaps_5_20m_reported": 2,
                          "ambiguous_crossings_total": 1},
        },
    }


def _sections():
    def sec(sid, frm, to, status, **kw):
        base = {
            "id": sid, "from_temple": frm, "to_temple": to, "status": status,
            "anchors": {"from": {"temple_number": frm, "usable_for_routing": True,
                                 "confidence": "near", "status": "near",
                                 "distance_m": 5.0},
                        "to": {"temple_number": to, "usable_for_routing": True,
                               "confidence": "near", "status": "near",
                               "distance_m": 5.0}},
        }
        base["anchors"]["from"]["node_id"] = kw.pop("from_node", None)
        base["anchors"]["to"]["node_id"] = kw.pop("to_node", None)
        base.update(kw)
        return base

    sections = []
    sections.append(sec("SEC_1_2", 1, 2, "ambiguous",
                        from_node="A", to_node="C",
                        primary={"edge_ids": ["shj_primary"], "directions": ["forward"],
                                 "length_m": 25.0},
                        alternative={"edge_ids": ["shj_alt2", "te2"],
                                     "directions": ["forward", "forward"],
                                     "length_m": 28.0},
                        diagnostics={}))
    sections.append(sec("SEC_2_3", 2, 3, "candidate",
                        from_node="C", to_node="D",
                        primary={"edge_ids": ["te3"], "directions": ["reverse"],
                                 "length_m": 30.0}))
    sections.append(sec("SEC_3_4", 3, 4, "disconnected",
                        from_node="D", to_node="F"))
    for i in range(4, 88):
        sections.append(sec("SEC_%d_%d" % (i, i + 1), i, i + 1,
                            "anchor_review_required"))
    by_status = {"candidate": 1, "ambiguous": 1, "disconnected": 1,
                 "anchor_review_required": 84}
    return {
        "schema_version": 1, "kind": "temple_sections",
        "dataset_id": DATASET, "snapshot_sha256": SNAPSHOT,
        "projection": {"kind": "equirectangular"}, "limitation": "test fixture",
        "note": "test fixture", "sections": sections,
        "closure_88_1": {"status": "not_requested"},
        "accounting": {"sections_total": 87, "by_status": by_status,
                       "paths_using_synthetic_joins": 1},
    }


def _standard_report():
    """A fully consistent 5-document fixture (all cross-input checks pass)."""
    anchored = _anchored()
    report = [
        # applied joins (must match anchored synthetic_joins for endpoint_cluster)
        {"kind": "endpoint_cluster", "applied": True, "distance_m": 25.0,
         "from_node": "A", "to_node": "C", "route_a": "RA", "route_b": "RB",
         "reason": "applied: unambiguous <=5m endpoint cluster"},
        {"kind": "endpoint_cluster", "applied": True, "distance_m": 8.0,
         "from_node": "A", "to_node": "B", "route_a": "RC", "route_b": "RD",
         "reason": "applied: unambiguous <=5m endpoint cluster"},
        {"kind": "endpoint_cluster", "applied": True, "distance_m": 5.0,
         "from_node": "E", "to_node": "F", "route_a": "RE", "route_b": "RF",
         "reason": "applied: unambiguous <=5m endpoint cluster"},
        {"kind": "endpoint_to_line", "applied": True, "distance_m": 4.0,
         "from_node": "A", "to_node": "T1", "route_a": "RA", "route_b": "RB",
         "coordinates": list(T1), "reason": "applied: unique endpoint-to-line"},
        # reported (rejected / gaps / crossings)
        {"kind": "endpoint_cluster", "applied": False, "distance_m": 2.0,
         "from_node": "B", "to_node": "C", "route_a": "RA", "route_b": "RB",
         "reason": "rejected: ambiguous/competing"},
        {"kind": "endpoint_to_line", "applied": False, "distance_m": 3.0,
         "from_node": "A", "route_a": "RA", "route_b": "RB", "coordinates": list(C),
         "reason": "rejected: competing"},
        {"kind": "endpoint_pair_gap", "applied": False, "distance_m": 7.0,
         "route_a": "RA", "route_b": "RB", "coordinates": [list(A), list(B)],
         "reason": "not joined: 5-20m endpoint gap"},
        {"kind": "endpoint_to_line_gap", "applied": False, "distance_m": 6.0,
         "route_a": "R1", "route_b": "R2", "coordinates": list(B),
         "reason": "not joined: 5-20m endpoint-to-line gap"},
        {"kind": "ambiguous_crossing", "applied": False, "distance_m": 0.0,
         "route_a": "RA", "route_b": "RB", "coordinates": list(C),
         "reason": "not joined: ambiguous crossing"},
    ]
    etl_gap = {"endpoint_route": "R1", "endpoint": "start",
               "endpoint_coordinates": list(A), "target_route": "R2",
               "distance_m": 6.0, "projected_coordinates": list(B)}
    return (_normalized(), _inventory([etl_gap]), _prox(anchored, report),
            anchored, _sections())


class TestSourceEdges(unittest.TestCase):
    def test_features_present_and_sorted(self):
        n, i, p, a, s = _standard_report()
        a["edges"] = [{"id": "SHE_1", "from": "A", "to": "B",
                       "coordinates": [[0, 0], [1, 1]], "length_m": 1.0,
                       "provenance": {"route_id": "R", "prefecture": "tokushima",
                                      "source_file": "t.kml", "source_fid": "1",
                                      "part": 1}}]
        # keep prox value-identical to anchored edges
        p["edges"] = a["edges"]
        p["accounting"]["edges"] = len(a["edges"])
        pack = review.build_review_pack(n, i, p, a, s)
        fc = pack["files"]["source-edges.geojson"]
        self.assertEqual(len(fc["features"]), 1)
        f = fc["features"][0]
        self.assertEqual(f["id"], "SHE_1")
        self.assertEqual(f["geometry"]["type"], "LineString")
        self.assertEqual(f["properties"]["edge_id"], "SHE_1")
        self.assertEqual(f["properties"]["route_id"], "R")


class TestTopologyGeometriesAndPriorities(unittest.TestCase):
    def test_all_categories_and_geometries(self):
        n, i, p, a, s = _standard_report()
        pack = review.build_review_pack(n, i, p, a, s)
        fc = pack["files"]["topology.geojson"]
        by_id = {f["id"]: f for f in fc["features"]}
        # applied joins: shj_primary P0 (primary), shj_alt2 P1 (alternative),
        # shj_unused P2, shj_etl applied endpoint_to_line (unused -> P2)
        self.assertEqual(by_id["shj_primary"]["geometry"]["type"], "LineString")
        self.assertEqual(by_id["shj_primary"]["properties"]["priority"], "P0")
        self.assertEqual(by_id["shj_primary"]["properties"]["used_by_primary_sections"],
                         ["SEC_1_2"])
        self.assertEqual(by_id["shj_primary"]["properties"]["route_a"], "RA")
        self.assertEqual(by_id["shj_primary"]["properties"]["route_b"], "RB")
        self.assertEqual(by_id["shj_alt2"]["properties"]["priority"], "P1")
        self.assertEqual(by_id["shj_alt2"]["properties"]["used_by_alternative_sections"],
                         ["SEC_1_2"])
        self.assertEqual(by_id["shj_alt2"]["properties"]["route_a"], "RC")
        self.assertEqual(by_id["shj_unused"]["properties"]["priority"], "P2")
        # applied endpoint_to_line carries endpoint/target route ids
        self.assertEqual(by_id["shj_etl"]["properties"]["route_a"], "RA")
        self.assertEqual(by_id["shj_etl"]["properties"]["route_b"], "RB")
        self.assertTrue(by_id["shj_etl"]["properties"]["applied"])
        # rejected endpoint_cluster -> LineString, P1
        rej_ec = [f for f in fc["features"]
                  if f["properties"]["review_kind"] == "endpoint_cluster"
                  and not f["properties"]["applied"]][0]
        self.assertEqual(rej_ec["geometry"]["type"], "LineString")
        self.assertEqual(rej_ec["properties"]["priority"], "P1")
        self.assertTrue(rej_ec["id"].startswith("REV_"))
        # rejected endpoint_to_line -> LineString connector, P1
        rej_etl = [f for f in fc["features"]
                   if f["properties"]["review_kind"] == "endpoint_to_line"
                   and not f["properties"]["applied"]][0]
        self.assertEqual(rej_etl["geometry"]["type"], "LineString")
        # endpoint_pair_gap -> LineString
        gap = [f for f in fc["features"]
               if f["properties"]["review_kind"] == "endpoint_pair_gap"][0]
        self.assertEqual(gap["geometry"]["type"], "LineString")
        # endpoint_to_line_gap -> LineString connector from endpoint to projected
        etl_gap = [f for f in fc["features"]
                   if f["properties"]["review_kind"] == "endpoint_to_line_gap"][0]
        self.assertEqual(etl_gap["geometry"]["type"], "LineString")
        self.assertEqual(len(etl_gap["geometry"]["coordinates"]), 2)
        # ambiguous_crossing -> Point
        cross = [f for f in fc["features"]
                 if f["properties"]["review_kind"] == "ambiguous_crossing"][0]
        self.assertEqual(cross["geometry"]["type"], "Point")

    def test_deterministic_order(self):
        n, i, p, a, s = _standard_report()
        ids1 = [f["id"] for f in review.build_review_pack(
            n, i, p, a, s)["files"]["topology.geojson"]["features"]]
        ids2 = [f["id"] for f in review.build_review_pack(
            n, i, p, a, s)["files"]["topology.geojson"]["features"]]
        self.assertEqual(ids1, ids2)
        self.assertEqual(ids1, sorted(ids1))


class TestAppliedClusterRouteMatch(unittest.TestCase):
    def test_missing_applied_report_match_fails(self):
        n, i, p, a, s = _standard_report()
        # drop the applied record for shj_primary (A-C, 25) -> no match
        p["proximity_report"] = [r for r in p["proximity_report"]
                                 if not (r["kind"] == "endpoint_cluster"
                                         and r["from_node"] == "A"
                                         and r["to_node"] == "C"
                                         and r["distance_m"] == 25.0)]
        with self.assertRaisesRegex(ValueError, "no applied report record"):
            review.build_review_pack(n, i, p, a, s)

    def test_ambiguous_applied_report_match_fails(self):
        n, i, p, a, s = _standard_report()
        # add a second applied record for the same node pair + distance with a
        # different route pair -> ambiguous
        p["proximity_report"].append({
            "kind": "endpoint_cluster", "applied": True, "distance_m": 25.0,
            "from_node": "A", "to_node": "C", "route_a": "RX", "route_b": "RY",
            "reason": "applied"})
        with self.assertRaisesRegex(ValueError, "ambiguous applied report"):
            review.build_review_pack(n, i, p, a, s)


class TestEndpointToLineGapDisambiguation(unittest.TestCase):
    def test_distinct_projected_coords_same_route_pair_and_distance(self):
        # Two 5-20m endpoint-to-line gaps on the SAME route pair with the SAME
        # rounded distance but distinct projected points must each resolve to
        # their own endpoint coordinate (the old (route,target,distance) key
        # would collide and pick one).
        n, i, p, a, s = _standard_report()
        gap_records = [
            {"kind": "endpoint_to_line_gap", "applied": False, "distance_m": 6.0,
             "route_a": "R1", "route_b": "R2", "coordinates": list(B),
             "reason": "not joined: 5-20m endpoint-to-line gap"},
            {"kind": "endpoint_to_line_gap", "applied": False, "distance_m": 6.0,
             "route_a": "R1", "route_b": "R2", "coordinates": list(D),
             "reason": "not joined: 5-20m endpoint-to-line gap"},
        ]
        inventory_gaps = [
            {"endpoint_route": "R1", "endpoint": "start",
             "endpoint_coordinates": list(A), "target_route": "R2",
             "distance_m": 6.0, "projected_coordinates": list(B)},
            {"endpoint_route": "R1", "endpoint": "end",
             "endpoint_coordinates": list(C), "target_route": "R2",
             "distance_m": 6.0, "projected_coordinates": list(D)},
        ]
        # replace the standard gaps with the two colliding ones
        p["proximity_report"] = [r for r in p["proximity_report"]
                                 if r["kind"] != "endpoint_to_line_gap"] + gap_records
        i = _inventory(inventory_gaps)
        pack = review.build_review_pack(n, i, p, a, s)
        gaps = [f for f in pack["files"]["topology.geojson"]["features"]
                if f["properties"]["review_kind"] == "endpoint_to_line_gap"]
        self.assertEqual(len(gaps), 2)
        starts = {tuple(g["geometry"]["coordinates"][0]) for g in gaps}
        self.assertEqual(starts, {tuple(A), tuple(C)})
        # deterministic distinct review ids
        self.assertEqual(len({g["id"] for g in gaps}), 2)

    def test_ambiguous_matching_fails(self):
        n, i, p, a, s = _standard_report()
        # two inventory entries share projected B but different endpoints
        i = _inventory([
            {"endpoint_route": "R1", "endpoint": "start",
             "endpoint_coordinates": list(A), "target_route": "R2",
             "distance_m": 6.0, "projected_coordinates": list(B)},
            {"endpoint_route": "R1", "endpoint": "end",
             "endpoint_coordinates": list(C), "target_route": "R2",
             "distance_m": 6.0, "projected_coordinates": list(B)},
        ])
        with self.assertRaisesRegex(ValueError, "ambiguous endpoint coordinate"):
            review.build_review_pack(n, i, p, a, s)


class TestAnchors(unittest.TestCase):
    def test_tied_anchor_point_only(self):
        n, i, p, a, s = _standard_report()
        pack = review.build_review_pack(n, i, p, a, s)
        fc = pack["files"]["anchors.geojson"]
        by_id = {f["id"]: f for f in fc["features"]}
        self.assertIn("REV_ANCHOR_88", by_id)
        self.assertNotIn("REV_ANCHOR_88:offset", by_id)
        self.assertEqual(by_id["REV_ANCHOR_88"]["geometry"]["type"], "Point")
        self.assertEqual(by_id["REV_ANCHOR_88"]["properties"]["priority"], "P0")
        self.assertEqual(len(by_id["REV_ANCHOR_88"]["properties"]["candidate_edge_ids"]), 2)
        self.assertIn("REV_ANCHOR_5:offset", by_id)
        off = by_id["REV_ANCHOR_5:offset"]
        self.assertEqual(off["geometry"]["type"], "LineString")
        self.assertTrue(off["properties"]["review_visualization_only"])
        self.assertEqual(by_id["REV_ANCHOR_1"]["properties"]["priority"], "P2")

    def test_resolved_shared_node_tie_emits_offset_without_chosen_edge(self):
        n, i, p, a, s = _standard_report()
        # Convert temple 88 into a resolved shared-node tie: it has a projected
        # location but NO single chosen edge, plus resolution/resolved_edge_ids.
        a88 = next(x for x in a["temple_anchors"] if x["temple_number"] == 88)
        a88.update({
            "confidence": "near", "status": "near", "usable_for_routing": True,
            "distance_m": 5.0,
            "anchor_node_id": "A",
            "projected_coordinates": list(A),
            "resolution": "shared_node_tie",
            "resolved_edge_ids": list(a88["candidate_edge_ids"]),
        })
        a88.pop("chosen_edge_id", None)
        a88.pop("measure_m", None)
        pack = review.build_review_pack(n, i, p, a, s)
        fc = pack["files"]["anchors.geojson"]
        by_id = {f["id"]: f for f in fc["features"]}
        # offset line is emitted for the resolved tie even without a chosen edge
        self.assertIn("REV_ANCHOR_88:offset", by_id)
        off = by_id["REV_ANCHOR_88:offset"]
        self.assertEqual(off["geometry"]["type"], "LineString")
        self.assertTrue(off["properties"]["review_visualization_only"])
        self.assertEqual(off["properties"]["resolution"], "shared_node_tie")
        self.assertEqual(off["properties"]["resolved_edge_ids"],
                         ["SHE_x", "SHE_y"])
        self.assertEqual(off["properties"]["candidate_edge_ids"], ["SHE_x", "SHE_y"])
        # no chosen_edge_id is claimed (it does not exist on the source record)
        self.assertNotIn("chosen_edge_id", off["properties"])
        self.assertEqual(off["properties"]["priority"], "P2")
        # the review item references also expose resolution/resolved_edge_ids
        item = next(x for x in pack["files"]["review-items.json"]["items"]
                    if x["review_id"] == "REV_ANCHOR_88")
        self.assertEqual(item["references"]["resolution"], "shared_node_tie")
        self.assertEqual(item["references"]["resolved_edge_ids"], ["SHE_x", "SHE_y"])

    def test_all_88_points_and_unique_offsets(self):
        n, i, p, a, s = _standard_report()
        fc = review.build_review_pack(n, i, p, a, s)["files"]["anchors.geojson"]
        points = [f for f in fc["features"] if f["geometry"]["type"] == "Point"]
        offsets = [f for f in fc["features"] if f["geometry"]["type"] == "LineString"]
        self.assertEqual(len(points), 88)
        self.assertEqual(len(offsets), 4 + 83)


class TestSectionsGeometry(unittest.TestCase):
    def test_primary_and_alternative_reconstruction(self):
        n, i, p, a, s = _standard_report()
        fc = review.build_review_pack(n, i, p, a, s)["files"]["sections.geojson"]
        by_id = {f["id"]: f for f in fc["features"]}
        prim = by_id["SEC_1_2:primary"]
        self.assertEqual(prim["geometry"]["type"], "LineString")
        self.assertEqual(prim["properties"]["synthetic_join_ids"], ["shj_primary"])
        self.assertEqual(prim["properties"]["priority"], "P0")
        alt = by_id["SEC_1_2:alternative"]
        self.assertEqual(alt["geometry"]["type"], "LineString")
        self.assertEqual(alt["properties"]["synthetic_join_ids"], ["shj_alt2"])
        rev = by_id["SEC_2_3:primary"]
        self.assertEqual(rev["geometry"]["type"], "LineString")
        self.assertEqual(rev["properties"]["variant"], "primary")
        self.assertNotIn("SEC_3_4:primary", by_id)
        self.assertNotIn("SEC_3_4:alternative", by_id)

    def test_continuity_failure_raises(self):
        n, i, p, a, s = _standard_report()
        s["sections"][0]["primary"]["edge_ids"] = ["shj_primary"]
        s["sections"][0]["anchors"]["from"]["node_id"] = "D"
        with self.assertRaises(ValueError):
            review.build_review_pack(n, i, p, a, s)

    def test_length_mismatch_raises(self):
        n, i, p, a, s = _standard_report()
        s["sections"][0]["primary"]["length_m"] = 999.0
        with self.assertRaises(ValueError):
            review.build_review_pack(n, i, p, a, s)


class TestReviewItems(unittest.TestCase):
    def test_counts_and_allowed_decisions(self):
        n, i, p, a, s = _standard_report()
        pack = review.build_review_pack(n, i, p, a, s)
        items = pack["files"]["review-items.json"]["items"]
        # 4 applied + 5 reported topology + 88 anchors + 87 sections
        self.assertEqual(len(items), 9 + 88 + 87)
        self.assertTrue(all(item["decision"] is None for item in items))
        # category-specific allowed decisions
        topo_applied = {tuple(it["allowed_decisions"]) for it in items
                        if it["category"] == "topology" and it["status"] == "applied"}
        topo_reported = {tuple(it["allowed_decisions"]) for it in items
                         if it["category"] == "topology" and it["status"] == "reported"}
        self.assertEqual(topo_applied,
                         {("accept_as_is", "forbid_join", "needs_more_evidence")})
        self.assertEqual(topo_reported,
                         {("keep_disconnected", "forced_join_proposed",
                           "needs_more_evidence")})
        anchors = {tuple(it["allowed_decisions"]) for it in items
                   if it["category"] == "anchor"}
        self.assertEqual(anchors,
                         {("accept_anchor", "temple_anchor_override",
                           "remain_review_required")})
        # status-specific section decisions
        sec_dec = {it["status"]: tuple(it["allowed_decisions"]) for it in items
                   if it["category"] == "section"}
        self.assertEqual(sec_dec["candidate"],
                         ("accept_as_candidate", "topology_issue", "anchor_issue"))
        self.assertEqual(sec_dec["ambiguous"],
                         ("ambiguity_unresolved", "primary_plausible",
                          "alternative_plausible", "topology_issue", "anchor_issue"))
        self.assertEqual(sec_dec["disconnected"],
                         ("expected_source_gap", "topology_issue", "anchor_issue"))
        self.assertEqual(sec_dec["anchor_review_required"],
                         ("remain_review_required", "anchor_issue"))
        # unique review ids, sorted
        ids = [item["review_id"] for item in items]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids, sorted(ids))
        anc88 = next(item for item in items
                     if item["category"] == "anchor" and item["review_id"] == "REV_ANCHOR_88")
        self.assertTrue(anc88["evidence_required"])
        self.assertEqual(anc88["priority"], "P0")


class TestValidation(unittest.TestCase):
    def _base(self):
        return _standard_report()

    def test_kind_mismatch(self):
        n, i, p, a, s = self._base()
        a["kind"] = "not_anchored_route_graph"
        with self.assertRaisesRegex(ValueError, "anchored_route_graph"):
            review.build_review_pack(n, i, p, a, s)

    def test_snapshot_mismatch(self):
        n, i, p, a, s = self._base()
        a["snapshot_sha256"] = "cc" * 32
        with self.assertRaisesRegex(ValueError, "snapshot mismatch"):
            review.build_review_pack(n, i, p, a, s)

    def test_dataset_mismatch(self):
        n, i, p, a, s = self._base()
        s["dataset_id"] = "other"
        with self.assertRaisesRegex(ValueError, "dataset mismatch"):
            review.build_review_pack(n, i, p, a, s)

    def test_wrong_temple_count(self):
        n, i, p, a, s = self._base()
        a["temple_anchors"] = a["temple_anchors"][:-1]
        with self.assertRaisesRegex(ValueError, "exactly 88"):
            review.build_review_pack(n, i, p, a, s)

    def test_wrong_section_count(self):
        n, i, p, a, s = self._base()
        s["sections"] = s["sections"][:-1]
        with self.assertRaisesRegex(ValueError, "exactly 87"):
            review.build_review_pack(n, i, p, a, s)

    def test_inventory_source_accounting_mismatch(self):
        n, i, p, a, s = self._base()
        i["source_accounting"] = {}
        with self.assertRaisesRegex(ValueError, "source accounting mismatch"):
            review.build_review_pack(n, i, p, a, s)

    def test_proximity_source_counts_mismatch(self):
        n, i, p, a, s = self._base()
        p["accounting"]["source_points"] = 999
        with self.assertRaisesRegex(ValueError, "proximity source_points"):
            review.build_review_pack(n, i, p, a, s)

    def test_anchored_source_not_value_identical(self):
        n, i, p, a, s = self._base()
        a["edges"] = [{"id": "SHE_x", "from": "A", "to": "B",
                       "coordinates": [[0, 0], [1, 1]], "length_m": 1.0,
                       "provenance": {}}]
        with self.assertRaisesRegex(ValueError, "anchored edges differs"):
            review.build_review_pack(n, i, p, a, s)

    def test_anchored_lengths_mismatch(self):
        n, i, p, a, s = self._base()
        a["accounting"]["lengths"] = {"per_route": {}}
        with self.assertRaisesRegex(ValueError, "anchored source lengths"):
            review.build_review_pack(n, i, p, a, s)

    def test_anchored_components_before_mismatch(self):
        n, i, p, a, s = self._base()
        a["components_before"] = [{"id": "SHC_x", "node_count": 1, "edge_count": 0,
                                   "nodes": ["A"], "edges": []}]
        with self.assertRaisesRegex(ValueError, "components_before"):
            review.build_review_pack(n, i, p, a, s)

    def test_temple_numbers_not_1_88(self):
        n, i, p, a, s = self._base()
        a["temple_anchors"][0]["temple_number"] = 2
        with self.assertRaisesRegex(ValueError, "temple anchor numbers"):
            review.build_review_pack(n, i, p, a, s)

    def test_section_ids_not_sequential(self):
        n, i, p, a, s = self._base()
        s["sections"][0]["id"] = "SEC_99_1"
        with self.assertRaisesRegex(ValueError, "section ids"):
            review.build_review_pack(n, i, p, a, s)

    def test_section_accounting_status_mismatch(self):
        n, i, p, a, s = self._base()
        s["accounting"]["by_status"] = {"candidate": 0, "ambiguous": 1,
                                        "disconnected": 1,
                                        "anchor_review_required": 84}
        with self.assertRaisesRegex(ValueError, "by_status"):
            review.build_review_pack(n, i, p, a, s)


class TestDuplicateIds(unittest.TestCase):
    def test_duplicate_review_id_fails(self):
        n, i, p, a, s = _standard_report()
        # duplicate the existing rejected endpoint_cluster report record -> the
        # same REV_ review id is produced twice -> collision must fail
        existing = next(r for r in p["proximity_report"]
                        if r["kind"] == "endpoint_cluster" and not r["applied"])
        p["proximity_report"] = p["proximity_report"] + [dict(existing)]
        with self.assertRaisesRegex(ValueError, "duplicate"):
            review.build_review_pack(n, i, p, a, s)


class TestDeterminismAndAtomicWrite(unittest.TestCase):
    def test_byte_determinism(self):
        n, i, p, a, s = _standard_report()
        first = review.build_review_pack(n, i, p, a, s)["files"]["report.json"]
        second = review.build_review_pack(n, i, p, a, s)["files"]["report.json"]
        self.assertEqual(json.dumps(first, sort_keys=True),
                         json.dumps(second, sort_keys=True))
        self.assertNotIn('"timestamp"', json.dumps(first))

    def test_run_review_writes_all_files_atomically(self):
        d = tempfile.mkdtemp()
        n, i, p, a, s = _standard_report()
        paths = {}
        for key, doc in (("normalized", n), ("inventory", i), ("prox", p),
                         ("anchored", a), ("sections", s)):
            path = os.path.join(d, key + ".json")
            with open(path, "w", encoding="utf-8") as stream:
                json.dump(doc, stream)
            paths[key] = path
        outdir = os.path.join(d, "review")
        report = review.run_review(paths["normalized"], paths["inventory"],
                                   paths["prox"], paths["anchored"],
                                   paths["sections"], outdir)
        self.assertEqual(report["kind"], "review_pack")
        expected = {"source-edges.geojson", "topology.geojson", "anchors.geojson",
                    "sections.geojson", "review-items.json", "report.json"}
        self.assertEqual(set(os.listdir(outdir)), expected)
        self.assertFalse(any(f.endswith(".tmp") for f in os.listdir(outdir)))


class TestCliBuildReviewPack(unittest.TestCase):
    def test_defaults(self):
        args = build_parser().parse_args(["build-review-pack"])
        self.assertEqual(args.command, "build-review-pack")
        self.assertEqual(args.normalized, "output/sekaiisan-henro-normalized.json")
        self.assertEqual(args.inventory, "output/sekaiisan-henro-topology-inventory.json")
        self.assertEqual(args.proximity, "output/sekaiisan-henro-graph-proximity.json")
        self.assertEqual(args.anchored, "output/sekaiisan-henro-graph-anchors.json")
        self.assertEqual(args.sections, "output/sekaiisan-henro-temple-sections.json")
        self.assertEqual(args.output_dir, "output/sekaiisan-henro-review")

    def test_dispatch_writes_all_files(self):
        d = tempfile.mkdtemp()
        n, i, p, a, s = _standard_report()
        for key, doc in (("normalized", n), ("inventory", i), ("prox", p),
                         ("anchored", a), ("sections", s)):
            with open(os.path.join(d, key + ".json"), "w", encoding="utf-8") as stream:
                json.dump(doc, stream)
        outdir = os.path.join(d, "review")
        parser = build_parser()
        result = dispatch(parser.parse_args([
            "build-review-pack",
            "--normalized", os.path.join(d, "normalized.json"),
            "--inventory", os.path.join(d, "inventory.json"),
            "--proximity", os.path.join(d, "prox.json"),
            "--anchored", os.path.join(d, "anchored.json"),
            "--sections", os.path.join(d, "sections.json"),
            "--output-dir", outdir,
        ]))
        self.assertEqual(result["kind"], "review_pack")
        expected = {"source-edges.geojson", "topology.geojson", "anchors.geojson",
                    "sections.geojson", "review-items.json", "report.json"}
        self.assertEqual(set(os.listdir(outdir)), expected)
        self.assertFalse(any(f.endswith(".tmp") for f in os.listdir(outdir)))


if __name__ == "__main__":
    unittest.main()