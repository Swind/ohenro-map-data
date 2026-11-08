"""Source safety, place-cache identity, and consumer-visible geocode boundaries."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from datasets._pipeline import read_json
from datasets.henroyado.export_map import export_map
from datasets.henroyado.geocode import embed_url, enrich_file, parse_place
from datasets.henroyado.pipeline import normalized, snapshot, validate_html, write_jsonl


def full_html():
    groups = []
    for index, prefecture in enumerate(("tokushima", "kochi", "ehime", "kagawa")):
        captions = "".join(f'<caption class="js_temple_{number}">寺</caption>'
                           for number in range(index * 22 + 1, index * 22 + 23))
        groups.append(f'<div class="js_prefGroup" data-pref="{prefecture}"><table class="bl_table">'
                      + captions + '<tr class="bl_table_row_frontInfo"><td>宿</td><td></td><td></td><td></td><td></td></tr>'
                      '<tr class="bl_table_row_detail"><td><div class="bl_card_info"></div></td></tr></table></div>')
    return ("<html><body>" + "".join(groups) + "</body></html>").encode()


PLACE_HTML = ('<html><script>var _pageData = '
              '[["0x123:0x456","日本、徳島県",[34.1,134.5],"123"],"旅館"]'
              '</script></html>')


class UpdateBoundaryTest(unittest.TestCase):
    def test_truncated_page_cannot_replace_valid_selector(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            selected = snapshot(root, full_html())
            selector = read_json(root / "current.json")
            with self.assertRaises(ValueError):
                snapshot(root, full_html().replace(b"</body></html>", b""))
            self.assertEqual(read_json(root / "current.json"), selector)
            self.assertEqual((selected / "henroyado.html").read_bytes(), full_html())

    def test_missing_detail_row_cannot_be_silently_dropped(self):
        malformed = full_html().replace(b'class="bl_table_row_detail"', b'class="missing"', 1)
        with self.assertRaisesRegex(ValueError, "accounting"):
            validate_html(malformed)

    def test_normalization_is_deterministic_and_keeps_semantic_warnings(self):
        _, _, raw, _ = validate_html(full_html())
        raw[0]["route"] = "uncertain route"
        first, second = normalized(raw[0]), normalized(raw[0])
        self.assertEqual(first, second)
        self.assertIsNone(first["source"]["retrieved_at"])
        self.assertEqual(first["henro"]["raw_route_text"], "uncertain route")
        self.assertTrue(any(w["code"] == "UNRECOGNIZED_FORMAT" for w in first["_warnings"]))

    def test_changed_source_name_or_url_does_not_reuse_old_place(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / "cache"
            cache.mkdir()
            url = "http://maps.google.com/maps?q=old"
            legacy = cache / (hashlib.sha256(embed_url(url).encode()).hexdigest() + ".html")
            legacy.write_text(PLACE_HTML, encoding="utf-8")
            _, _, raw, _ = validate_html(full_html())
            raw[0]["google_maps_search_url"] = url
            old = normalized(raw[0])
            source, target, geojson = root / "source.jsonl", root / "enriched.jsonl", root / "map.geojson"
            write_jsonl(source, [old])
            self.assertEqual(enrich_file(source, target, cache, delay=0)["geocoded"], 1)
            self.assertEqual(export_map(target, geojson)["features"], 1)
            previous = target.read_bytes()
            for name, changed_url in (("new name", url), ("宿", url + "-changed")):
                changed = json.loads(json.dumps(old))
                changed["identity"]["name"] = name
                changed["location"]["google_maps_search_url"] = changed_url
                write_jsonl(source, [changed])
                with patch("urllib.request.urlopen", side_effect=OSError("offline")):
                    self.assertEqual(enrich_file(source, target, cache, delay=0)["errors"], 1)
                self.assertEqual(target.read_bytes(), previous)
                failed_target = root / ("failed-" + hashlib.sha256(changed_url.encode() + name.encode()).hexdigest() + ".jsonl")
                with patch("urllib.request.urlopen", side_effect=OSError("offline")):
                    stats = enrich_file(source, failed_target, cache, delay=0)
                self.assertEqual(stats["errors"], 1)
                enriched = json.loads(failed_target.read_text())
                self.assertEqual(enriched["location"]["map_data_status"], "fetch_failed")
                self.assertIsNone(enriched["location"]["coordinates"])
                self.assertEqual(export_map(failed_target, geojson)["features"], 0)

    def test_viewport_coordinates_are_not_a_place(self):
        self.assertIsNone(parse_place('<html>[[3301.4,134.5,34.1]]</html>',
                                     "https://maps.google.com/maps?ll=34.1,134.5&z=12"))
