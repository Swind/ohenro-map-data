import unittest

from min88_lodging.normalize import normalize_lodging
from min88_lodging.normalize.fields import (parse_parking, parse_prices, parse_time,
                                             parse_tri_state)


class TestFields(unittest.TestCase):
    def test_tri_state(self):
        self.assertEqual(parse_tri_state("可"), "available")
        self.assertEqual(parse_tri_state("不可"), "unavailable")
        self.assertEqual(parse_tri_state(None), "not_provided")
        self.assertEqual(parse_tri_state("あり（100円）"), "available")
        self.assertEqual(parse_tri_state("なし（近隣施設あり）"), "unavailable")
        self.assertEqual(parse_tri_state("未確認"), "unknown")
        self.assertEqual(parse_tri_state("対象外"), "not_applicable")
        self.assertEqual(parse_tri_state("OK（PayPay）"), "available")
        self.assertEqual(parse_tri_state("◯"), "available")
        self.assertEqual(parse_tri_state("○"), "available")
        self.assertEqual(parse_tri_state("NG"), "unavailable")
        self.assertEqual(parse_tri_state("設定無し"), "not_applicable")
        self.assertEqual(parse_tri_state("—"), "not_provided")

    def test_checkout_deadline(self):
        self.assertEqual(parse_time("９：００前", deadline=True)["end"], "09:00")
        self.assertIsNone(parse_time("９：００前", deadline=True)["start"])

    def test_parking(self):
        value = parse_parking("6台　無料（予約不要）")
        self.assertEqual((value["space_count"], value["fee_status"], value["reservation_required"]),
                         (6, "free", False))

    def test_prices_and_surcharge(self):
        value = parse_prices("素泊り：個室4,200円、ドミトリー2,625円|朝食付：+525円")
        self.assertEqual([item["amount_yen"] for item in value["items"]], [4200, 2625, 525])
        self.assertTrue(value["items"][-1]["surcharge"])
        self.assertEqual([item["room_type"] for item in value["items"]],
                          ["private", "dormitory", None])

    def test_price_states_ranges_and_notes(self):
        value = parse_prices("素泊り：4,000〜5,000円|朝食付：設定無し|夕食付：応相談|※季節料金")
        self.assertEqual((value["items"][0]["min_amount_yen"], value["items"][0]["max_amount_yen"]),
                         (4000, 5000))
        self.assertEqual([item["status"] for item in value["items"][1:]],
                         ["not_applicable", "negotiable"])
        self.assertEqual(value["notes"], ["※季節料金"])

    def test_descriptive_price_does_not_warn(self):
        value = normalize_lodging({"basic_data": {"price": "素泊り：予約サイト参照"}})
        self.assertEqual(value["pricing"]["items"][0]["status"], "descriptive")
        self.assertEqual(value["_warnings"], [])

    def test_after_midnight_time(self):
        value = parse_time("15:00～25:30")
        self.assertEqual((value["start"], value["end"]), ("15:00", "01:30"))
        self.assertEqual((value["start_day_offset"], value["end_day_offset"]), (0, 1))

    def test_invalid_clock_is_not_normalized(self):
        value = parse_time("99:99")
        self.assertIsNone(value["start"])
        self.assertEqual(value["raw_text"], "99:99")


class TestAggregate(unittest.TestCase):
    def test_conservative_record(self):
        raw = {
            "source_context": {"source_id": "85", "source_url": "https://min88.jp/inn/85/",
                               "prefecture": "tokushima", "closure_marker": "《休業･閉業》"},
            "name": "旅人の宿・道しるべ", "modified_text": "最終更新日：2026年6月20日",
            "lodging_types": ["民宿･ゲストハウス"],
            "route_lines": [{"lnum": "03", "lname": "金泉寺", "lkm": "1.2",
                             "rnum": "04", "rname": "大日寺", "rkm": "5.3"}],
            "basic_data": {"address": "徳島県板野郡板野町", "rooms": "6室",
                           "checkout": "9:00前", "wifi": "未確認",
                           "payment": "現金：可|クレジットカード：不可"},
        }
        value = normalize_lodging(raw)
        self.assertEqual(value["business_status"], "closed_or_suspended")
        self.assertEqual(value["rooms"]["room_count"], 6)
        self.assertEqual(value["henro"]["next_temple"]["number"], 4)
        self.assertEqual(value["location"]["coordinates"], None)
        self.assertEqual(value["payment"]["credit_card"], "unavailable")

    def test_live_output_fixes_are_retained(self):
        raw = {
            "lodging_types": ["旅館･ホテル", "通夜堂･善根宿"],
            "basic_data": {
                "laundry": "洗濯機：あり（100円）|乾燥機：なし",
                "payment": "現金：可|電子マネー：未確認",
                "emoney": "PayPay,楽天ペイ", "rooms": "全10室（うち和室8室）",
                "website": "未確認",
            },
            "supplemental_facilities": ["ー", "ペット宿泊不可", "送迎あり"],
            "unknown_sections": [{"title": "補足情報"}],
        }
        value = normalize_lodging(raw)
        self.assertEqual(value["lodging_types"], ["ryokan", "hotel", "pilgrim_shelter"])
        self.assertEqual(value["rooms"]["room_count"], 10)
        self.assertEqual(value["payment"]["electronic_money"], "available")
        self.assertEqual(value["payment"]["electronic_money_methods"], ["PayPay", "楽天ペイ"])
        self.assertIsNone(value["contact"]["website"])
        self.assertEqual([item["status"] for item in value["facilities"][-2:]], ["unknown", "available"])
        self.assertEqual(value["raw"]["supplemental_facilities"], raw["supplemental_facilities"])
        self.assertEqual(value["raw"]["unknown_sections"], raw["unknown_sections"])
        self.assertEqual(value["_warnings"], [])

    def test_explicit_all_rooms_is_authoritative_total(self):
        value = normalize_lodging({"basic_data": {
            "rooms": "全16室（シングル6室、ツイン6室、和室4室）",
        }})
        self.assertEqual(value["rooms"]["room_count"], 16)

    def test_emoney_placeholder_does_not_override_payment_state(self):
        value = normalize_lodging({"basic_data": {
            "payment": "電子マネー：可", "emoney": "未確認",
        }})
        self.assertEqual(value["payment"]["electronic_money"], "available")
        self.assertEqual(value["payment"]["electronic_money_methods"], [])

    def test_legacy_multiline_payment_states(self):
        raw_text = "現金：OK\nクレジットカード：NG\n電子マネー：OK（PayPay）"
        value = normalize_lodging({"basic_data": {"payment": raw_text}})
        self.assertEqual(value["payment"]["cash"], "available")
        self.assertEqual(value["payment"]["credit_card"], "unavailable")
        self.assertEqual(value["payment"]["electronic_money"], "available")
        self.assertEqual(value["payment"]["raw_text"], raw_text)
        self.assertEqual(value["_warnings"], [])

        wifi = normalize_lodging({"basic_data": {"wifi": "–"}})
        self.assertEqual(wifi["facilities"][0]["status"], "not_provided")
        self.assertEqual(wifi["_warnings"], [])

    def test_legacy_multiline_laundry_amounts(self):
        raw_text = "洗濯機：100円\n乾燥機：無料"
        value = normalize_lodging({"basic_data": {"laundry": raw_text}})
        self.assertEqual([item["status"] for item in value["facilities"][1:3]],
                         ["available", "available"])
        self.assertEqual(value["facilities"][1]["raw_text"], raw_text)
        self.assertEqual(value["_warnings"], [])

        combined = normalize_lodging({"basic_data": {"laundry": "洗濯+乾燥機：300円"}})
        self.assertEqual([item["status"] for item in combined["facilities"][1:3]],
                         ["available", "available"])
        prose = normalize_lodging({"basic_data": {"laundry": "近隣にコインランドリーあり"}})
        self.assertEqual([item["status"] for item in prose["facilities"][1:3]],
                         ["not_provided", "not_provided"])
        self.assertEqual(len(prose["_warnings"]), 1)

    def test_unknown_keyed_values_and_invalid_clock_warn(self):
        value = normalize_lodging({"basic_data": {
            "laundry": "洗濯機：未確認|謎：可", "payment": "現金：たぶん", "checkin": "99:99",
        }})
        warnings = [(warning["field"], warning["raw_value"]) for warning in value["_warnings"]]
        self.assertIn(("laundry", "謎：可"), warnings)
        self.assertIn(("payment", "現金：たぶん"), warnings)
        self.assertIn(("checkin", "99:99"), warnings)
        self.assertNotIn(("laundry", "洗濯機：未確認"), warnings)


if __name__ == "__main__":
    unittest.main()
