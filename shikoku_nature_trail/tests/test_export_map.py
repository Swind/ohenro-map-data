import json
import os
import tempfile
import unittest
from unittest.mock import patch

from shikoku_nature_trail.cli import main
from shikoku_nature_trail.export_map import export_map


def dataset(geometry=None):
    placemarks = [
        {"name": "route-a", "geometry": geometry or {
            "type": "LineString", "coordinates": [[134.0, 34.0], [134.1, 34.1]]}},
        {"name": "route-b", "geometry": {
            "type": "LineString", "coordinates": [[134.1, 34.1], [134.2, 34.2]]}},
        {"name": "展望台 （北）", "geometry": {"type": "Point", "coordinates": [134.1, 34.1]}},
        {"name": "重複", "geometry": {"type": "Point", "coordinates": [134.2, 34.2]}},
        {"name": "重複", "geometry": {"type": "Point", "coordinates": [134.3, 34.3]}},
        {"name": "POI only", "geometry": {"type": "Point", "coordinates": [134.4, 34.4]}},
    ]
    return {
        "schema_version": 1,
        "source": "https://shikoku-nature-trail.com/",
        "courses": [{
            "source_post_id": 42, "prefecture": "kochi", "course_number": "7",
            "name_ja": "Course", "distance_km": 4.2, "difficulty": 2,
            "photo_point": {"title": "展望台（北）"},
            "tourism_spots": [
                {"number": "1", "title": "展望台【北】"},
                {"number": "2", "title": "重複"},
                {"number": "3", "title": "spot only"},
            ],
            "kml": {"placemarks": placemarks},
        }],
    }


class TestExportMap(unittest.TestCase):
    def run_export(self, value):
        root = tempfile.TemporaryDirectory()
        paths = [os.path.join(root.name, name) for name in
                 ("input.json", "routes.json", "pois.json", "report.json")]
        with open(paths[0], "w", encoding="utf-8") as file:
            json.dump(value, file)
        export_map(*paths)
        return root, paths

    def test_stable_ids_segments_links_and_determinism(self):
        root, paths = self.run_export(dataset())
        self.addCleanup(root.cleanup)
        with open(paths[1], encoding="utf-8") as file:
            routes = json.load(file)["features"]
        with open(paths[2], encoding="utf-8") as file:
            pois = json.load(file)["features"]
        with open(paths[3], encoding="utf-8") as file:
            report = json.load(file)
        self.assertEqual([f["properties"]["segment_id"] for f in routes],
                         ["SNT_42_L001", "SNT_42_L002"])
        self.assertEqual(routes[0]["properties"]["seg_count"], 2)
        self.assertEqual([f["properties"]["poi_id"] for f in pois],
                         ["SNT_42_P0001", "SNT_42_P0002", "SNT_42_P0003", "SNT_42_P0004"])
        self.assertEqual(pois[0]["properties"]["content_id"], "SNT_42_S001")
        self.assertIsNone(pois[1]["properties"]["content_id"])
        self.assertEqual(report["totals"]["linked_tourism_spots"], 1)
        self.assertEqual(report["totals"]["unmatched_tourism_spots"], 2)
        self.assertEqual(report["totals"]["unmatched_pois"], 3)
        self.assertEqual(report["totals"]["ambiguous_names"], 1)
        self.assertEqual(report["by_prefecture"]["kochi"]["matched_photo_points"], 1)
        first = []
        for path in paths[1:]:
            with open(path, "rb") as file:
                first.append(file.read())
        export_map(*paths)
        second = []
        for path in paths[1:]:
            with open(path, "rb") as file:
                second.append(file.read())
        self.assertEqual(second, first)

    def test_malformed_geometry_is_fatal(self):
        for geometry in (
            {"type": "LineString", "coordinates": [[134, 34]]},
            {"type": "Polygon", "coordinates": []},
            {"type": "Point", "coordinates": [999, 34]},
        ):
            with self.subTest(geometry=geometry):
                root = tempfile.TemporaryDirectory()
                self.addCleanup(root.cleanup)
                paths = [os.path.join(root.name, name) for name in
                         ("input.json", "routes.json", "pois.json", "report.json")]
                with open(paths[0], "w", encoding="utf-8") as file:
                    json.dump(dataset(geometry), file)
                with self.assertRaises(ValueError):
                    export_map(*paths)

    def test_invalid_schema_is_fatal(self):
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        paths = [os.path.join(root.name, name) for name in
                 ("input.json", "routes.json", "pois.json", "report.json")]
        with open(paths[0], "w", encoding="utf-8") as file:
            json.dump({"schema_version": 2, "courses": []}, file)
        with self.assertRaises(ValueError):
            export_map(*paths)

    def test_cli_does_not_construct_http_client(self):
        with tempfile.TemporaryDirectory() as root:
            paths = [os.path.join(root, name) for name in
                     ("input.json", "routes.json", "pois.json", "report.json")]
            with open(paths[0], "w", encoding="utf-8") as file:
                json.dump(dataset(), file)
            args = ["export-map", "--input", paths[0], "--routes", paths[1],
                    "--pois", paths[2], "--report", paths[3]]
            with patch("shikoku_nature_trail.cli._make_client",
                       side_effect=AssertionError("network client constructed")):
                self.assertEqual(main(args), 0)


if __name__ == "__main__":
    unittest.main()
