import unittest

from arukihenro_routes.temple_range import parse_temple_range


class TestParseTempleRange(unittest.TestCase):
    def test_standard_titles(self):
        self.assertEqual(parse_temple_range("01番～02番札所極楽寺　歩きへんろ道"), (1, 2, [1, 2]))
        self.assertEqual(parse_temple_range("79番～81番札所白峯寺　あるき遍路道"), (79, 81, [79, 81]))

    def test_map_name_separators(self):
        for sep in ("～", "－", "―", "ー", "‐"):
            self.assertEqual(parse_temple_range("24番%s25番札所津照寺【5.9㎞】" % sep), (24, 25, [24, 25]))

    def test_closing_loop(self):
        self.assertEqual(parse_temple_range("88番札所～01番札所へんろ道"), (88, 1, [88, 1]))

    def test_combined_targets(self):
        self.assertEqual(parse_temple_range("67番－68・69番所観音寺【8.7㎞】"), (67, 69, [67, 68, 69]))
        self.assertEqual(parse_temple_range("68・69番－70番札所本山寺【北:4.5㎞　南:4.9㎞】"), (68, 70, [68, 69, 70]))

    def test_single_temple(self):
        self.assertEqual(parse_temple_range("23番～　旧へんろ道（八坂八浜古道）"), (23, 23, [23]))

    def test_extra_segment_marker(self):
        self.assertEqual(parse_temple_range("38番－月山神社－39番札所延光寺(ルート2)【72.5㎞】"), (38, 39, [38, 39]))

    def test_betsu_ignored(self):
        self.assertEqual(parse_temple_range("別格04番札所鯖大師本坊　遍路道"), (None, None, []))
        self.assertEqual(parse_temple_range(None), (None, None, []))

    def test_duplicates_collapsed(self):
        self.assertEqual(parse_temple_range("87番－88番札所大窪寺【88番の近く】"), (87, 88, [87, 88]))


if __name__ == "__main__":
    unittest.main()