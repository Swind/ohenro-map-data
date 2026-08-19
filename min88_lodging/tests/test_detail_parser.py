import os
import unittest

from min88_lodging.html_parser.detail import extract_detail, parse_detail_html
from min88_lodging.model.raw import RawMin88Lodging


FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def parse_fixture(name, context=None):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return parse_detail_html(handle.read(), context or {
            "source_id": "85",
            "source_url": "https://min88.jp/inn/85/",
            "name": "旅人の宿・道しるべ",
            "prefecture": "tokushima",
        })


class TestDetailParser(unittest.TestCase):
    def test_extracts_observed_page_85_structure(self):
        raw = parse_fixture("detail85.html")
        self.assertIsInstance(raw, RawMin88Lodging)
        self.assertEqual(raw.canonical_source_id, "85")
        self.assertEqual(raw.source_context["list_name"], "旅人の宿・道しるべ")
        self.assertNotIn("name", raw.source_context)
        self.assertEqual(raw.name, "旅人の宿・道しるべ")
        self.assertEqual(raw.modified_text, "最終更新日：2026年6月20日")
        self.assertEqual(raw.categories, ["03 金泉寺", "徳島"])
        self.assertEqual(raw.lodging_types, ["民宿･ゲストハウス"])
        self.assertEqual(raw.route_lines, [{
            "lnum": "03", "lname": "金泉寺", "lkm": "1.2",
            "rnum": "04", "rname": "大日寺", "rkm": "5.3",
        }])
        self.assertEqual(raw.basic_data["website"], "https://example.test/path?a=b")
        self.assertEqual(raw.basic_data["price"], "素泊り：個室4,200円|朝食付：+525円")
        self.assertEqual(raw.basic_data_ignored_lines, ["# ===== 基本情報 ====="])
        self.assertEqual(raw.supplemental_facilities, ["禁煙ルーム", "送迎バス"])
        self.assertEqual(raw.editorial_title, "温かな木の香りに迎えられる、\n遍路を支える小さな拠点")
        self.assertEqual(raw.editorial_description, "木の温もりが漂う宿です。\n歩き旅を支えます。")

    def test_images_maps_and_languages_are_scoped_and_classified(self):
        raw = parse_fixture("detail85.html")
        self.assertEqual(raw.featured_image_url, "https://min88.jp/inn/wp-content/uploads/2024/02/featured.jpg")
        self.assertEqual(raw.featured_image_display_url, "https://min88.jp/inn/wp-content/uploads/2024/02/featured-860x611.jpg")
        self.assertEqual(raw.gallery_image_urls, [
            "https://min88.jp/inn/wp-content/uploads/guest-1.jpg",
            "https://min88.jp/inn/wp-content/uploads/guest-2.jpg",
        ])
        self.assertIn("!1m18", raw.google_maps_place_embed_url)
        self.assertIn("!6m8", raw.google_street_view_embed_url)
        self.assertIn("/maps/dir/", raw.google_maps_directions_url)
        self.assertEqual([item["source_id"] for item in raw.alternate_languages], ["85", "11726", "30094"])
        self.assertNotIn("WRONG", str(raw.to_dict()))
        self.assertNotIn("banner.jpg", str(raw.to_dict()))
        self.assertNotIn("review.jpg", str(raw.to_dict()))
        self.assertEqual(raw.unknown_sections, [{
            "heading": "地域からのお知らせ",
            "text": "橋は午後5時に閉まります。\n詳細",
            "links": ["https://min88.jp/inn/local-note"],
            "image_urls": ["https://min88.jp/inn/wp-content/uploads/local-note.jpg"],
        }])
        self.assertIn("UNKNOWN_CONTENT_SECTION", [warning["code"] for warning in raw.parser_warnings])

    def test_google_urls_require_an_explicit_google_maps_hostname(self):
        html = '''<div id="article"><h1 id="post_title">宿</h1>
        <div class="min88-basicdata-pack"><textarea class="min88-basicdata-kv">address=x</textarea></div>
        <iframe src="https://evilgoogle.com/maps/embed?pb=!1m18"></iframe>
        <a href="https://evilgoogle.com/maps/dir/?api=1">route</a></div>'''
        raw = parse_detail_html(html, {"source_id": "1", "source_url": "https://min88.jp/inn/1/"})
        self.assertIsNone(raw.google_maps_place_embed_url)
        self.assertIsNone(raw.google_maps_directions_url)

    def test_duplicate_unknown_and_mismatches_are_retained_as_warnings(self):
        raw = parse_fixture("detail_edge.html", {
            "source_id": "85", "source_url": "https://min88.jp/inn/85/", "name": "一覧の宿名",
        })
        self.assertEqual(raw.basic_data, {"address": "first"})
        self.assertEqual(raw.extra_fields, [
            {"key": "address", "value": "second", "reason": "duplicate"},
            {"key": "custom", "value": "left=right|pipe", "reason": "unknown"},
        ])
        self.assertEqual(raw.basic_data_ignored_lines, ["# comment retained", "malformed line"])
        self.assertEqual(raw.gallery_image_urls, [])
        self.assertEqual(
            [warning["code"] for warning in raw.parser_warnings],
            ["SOURCE_ID_MISMATCH", "SOURCE_NAME_MISMATCH", "DUPLICATE_BASIC_DATA_KEY", "UNKNOWN_BASIC_DATA_KEY"],
        )

    def test_missing_basic_data_is_retained_with_warning(self):
        raw = parse_detail_html('<div id="article"><h1 id="post_title">宿</h1></div>', {
            "source_id": "1", "source_url": "https://min88.jp/inn/1/",
        })
        self.assertEqual(raw.name, "宿")
        self.assertEqual(raw.basic_data, {})
        self.assertIn("MISSING_REQUIRED_FIELD", [warning["code"] for warning in raw.parser_warnings])

    def test_legacy_basic_table_and_recurring_sections(self):
        raw = parse_fixture("detail_legacy.html", {
            "source_id": "1", "source_url": "https://min88.jp/inn/1/", "name": "legacy inn",
        })
        self.assertEqual(raw.basic_data, {
            "address": "徳島県\n一番町", "tel": "088-000-0000", "parking": "2台",
            "rooms": "3室", "price": "素泊り：4,000円", "website": "example.test",
            "checkin": "15:00", "checkout": "10:00", "wifi": "あり",
            "laundry": "洗濯機：あり", "payment": "現金：OK",
        })
        self.assertEqual([section["kind"] for section in raw.content_sections], ["host", "photo", "website"])
        self.assertIn("宿主の言葉です。", str(raw.content_sections))
        self.assertNotIn("除外する口コミです。", str(raw.to_dict()))
        self.assertEqual(raw.gallery_image_urls, ["https://min88.jp/tour.jpg"])
        self.assertNotIn("UNKNOWN_CONTENT_SECTION", [warning["code"] for warning in raw.parser_warnings])
        self.assertNotIn("MISSING_REQUIRED_FIELD", [warning["code"] for warning in raw.parser_warnings])

    def test_hidden_basic_data_remains_preferred_over_legacy_table(self):
        html = '''<div id="article"><h1 id="post_title">宿</h1><div class="post_content">
        <div class="min88-basicdata-pack"><textarea class="min88-basicdata-kv">address=hidden</textarea></div>
        <h3>基本情報</h3><table><tr><td>住所</td><td>rendered</td></tr></table></div></div>'''
        raw = parse_detail_html(html, {"source_id": "1", "source_url": "https://min88.jp/inn/1/"})
        self.assertEqual(raw.basic_data, {"address": "hidden"})

    def test_name_mismatch_ignores_only_cosmetic_differences(self):
        html = '''<div id="article"><h1 id="post_title">Ｌｅｇａｃｙ・Ｉｎｎ （本館）</h1>
        <div class="min88-basicdata-pack"><textarea class="min88-basicdata-kv">address=x</textarea></div></div>'''
        context = {"source_id": "1", "source_url": "https://min88.jp/inn/1/", "name": "legacy inn本館"}
        raw = parse_detail_html(html, context)
        self.assertNotIn("SOURCE_NAME_MISMATCH", [warning["code"] for warning in raw.parser_warnings])
        context["name"] = "legacy inn別館"
        raw = parse_detail_html(html, context)
        self.assertIn("SOURCE_NAME_MISMATCH", [warning["code"] for warning in raw.parser_warnings])

    def test_missing_article_uses_nulls_and_empty_collections(self):
        raw = extract_detail("<html><head></head><body></body></html>", {"source_id": "1", "source_url": "https://min88.jp/inn/1/"})
        self.assertIsNone(raw.name)
        self.assertIsNone(raw.canonical_source_id)
        self.assertEqual(raw.categories, [])
        self.assertEqual(raw.basic_data, {})
        self.assertEqual(raw.gallery_image_urls, [])
        self.assertEqual([warning["code"] for warning in raw.parser_warnings], ["MISSING_REQUIRED_FIELD", "MISSING_REQUIRED_FIELD", "MISSING_REQUIRED_FIELD"])


if __name__ == "__main__":
    unittest.main()
