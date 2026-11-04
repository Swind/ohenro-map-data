import os
import unittest

from datasets.mizutani_henro_map.categories import classify
from datasets.mizutani_henro_map.parser import icon_details, parse_kml, resolve_style


class TestParser(unittest.TestCase):
    def setUp(self):
        fixture = os.path.join(os.path.dirname(__file__), "fixtures", "map.kml")
        with open(fixture, "rb") as stream:
            self.parsed = parse_kml(stream.read())

    def test_folder_geometry_and_style_map_are_preserved(self):
        point, line = self.parsed["placemarks"]
        self.assertEqual(point["folder_path"], ["Outer", "Inner"])
        self.assertEqual(point["geometries"][0]["coordinates"], [133.5, 33.5, 10.0])
        self.assertEqual(line["geometries"][0]["type"], "LineString")
        style = resolve_style(point["style_url"], self.parsed["styles"], self.parsed["style_maps"])
        self.assertEqual(style["icon_color"]["rgb"], "#C2185B")

    def test_icon_details_use_source_style_url(self):
        self.assertEqual(icon_details("#icon-1602-C2185B"), {"icon_id": "1602", "color": "#C2185B"})
        self.assertEqual(icon_details("#icon-1567-FF5252-nodesc"), {"icon_id": "1567", "color": "#FF5252"})
        self.assertEqual(icon_details("#line-blue"), {"icon_id": None, "color": None})

    def test_invalid_coordinates_fail(self):
        with self.assertRaisesRegex(ValueError, "outside valid"):
            parse_kml(b"<kml><Document><Placemark><Point><coordinates>200,33</coordinates></Point></Placemark></Document></kml>")

    def test_classification_prefers_exact_style_over_icon(self):
        categories = {
            "icons": {"1602": {"category": "lodging", "icon": "lodging"}},
            "style_overrides": {"#icon-1602-C2185B": {"category": "food", "icon": "food"}},
        }
        self.assertEqual(classify("#icon-1602-C2185B", categories), {"category": "food", "icon": "food"})
        self.assertEqual(classify("#icon-1602-123456", categories), {"category": "lodging", "icon": "lodging"})
        self.assertEqual(classify("#line-blue", categories), {"category": "unclassified", "icon": "other"})
