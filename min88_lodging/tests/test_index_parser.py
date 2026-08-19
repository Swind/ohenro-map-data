import os
import unittest

from min88_lodging.index_parser import extract_source_id, parse_index_document

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "index-list.html")


class IndexParserTests(unittest.TestCase):
    def test_numeric_japanese_detail_url_only(self):
        self.assertEqual(extract_source_id("https://min88.jp/inn/85/"), "85")
        self.assertEqual(extract_source_id("https://min88.jp/inn/85"), "85")
        self.assertIsNone(extract_source_id("http://min88.jp/inn/85/"))
        self.assertIsNone(extract_source_id("https://min88.jp/inn/foo/"))
        self.assertIsNone(extract_source_id("https://min88.jp/inn/85/?lang=en"))

    def test_context_variants_empty_exclusion_and_dedupe(self):
        with open(FIXTURE, encoding="utf-8") as source:
            result = parse_index_document(source.read())
        records = result["records"]
        self.assertEqual([r["source_id"] for r in records], ["85", "86", "132", "200", "300", "400"])
        self.assertEqual(len(result["occurrences"]), 7)
        first = records[0]
        self.assertEqual(first["temple_context"], {"number": 1, "name": "霊山寺", "locality": "鳴門市"})
        self.assertEqual(first["distance_text"], "⬇ 1.2km")
        self.assertEqual(first["closure_marker"], "《休業･閉業》")
        online = records[2]
        self.assertTrue(online["online_booking"])
        self.assertEqual(online["name"], "Guest House チャンネルカン")
        self.assertEqual(online["online_booking_label"], "24時間受付")
        self.assertEqual(online["distance_text"], "⬇ 7.0km")

    def test_requires_all_four_sections(self):
        html = '<div id="article"><div class="post_content"><h2 id="tokushima"></h2><a href="https://min88.jp/inn/1/">one</a></div></div>'
        with self.assertRaisesRegex(ValueError, "missing prefecture"):
            parse_index_document(html)


if __name__ == "__main__":
    unittest.main()
