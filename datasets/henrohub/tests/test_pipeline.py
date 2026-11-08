import json
from pathlib import Path
import tempfile
import unittest

from datasets._pipeline import read_json
from datasets.henrohub import downloader
from datasets.henrohub.__main__ import script
from datasets.henrohub.validation import validate_graph, validate_routes


def feature(rid="main", role="canonical_shikoku88", longitude=133.0):
    return {"type": "Feature", "id": rid,
            "properties": {"route_feature_id": rid, "route_role": role,
                           "effective_route_class": "black", "route_set_ids": ["henro-network"],
                           "length_m": 100},
            "geometry": {"type": "LineString", "coordinates": [[longitude, 33.0, 10], [longitude + .001, 33.0, 20]]}}


def collection(*features):
    return {"type": "FeatureCollection", "features": list(features)}


class SourceBoundaryTests(unittest.TestCase):
    def test_invalid_import_preserves_current_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "archived.geojson"
            source.write_text(json.dumps(collection(feature())))
            snapshot = downloader.fetch(root / "raw", source)
            selector = read_json(root / "raw/current.json")
            source.write_text(json.dumps(collection(feature(), feature())))
            with self.assertRaisesRegex(ValueError, "duplicate route ID"):
                downloader.fetch(root / "raw", source)
            self.assertEqual(selector, read_json(root / "raw/current.json"))
            self.assertEqual(snapshot, downloader.resolve(root / "raw"))

    def test_manifest_hash_is_enforced_before_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            staged = Path(directory)
            data = collection(feature())
            (staged / "planner.geojson").write_text(json.dumps(data))
            channel = {"schema": "henro-route-release-channel", "channel": "beta", "active_release_id": "release-current",
                       "manifest": "/routes/releases/release-current/manifest.json"}
            manifest = {"schema": "henro-route-production-release", "immutable_release_id": "release-current",
                        "planner": {"available": True, "geometry": "planner/route.planner.geojson", "feature_count": 1,
                                    "coordinate_dimensions": 3},
                        "files": {"planner_geometry": "planner/route.planner.geojson"},
                        "deployed_files": {"planner/route.planner.geojson": {"path": "planner/route.planner.geojson",
                                                                             "sha256": "0" * 64}}}
            for name, value in (("channel.json", channel), ("manifest.json", manifest)):
                (staged / name).write_text(json.dumps(value))
            from datasets._pipeline import digest
            files = {name: {"size": (staged / name).stat().st_size, "sha256": digest(staged / name)}
                     for name in ("planner.geojson", "channel.json", "manifest.json")}
            metadata = {"kind": "public-release", "release_id": "release-current", "files": files,
                        "source_url": "https://assets.henro.app/routes/releases/release-current/planner/route.planner.geojson",
                        "summary": validate_routes(data, planner=True)}
            (staged / "metadata.json").write_text(json.dumps(metadata))
            with self.assertRaisesRegex(ValueError, "hash/size differs"):
                downloader.verify_snapshot(staged)

    def test_invalid_geometry_cannot_disappear_from_routes(self):
        converter = script("build-henrohub-routes.py")
        with tempfile.TemporaryDirectory() as directory:
            source, destination = Path(directory) / "source.json", Path(directory) / "routes.json"
            for invalid in ({"type": "Point", "coordinates": [133, 33, 0]},
                            {"type": "LineString", "coordinates": [[133, 33, 0], [float("nan"), 33, 1]]}):
                data = collection(feature())
                data["features"][0]["geometry"] = invalid
                source.write_text(json.dumps(data))
                with self.assertRaises(ValueError):
                    converter.convert(str(source), str(destination))
                self.assertFalse(destination.exists())

    def test_graph_excludes_glue_and_keeps_source_elevation(self):
        converter, builder = script("build-henrohub-routes.py"), script("build-henrohub-plan-graph.py")
        data = collection(feature(), feature("alternative", "unique_alternative", 133.01),
                          feature("connector", "transition_connector", 134), feature("fallback", "continuity_fallback", 134.01))
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / "source.json", Path(directory) / "routes.json"
            source.write_text(json.dumps(data))
            converter.convert(str(source), str(output))
            routes = read_json(output)
            graph = builder._build(builder._line_parts(routes["features"]), 30, 3)
            validate_graph(graph, routes)
            self.assertEqual(graph["accounting"]["segments"], 2)
            self.assertTrue(all(node["lon"] < 133.1 for node in graph["nodes"]))
            self.assertEqual({point[2] for coordinates in graph["edge_geometry"].values() for point in coordinates}, {10, 20})

    def test_interior_join_interpolates_elevation(self):
        builder = script("build-henrohub-plan-graph.py")
        edges = [{"id": "road", "from": "a", "to": "b", "length_m": 200,
                  "coordinates": [[133, 33, 10], [133.002, 33, 30]]},
                 {"id": "feeder", "from": "c", "to": "d", "length_m": 100,
                  "coordinates": [[133.001, 33.00005, 99], [133.001, 33.001, 100]]}]
        nodes = {"a": [133, 33], "b": [133.002, 33], "c": [133.001, 33.00005], "d": [133.001, 33.001]}
        split, joins = builder._proximity_joins(edges, nodes, {"c"}, 30)
        self.assertEqual(len(joins), 1)
        self.assertEqual(len(split), 3)
        road = [edge for edge in split if edge["id"] != "feeder"]
        self.assertTrue(all(len(point) == 3 for edge in road for point in edge["coordinates"]))
        self.assertAlmostEqual(road[0]["coordinates"][-1][2], 20)
        self.assertAlmostEqual(road[1]["coordinates"][0][2], 20)


if __name__ == "__main__":
    unittest.main()
