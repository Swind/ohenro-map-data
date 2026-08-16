"""Unit tests for the pure normalizer functions (plan §28)."""

import unittest

from henroyado.normalize.facility import facility_type
from henroyado.normalize.image import split_image_url
from henroyado.normalize.map import parse_coordinates
from henroyado.normalize.meal import parse_meal
from henroyado.normalize.payment import parse_payment
from henroyado.normalize.room import parse_room
from henroyado.normalize.route import parse_route
from henroyado.normalize.text import clean_punct, normalize_digits
from henroyado.normalize.time import find_time_range, parse_time_range


class TestTime(unittest.TestCase):
    def test_single_time(self):
        self.assertEqual(parse_time_range("15:00"), ("15:00", None, "15:00", None))

    def test_range_time(self):
        start, end, display, notes = parse_time_range("15:00-19:00")
        self.assertEqual((start, end, display), ("15:00", "19:00", "15:00-19:00"))

    def test_range_tilde(self):
        start, end, display, _ = parse_time_range("15:00〜19:00")
        self.assertEqual((start, end), ("15:00", "19:00"))

    def test_open_ended(self):
        start, end, display, _ = parse_time_range("16:00-")
        self.assertEqual((start, end, display), ("16:00", None, "16:00-"))

    def test_time_with_notes(self):
        start, _, _, notes = parse_time_range("15:00 15:00以前対応可、要事前連絡")
        self.assertEqual(start, "15:00")
        self.assertEqual(notes, "15:00以前対応可、要事前連絡")

    def test_fullwidth_colon(self):
        start, _, _, _ = parse_time_range("14：00")
        self.assertEqual(start, "14:00")

    def test_four_digit_hhmm(self):
        start, _, _, _ = parse_time_range("1500")
        self.assertEqual(start, "15:00")

    def test_flexible_no_time(self):
        start, end, display, notes = parse_time_range("適宜")
        self.assertEqual((start, end, display), (None, None, None))
        self.assertEqual(notes, "適宜")

    def test_find_range_in_text(self):
        self.assertEqual(find_time_range("朝食 (7:00~9:00) 、 夕食"), ("07:00", "09:00", "07:00-09:00"))
        self.assertEqual(find_time_range("朝食 (6:30) 、 夕食"), ("06:30", None, "06:30"))


class TestRoom(unittest.TestCase):
    def test_room_type_and_count(self):
        self.assertEqual(parse_room("個室\n7部屋"), (["個室"], 7))

    def test_room_no_count(self):
        self.assertEqual(parse_room("個室"), (["個室"], None))

    def test_count_no_type(self):
        self.assertEqual(parse_room("5部屋"), ([], 5))

    def test_people_not_rooms(self):
        self.assertEqual(parse_room("相部屋\n16人"), (["相部屋"], None))

    def test_fullwidth_digits(self):
        self.assertEqual(parse_room("個室\n８部屋"), (["個室"], 8))

    def test_multiple_types(self):
        self.assertEqual(parse_room("個室 、 相部屋\n６部屋"), (["個室", "相部屋"], 6))

    def test_sum_multiple_counts(self):
        self.assertEqual(
            parse_room("個室 、 相部屋\nﾄﾞﾐﾄﾘｰ2人 1部屋. ﾄﾞﾐﾄﾘｰ4人 2部屋. 個室 2部屋\n個室4500円～"),
            (["個室", "相部屋", "ドミトリー"], 5))


class TestMeal(unittest.TestCase):
    def test_no_meal(self):
        b, d = parse_meal("なし")
        self.assertFalse(b["available"])
        self.assertFalse(d["available"])

    def test_breakfast_and_dinner(self):
        b, d = parse_meal("朝食 (7:00) 、 夕食")
        self.assertTrue(b["available"])
        self.assertEqual(b["start"], "07:00")
        self.assertTrue(d["available"])

    def test_no_times(self):
        b, d = parse_meal("朝食 、 夕食")
        self.assertTrue(b["available"])
        self.assertIsNone(b["start"])
        self.assertTrue(d["available"])

    def test_range(self):
        b, _ = parse_meal("朝食 (7:00~9:00) 、 夕食")
        self.assertEqual(b["start"], "07:00")
        self.assertEqual(b["end"], "09:00")

    def test_fullwidth(self):
        b, _ = parse_meal("朝食 (7：00) 、 夕食")
        self.assertEqual(b["start"], "07:00")

    def test_dinner_only(self):
        b, d = parse_meal("夕食")
        self.assertFalse(b["available"])
        self.assertTrue(d["available"])


class TestRoute(unittest.TestCase):
    def test_standard(self):
        f, t = parse_route("こちらは 1番霊山寺 から 2番極楽寺 へのお宿です。")
        self.assertEqual(f, {"number": 1, "name": "霊山寺"})
        self.assertEqual(t, {"number": 2, "name": "極楽寺"})

    def test_whitespace(self):
        f, t = parse_route("こちらは1番霊山寺から2番極楽寺へのお宿です。")
        self.assertEqual(f["number"], 1)
        self.assertEqual(t["name"], "極楽寺")

    def test_unsupported(self):
        f, t = parse_route("こちらの宿は1番霊山寺から少し歩いた場所にあります。")
        self.assertIsNone(f)
        self.assertIsNone(t)

    def test_empty(self):
        self.assertEqual(parse_route(None), (None, None))


class TestPayment(unittest.TestCase):
    def test_cash_only(self):
        self.assertEqual(parse_payment("現金"), (["cash"], []))

    def test_cash_and_card(self):
        methods, cards = parse_payment("現金 、 カード")
        self.assertEqual(methods, ["cash", "card"])
        self.assertEqual(cards, [])

    def test_card_brands(self):
        methods, cards = parse_payment("現金 、 カード （VISA/JCB/Mastercard/UC/AE）")
        self.assertEqual(methods, ["cash", "card"])
        self.assertEqual(cards, ["VISA", "Mastercard", "JCB", "AE", "UC"])

    def test_halfwidth_kana_amex(self):
        _, cards = parse_payment("現金 、 カード （ｱﾒﾘｶﾝｴｸｽﾌﾟﾚｽ）")
        self.assertIn("AE", cards)


class TestFacility(unittest.TestCase):
    def test_mapping(self):
        self.assertEqual(facility_type("wash_g.png"), "washing_machine")
        self.assertEqual(facility_type("wifi_g.png"), "wifi")
        self.assertEqual(facility_type("sougei_g.png"), "shuttle")

    def test_unknown(self):
        self.assertIsNone(facility_type("unknown_g.png"))


class TestImage(unittest.TestCase):
    def test_split_url(self):
        url, original = split_image_url("https://henroyado.com/storage/inns/HYT_02011.jpg?20260816022836")
        self.assertEqual(url, "https://henroyado.com/storage/inns/HYT_02011.jpg")
        self.assertEqual(original, "https://henroyado.com/storage/inns/HYT_02011.jpg?20260816022836")

    def test_no_query(self):
        url, original = split_image_url("https://henroyado.com/storage/inns/x.jpg")
        self.assertEqual(url, "https://henroyado.com/storage/inns/x.jpg")
        self.assertEqual(original, "https://henroyado.com/storage/inns/x.jpg")


class TestMap(unittest.TestCase):
    def test_coordinates(self):
        url = "https://www.google.com/maps/embed?pb=!1m18!2d134.4996533152179!3d34.159698980576884!5e0"
        c = parse_coordinates(url)
        self.assertEqual(c["longitude"], 134.4996533152179)
        self.assertEqual(c["latitude"], 34.159698980576884)

    def test_missing(self):
        self.assertIsNone(parse_coordinates(None))
        self.assertIsNone(parse_coordinates("https://example.com/embed"))


class TestText(unittest.TestCase):
    def test_fullwidth_digits(self):
        self.assertEqual(normalize_digits("６:００"), "6:00")

    def test_clean_punct(self):
        self.assertEqual(clean_punct("朝食 (7:00) 、 夕食"), "朝食 (7:00)、夕食")
        self.assertEqual(clean_punct("現金 、 カード （VISA）"), "現金、カード（VISA）")


if __name__ == "__main__":
    unittest.main()
