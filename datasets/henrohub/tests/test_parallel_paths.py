import importlib.util
from pathlib import Path
import unittest


class ParallelPathTests(unittest.TestCase):
    def test_collapsed_alternatives_keep_distinct_geometry_ids(self):
        script = Path(__file__).resolve().parents[1] / "scripts" / "build-henrohub-plan-graph.py"
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


if __name__ == "__main__":
    unittest.main()
