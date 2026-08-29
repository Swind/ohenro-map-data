import unittest
import os
import tempfile
from unittest.mock import patch

from arukihenro_routes.fetch import _fetch, _validate_kml
from arukihenro_routes.parser import parse_index, parse_route


class TestParser(unittest.TestCase):
    def test_extracts_only_walking_route_links(self):
        html = '<a href="/blog/arukihenro/junnro/michi01to02/">route</a><a href="/blog/arukihenro/michi45to46/">other form</a><a href="/blog/arukihenro/tera-tokushima/">other</a>'
        self.assertEqual(
            parse_index(html, "https://ohenro.jp/blog/arukihenro/tera-tokushima/"),
            [
                "https://ohenro.jp/blog/arukihenro/junnro/michi01to02/",
                "https://ohenro.jp/blog/arukihenro/michi45to46/",
            ],
        )

    def test_extracts_title_and_unique_google_map_ids(self):
        html = '<h1 class="entry-title">01番札所～02番札所</h1><iframe src="https://www.google.com/maps/d/u/2/embed?mid=abc"></iframe><iframe src="https://www.google.com/maps/d/embed?mid=abc"></iframe>'
        parsed = parse_route(html, "https://ohenro.jp/blog/arukihenro/junnro/michi01to02/")
        self.assertEqual(parsed["title"], "01番札所～02番札所")
        self.assertEqual(parsed["maps"], [{"embed_url": "https://www.google.com/maps/d/u/2/embed?mid=abc", "map_id": "abc", "kml_url": "https://www.google.com/maps/d/kml?mid=abc&forcekml=1"}])

    def test_invalid_kml_is_not_cached(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "map.kml")
            with patch("arukihenro_routes.fetch._get", return_value=b"<html>error</html>"):
                with self.assertRaisesRegex(ValueError, "not KML"):
                    _fetch("https://example.test/map", path, 1, 0, False, _validate_kml)
            self.assertFalse(os.path.exists(path))
