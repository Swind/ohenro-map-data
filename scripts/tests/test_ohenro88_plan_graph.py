"""Regression tests for scripts/build-ohenro88-plan-graph.py.

Uses small synthetic route sections (no app archive required), so the tests
run offline anywhere.
"""

import importlib.util
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "build-ohenro88-plan-graph.py")
_spec = importlib.util.spec_from_file_location("ohenro88_plan_graph", _SCRIPT)
_builder = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_builder)
_build = _builder._build  # noqa: E402


def _line(a, b, step=0.001, lat_offset=0.0):
    """Straight lon sweep from a to b with an optional lat offset."""
    coords = []
    x = a
    while x <= b + 1e-12:
        coords.append([round(x, 6), round(33.0 + lat_offset, 6)])
        x += step
    return coords


def _seg(route_id, coords):
    return (route_id, coords)


def _union_find_components(edges, node_ids):
    parent = {n: n for n in node_ids}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for e in edges:
        union(e["from"], e["to"])
    roots = {find(n) for n in node_ids}
    return len(roots), {find(n) for n in node_ids}


class TestBuild(unittest.TestCase):
    def test_overlapping_sections_merge_into_one_component(self):
        # Two sections trace the same path with a ~1.1m lat offset: within the
        # 15m merge radius, so they must end up in the same routing component.
        a = _seg("A", _line(133.0, 133.01))
        b = _seg("B", _line(133.0, 133.01, lat_offset=0.00001))
        graph = _build([a, b], 0.0, 15.0)
        nodes = {n["id"] for n in graph["nodes"]}
        comps, roots = _union_find_components(graph["traversal_edges"], nodes)
        self.assertEqual(comps, 1)

    def test_chain_collapse_removes_interior_vertices(self):
        # A single straight section with many intermediate vertices and no
        # junctions collapses to one edge between its two endpoints.
        seg = _seg("R1", _line(133.0, 133.01))
        graph = _build([seg], 0.0, 15.0)
        self.assertEqual(len(graph["nodes"]), 2)
        self.assertEqual(len(graph["traversal_edges"]), 1)
        edge = graph["traversal_edges"][0]
        self.assertGreater(edge["length_m"], 900.0)

    def test_no_zero_length_or_self_loop_edges(self):
        a = _seg("A", _line(133.0, 133.01))
        b = _seg("B", _line(133.0, 133.01, lat_offset=0.00001))
        graph = _build([a, b], 0.0, 15.0)
        for e in graph["traversal_edges"]:
            self.assertGreater(e["length_m"], 0.0)
            self.assertNotEqual(e["from"], e["to"])
            self.assertGreaterEqual(len(e["coordinates"]), 2)

    def test_collapsed_edge_direction_matches_node_ids(self):
        # A collapsed edge's coordinates must start at `from` and end at `to`
        # (within the merge radius); a reversed concatenation makes the drawn
        # path jump off the route.
        seg = _seg("R1", _line(133.0, 133.01))
        graph = _build([seg], 0.0, 15.0)
        node_coords = {n["id"]: (n["lon"], n["lat"]) for n in graph["nodes"]}
        for e in graph["traversal_edges"]:
            c0 = e["coordinates"][0]
            cn = e["coordinates"][-1]
            for coord, nid in ((c0, e["from"]), (cn, e["to"])):
                self.assertAlmostEqual(coord[0], node_coords[nid][0], delta=0.0005)
                self.assertAlmostEqual(coord[1], node_coords[nid][1], delta=0.0005)

    def test_deterministic_output(self):
        segs = [
            _seg("A", _line(133.0, 133.005)),
            _seg("B", _line(133.0, 133.005, lat_offset=0.00001)),
        ]
        one = _build(segs, 0.0, 15.0)
        two = _build(segs, 0.0, 15.0)
        self.assertEqual(
            json.dumps(one, sort_keys=True),
            json.dumps(two, sort_keys=True),
        )


if __name__ == "__main__":
    unittest.main()