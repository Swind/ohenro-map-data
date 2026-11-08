import json
import os
import shutil
import tempfile
import unittest

from datasets.mizutani_henro_map.export_map import export_map
from datasets.mizutani_henro_map.diff import generate_update_report
from datasets.mizutani_henro_map.normalize import normalize
from datasets.mizutani_henro_map.verify import verify


class TestNormalize(unittest.TestCase):
    def test_normalize_and_export_account_for_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot = "test"
            snapshot_dir = os.path.join(directory, "snapshots", snapshot)
            os.makedirs(snapshot_dir)
            fixture = os.path.join(os.path.dirname(__file__), "fixtures", "map.kml")
            shutil.copyfile(fixture, os.path.join(snapshot_dir, "map.kml"))
            with open(os.path.join(snapshot_dir, "metadata.json"), "w", encoding="utf-8") as stream:
                json.dump({"map_id": "map", "title": "title", "author": "author", "source_map_url": "https://example.test/map", "source_article_url": "https://example.test/article", "retrieved_at": "2026-08-22T00:00:00Z"}, stream)
            output = os.path.join(directory, "normalized.json")
            normalized = normalize(directory, snapshot=snapshot, output=output)
            report = export_map(output, routes_path=os.path.join(directory, "routes.geojson"), pois_path=os.path.join(directory, "pois.geojson"), report_path=os.path.join(directory, "report.json"))
            self.assertEqual(normalized["summary"]["feature_count"], 2)
            self.assertEqual(normalized["features"][0]["folder_path"], ["Outer", "Inner"])
            self.assertEqual(normalized["features"][0]["description"], "Example")
            self.assertEqual(normalized["features"][1]["line_color"], "#0000FF")
            self.assertEqual(report["routes"], 1)
            self.assertEqual(report["pois"], 1)
            with open(os.path.join(directory, "routes.geojson"), encoding="utf-8") as stream:
                route_features = json.load(stream)["features"]
            self.assertEqual(len(route_features), 1)
            route_props = route_features[0]["properties"]
            self.assertEqual(route_props["route_id"], route_props["feature_id"])
            self.assertEqual(route_props["segment_id"], route_props["feature_id"])
            checked = verify(directory, snapshot=snapshot, normalized_path=output,
                             routes_path=os.path.join(directory, "routes.geojson"),
                             pois_path=os.path.join(directory, "pois.geojson"))
            self.assertTrue(checked["ok"], checked["errors"])
            update = generate_update_report(directory, snapshot, snapshot, os.path.join(directory, "update.json"))
            self.assertEqual(update["features"], {"added": [], "removed": [], "changed": []})
            route_features[0]["geometry"]["coordinates"][0][0] += 0.01
            with open(os.path.join(directory, "routes.geojson"), "w", encoding="utf-8") as stream:
                json.dump({"type": "FeatureCollection", "features": route_features}, stream)
            corrupted = verify(directory, snapshot=snapshot, normalized_path=output,
                               routes_path=os.path.join(directory, "routes.geojson"),
                               pois_path=os.path.join(directory, "pois.geojson"),
                               report_path=os.path.join(directory, "report.json"))
            self.assertFalse(corrupted["ok"])
            self.assertTrue(any("geometry differ" in error for error in corrupted["errors"]))
