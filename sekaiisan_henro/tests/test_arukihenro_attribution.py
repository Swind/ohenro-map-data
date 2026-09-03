import json
import os
import tempfile
import unittest

from sekaiisan_henro.arukihenro_attribution import build_attribution


def _arukihenro(routes):
    return {"schema_version": 1, "source": "test", "summary": {}, "routes": routes}


def _route(temple_range, title, lines):
    return {
        "id": "route_%s_%s" % (temple_range[0], temple_range[-1]),
        "temple_range": temple_range,
        "title": title,
        "maps": [{"map_id": "m", "lines": [{"coordinates": line} for line in lines]}],
    }


def _graph(edges):
    nodes = {}
    for edge in edges:
        nodes[edge["from"]] = {"id": edge["from"], "coordinates": [0, 0], "kinds": ["endpoint"], "source_refs": []}
        nodes[edge["to"]] = {"id": edge["to"], "coordinates": [0, 0], "kinds": ["endpoint"], "source_refs": []}
    return {
        "schema_version": 1,
        "kind": "exact_route_graph",
        "dataset_id": "88sekaiisan-henro",
        "snapshot_sha256": "abc123",
        "nodes": sorted(nodes.values(), key=lambda n: n["id"]),
        "edges": sorted(edges, key=lambda e: e["id"]),
        "components": [],
        "route_sources": {},
    }


def _edge(edge_id, coords, length_m=100.0):
    return {
        "id": edge_id,
        "from": edge_id + "_a",
        "to": edge_id + "_b",
        "coordinates": coords,
        "length_m": length_m,
        "provenance": {"route_id": "R", "prefecture": "tokushima", "source_file": "r.kml",
                       "source_fid": edge_id, "part": 1},
    }


def _anchored_graph(edges):
    """Same shape as _graph but carrying traversal_edges (anchored layer)."""
    data = _graph(edges)
    data["kind"] = "anchored_route_graph"
    data["traversal_edges"] = data.pop("edges")
    return data


ARUKIHENRO = _arukihenro([
    _route([1, 2], "01番～02番札所極楽寺　歩きへんろ道", [[[134.0, 33.000], [134.0, 33.005]]]),
    _route([2, 3], "02番～03番札所金泉寺　歩きへんろ道", [[[134.0, 33.010], [134.0, 33.015]]]),
    _route([88, 1], "88番札所～01番札所へんろ道", [[[134.0, 34.000], [134.0, 34.005]]]),
    _route([40, 41], "40番～41番札所龍光寺　歩きへんろ道", []),  # no KML upstream
])

GRAPH = _graph([
    _edge("SHE_1", [[134.0, 33.0002], [134.0, 33.0048]]),
    _edge("SHE_2", [[134.0, 33.0102], [134.0, 33.0148]]),
    _edge("SHE_3", [[134.0, 33.050], [134.0, 33.051]]),
    _edge("SHE_4", [[134.0, 33.008], [134.0, 33.012]]),
])


class TestBuildAttribution(unittest.TestCase):
    def test_reference_sections(self):
        result = build_attribution(ARUKIHENRO, GRAPH, None, 500.0)
        self.assertEqual(result["accounting"]["reference_sections"], 4)
        self.assertEqual(result["accounting"]["reference_sections_with_lines"], 3)
        self.assertEqual(result["accounting"]["reference_sections_missing"], 1)

    def test_edge_statuses(self):
        result = build_attribution(ARUKIHENRO, GRAPH, None, 500.0)
        by_id = {record["edge_id"]: record for record in result["edges"]}
        self.assertEqual(by_id["SHE_1"]["status"], "assigned_unique")
        self.assertEqual(by_id["SHE_1"]["nearest_section"], "SEC_1_2")
        self.assertEqual(by_id["SHE_2"]["status"], "assigned_unique")
        self.assertEqual(by_id["SHE_2"]["nearest_section"], "SEC_2_3")
        self.assertEqual(by_id["SHE_3"]["status"], "unattributed")
        self.assertEqual(by_id["SHE_3"]["nearest_section"], "SEC_2_3")
        self.assertEqual(by_id["SHE_4"]["status"], "ambiguous")
        self.assertEqual(len(by_id["SHE_4"]["within_buffer_sections"]), 2)

    def test_section_attribution(self):
        result = build_attribution(ARUKIHENRO, GRAPH, None, 500.0)
        by_section = {section["id"]: section for section in result["section_attribution"]}
        self.assertEqual(by_section["SEC_1_2"]["edge_ids"], ["SHE_1"])
        self.assertEqual(by_section["SEC_2_3"]["edge_ids"], ["SHE_2"])
        self.assertEqual(by_section["SEC_88_1"]["edge_ids"], [])

    def test_corridor_crosscheck(self):
        corridors = {"sections": [{
            "id": "SEC_1_2", "status": "corridor",
            "source_edge_ids": ["SHE_1", "SHE_OTHER"],
        }]}
        result = build_attribution(ARUKIHENRO, GRAPH, corridors, 500.0)
        cc = result["corridor_crosscheck"]
        self.assertEqual(cc["sections_compared"], 1)
        self.assertEqual(cc["total_intersection"], 1)
        self.assertEqual(cc["total_union"], 2)
        self.assertAlmostEqual(cc["jaccard"], 0.5)

    def test_deterministic(self):
        result = build_attribution(ARUKIHENRO, GRAPH, None, 500.0)
        again = build_attribution(ARUKIHENRO, GRAPH, None, 500.0)
        self.assertEqual(json.dumps(result, ensure_ascii=False, sort_keys=True),
                         json.dumps(again, ensure_ascii=False, sort_keys=True))

    def test_invalid_inputs(self):
        with self.assertRaises(ValueError):
            build_attribution({"schema_version": 99, "routes": []}, GRAPH, None, 500.0)
        with self.assertRaises(ValueError):
            build_attribution(ARUKIHENRO, {"kind": "other"}, None, 500.0)
        with self.assertRaises(ValueError):
            build_attribution(ARUKIHENRO, GRAPH, None, -1.0)
        with self.assertRaises(ValueError):
            build_attribution(ARUKIHENRO, GRAPH, None, 500.0, edge_layer="bogus")

    def test_traversal_edge_layer(self):
        anchored = _anchored_graph(GRAPH["edges"])
        result = build_attribution(ARUKIHENRO, anchored, None, 500.0, edge_layer="traversal")
        self.assertEqual(result["accounting"]["edge_layer"], "traversal")
        self.assertEqual(result["accounting"]["edges_total"], 4)
        by_id = {record["edge_id"]: record for record in result["edges"]}
        self.assertEqual(by_id["SHE_1"]["status"], "assigned_unique")
        self.assertEqual(by_id["SHE_1"]["nearest_section"], "SEC_1_2")
        self.assertEqual(by_id["SHE_3"]["status"], "unattributed")

    def test_traversal_crosscheck_uses_traversal_edge_ids(self):
        anchored = _anchored_graph(GRAPH["edges"])
        corridors = {"sections": [{
            "id": "SEC_1_2", "status": "corridor",
            "source_edge_ids": ["SHE_OTHER"],  # ignored for traversal layer
            "traversal_edge_ids": ["SHE_1", "SHE_OTHER"],
        }]}
        result = build_attribution(ARUKIHENRO, anchored, corridors, 500.0, edge_layer="traversal")
        cc = result["corridor_crosscheck"]
        self.assertEqual(cc["total_intersection"], 1)
        self.assertEqual(cc["total_union"], 2)
        self.assertAlmostEqual(cc["jaccard"], 0.5)


class TestRunAttribution(unittest.TestCase):
    def test_run_writes_output(self):
        from sekaiisan_henro.arukihenro_attribution import run_attribution
        with tempfile.TemporaryDirectory() as directory:
            arukihenro_path = os.path.join(directory, "arukihenro.json")
            graph_path = os.path.join(directory, "graph.json")
            output_path = os.path.join(directory, "attribution.json")
            with open(arukihenro_path, "w", encoding="utf-8") as stream:
                json.dump(ARUKIHENRO, stream, ensure_ascii=False)
            with open(graph_path, "w", encoding="utf-8") as stream:
                json.dump(GRAPH, stream, ensure_ascii=False)
            result = run_attribution(arukihenro_path, graph_path, None, 500.0, output_path)
            self.assertEqual(result["kind"], "arukihenro_attribution")
            self.assertTrue(os.path.isfile(output_path))


if __name__ == "__main__":
    unittest.main()