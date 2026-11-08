import importlib.util
from pathlib import Path
import unittest


class ParallelPathTests(unittest.TestCase):
    def test_collapsed_alternatives_keep_distinct_geometry_ids(self):
        script = Path(__file__).resolve().parents[1] / "scripts" / "build-ohenro88-plan-graph.py"
        spec = importlib.util.spec_from_file_location("route_builder_parallel", script)
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        points = {"a": [133.0, 33.0, 10.0], "upper": [133.001, 33.001, 12.0],
                  "lower": [133.001, 32.999, 8.0], "b": [133.002, 33.0, 10.0]}
        edges = [{"id": f"edge-{i}", "from": a, "to": b, "length_m": 100.0,
                  "coordinates": [points[a], points[b]]}
                 for i, (a, b) in enumerate((("a", "upper"), ("upper", "b"),
                                             ("a", "lower"), ("lower", "b")))]
        collapsed, _ = builder._simplify(edges, {"a", "b"}, {key: p[:2] for key, p in points.items()})
        geometry = {edge["id"]: edge["coordinates"] for edge in collapsed}
        self.assertEqual(len(collapsed), 2)
        self.assertEqual(len(geometry), 2)
        self.assertEqual({tuple(edge["coordinates"][1]) for edge in collapsed},
                         {tuple(points["upper"]), tuple(points["lower"])})
        for edge in collapsed:
            self.assertEqual(geometry[edge["id"]], edge["coordinates"])

    def test_existing_node_on_edge_interior_splits_without_self_join(self):
        script = Path(__file__).resolve().parents[1] / "scripts" / "build-ohenro88-plan-graph.py"
        spec = importlib.util.spec_from_file_location("route_builder_contact", script)
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        a, contact, b = [133.0, 33.0], [133.001, 33.0], [133.002, 33.0]
        ids = [builder._node_id(*point) for point in (a, contact, b)]
        edge = {"id": "source-edge", "from": ids[0], "to": ids[2],
                "length_m": builder._edge_metric({"coordinates": [a, b]})["length"],
                "coordinates": [a, b]}
        edges, joins = builder._proximity_joins([edge], dict(zip(ids, (a, contact, b))), {ids[1]}, 90.0)
        self.assertEqual(joins, [])
        self.assertEqual({(e["from"], e["to"]) for e in edges}, {(ids[0], ids[1]), (ids[1], ids[2])})
        self.assertAlmostEqual(sum(e["length_m"] for e in edges), edge["length_m"], places=5)


if __name__ == "__main__":
    unittest.main()
