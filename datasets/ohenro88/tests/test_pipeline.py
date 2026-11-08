"""Offline boundary regressions for app asset identity and consumer outputs."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from datasets.ohenro88 import downloader
from datasets.ohenro88.__main__ import graph_builder, validate_graph
from datasets.ohenro88.reference.build_reference import build_data


def assets():
    points = [{"type": "Feature", "properties": {"name": f"Temple {i}", "templeNumber": i},
               "geometry": {"type": "Point", "coordinates": [134, 34]}} for i in range(1, 89)]
    lines = [{"type": "Feature", "properties": {"name": f"Walking ({i}-{i+1 if i<88 else 1})"},
              "geometry": {"type": "LineString", "coordinates": [[134, 34, 1], [134.001, 34, 2]]}}
             for i in range(1, 89)]
    return {"trails_all.geojson": {"type": "FeatureCollection", "features": points + lines[:-1]},
            "merged.json": {"type": "FeatureCollection", "features": lines}}


def write_apk(path, data, package=downloader.PACKAGE, version=24):
    manifest = (f'<manifest xmlns:android="http://schemas.android.com/apk/res/android" '
                f'package="{package}" android:versionCode="{version}" android:versionName="1.1.0"/>')
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("AndroidManifest.xml", manifest)
        for name, body in data.items():
            archive.writestr(downloader.ASSET_PREFIX + name, json.dumps(body))


class SourceBoundaryTests(unittest.TestCase):
    def test_local_apk_extracts_assets_with_manifest_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "app.apk"
            write_apk(archive, assets())
            identity, checksums = downloader.validate_archive(archive, output=Path(directory) / "data")
            self.assertEqual(identity, {"package_name": downloader.PACKAGE, "version_code": 24, "version_name": "1.1.0"})
            self.assertEqual(set(checksums), set(downloader.ASSETS))
            self.assertEqual(json.loads((Path(directory) / "data/merged.json").read_text()), assets()["merged.json"])

    def test_wrong_package_and_version_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "app.apk"
            write_apk(archive, assets(), package="com.other.app")
            with self.assertRaisesRegex(ValueError, "identity"):
                downloader.validate_archive(archive)
            write_apk(archive, assets(), version=23)
            with self.assertRaisesRegex(ValueError, "version code"):
                downloader.validate_archive(archive, {"version_code": 24, "version_name": "1.1.0"})

    def test_incomplete_archive_does_not_replace_current_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "app.apk"
            write_apk(archive, assets())
            previous = downloader.fetch(root / "raw", archive)
            selector = (root / "raw/current.json").read_bytes()
            incomplete = assets()
            incomplete["merged.json"]["features"].pop()
            write_apk(archive, incomplete)
            with self.assertRaisesRegex(ValueError, "merged main section 88"):
                downloader.fetch(root / "raw", archive)
            self.assertEqual((root / "raw/current.json").read_bytes(), selector)
            self.assertEqual(downloader.resolve(root / "raw"), previous)

    def test_missing_temples_and_nonfinite_coordinates_fail(self):
        data = assets()
        data["trails_all.geojson"]["features"].pop(0)
        with self.assertRaisesRegex(ValueError, "temples 1"):
            downloader.validate_assets(data)
        data = assets()
        data["merged.json"]["features"][0]["geometry"]["coordinates"][0][2] = float("nan")
        with self.assertRaisesRegex(ValueError, "coordinate"):
            downloader.validate_assets(data)

    def test_cached_archive_corruption_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "app.apk"
            write_apk(archive, assets())
            snapshot = downloader.fetch(root / "raw", archive)
            with (snapshot / "archive.apk").open("ab") as stream:
                stream.write(b"corrupted")
            with self.assertRaisesRegex(ValueError, "hash/size mismatch"):
                downloader.resolve(root / "raw")

    def test_consumer_sections_preserve_closure_and_real_version(self):
        data = assets()
        metadata = {"package_name": downloader.PACKAGE, "version_name": "2.0", "version_code": 25,
                    "archive_sha256": "a" * 64}
        routes, sections = build_data(data["trails_all.geojson"], data["merged.json"], metadata)
        self.assertEqual(len(routes["features"]), 176)
        self.assertEqual(len(sections["sections"]), 87)
        self.assertEqual(sections["closure_88_1"]["geometry"], data["merged.json"]["features"][-1]["geometry"])
        self.assertEqual(sections["source"], metadata)
        self.assertIn("2.0", sections["dataset"])


class GraphBoundaryTests(unittest.TestCase):
    def test_real_schema_weights_and_accounting_are_checked(self):
        features = [{"type": "Feature", "properties": {"kind": "line", "route_id": "A"},
                     "geometry": {"type": "LineString", "coordinates": [[134, 34], [134.001, 34]]}}]
        graph = graph_builder._build(graph_builder._line_parts(features), 90.0, 3.0)
        self.assertEqual(validate_graph(graph, features)["edges"], 1)
        corrupted = copy.deepcopy(graph)
        corrupted["traversal_edges"][0]["length_m"] *= 2
        with self.assertRaisesRegex(ValueError, "weight differs"):
            validate_graph(corrupted, features)
        corrupted = copy.deepcopy(graph)
        corrupted["accounting"]["geometry_points"] += 1
        with self.assertRaisesRegex(ValueError, "accounting"):
            validate_graph(corrupted, features)

    def test_synthetic_join_uses_distance_weight_not_traversal_length(self):
        features = [
            {"type": "Feature", "properties": {"kind": "line", "route_id": name},
             "geometry": {"type": "LineString", "coordinates": coords}}
            for name, coords in (
                ("A", [[134, 34], [134.001, 34]]),
                ("B", [[134.0011, 34], [134.002, 34]]),
            )
        ]
        graph = graph_builder._build(graph_builder._line_parts(features), 90.0, 0.1)
        self.assertTrue(graph["synthetic_joins"])
        self.assertEqual(validate_graph(graph, features)["nodes"], 4)


if __name__ == "__main__":
    unittest.main()
