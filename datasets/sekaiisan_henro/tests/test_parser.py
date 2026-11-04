import unittest

from datasets.sekaiisan_henro import parser

NS = 'xmlns="http://www.opengis.net/kml/2.2"'


def _kml(body: str) -> bytes:
    return ('<?xml version="1.0" encoding="UTF-8"?><kml %s><Document>%s</Document></kml>' % (NS, body)).encode()


def _route(body: str) -> bytes:
    return _kml(body)


class TestRouteParser(unittest.TestCase):
    def _desc(self, fid: str) -> str:
        return ('<description><![CDATA[<table><tr><td>FID</td><td>%s</td></tr>'
                '<tr><td>区分</td><td>みち案内ルート</td></tr></table>]]></description>' % fid)

    def test_direct_and_multi_line_strings_with_stable_ids(self):
        data = _route(
            '<Placemark id="ID_0">%s'
            '<name></name>'
            '<LineString><coordinates>134.1,33.1 134.2,33.2 134.3,33.3</coordinates></LineString>'
            '</Placemark>'
            '<Placemark id="ID_1">%s'
            '<name></name>'
            '<MultiGeometry>'
            '<LineString><coordinates>134.4,33.4 134.5,33.5</coordinates></LineString>'
            '<LineString><coordinates>134.6,33.6 134.7,33.7 134.8,33.8</coordinates></LineString>'
            '</MultiGeometry>'
            '</Placemark>' % (self._desc("42"), self._desc("7"))
        )
        result = parser.parse_route_file(data, "tokushima")
        self.assertEqual(result["placemark_count"], 2)
        records = result["records"]
        self.assertEqual([r["id"] for r in records], ["SHR_tokushima_42_1", "SHR_tokushima_7_1", "SHR_tokushima_7_2"])
        self.assertEqual(records[0]["source_fid"], "42")
        self.assertEqual(records[0]["source_order"], 0)
        self.assertEqual(records[1]["source_order"], 1)
        self.assertEqual(records[2]["source_order"], 1)
        self.assertEqual(records[2]["part"], 2)
        self.assertEqual(records[0]["geometry"]["type"], "LineString")
        # altitude is dropped -> 2-element coordinates
        self.assertEqual(records[0]["geometry"]["coordinates"], [[134.1, 33.1], [134.2, 33.2], [134.3, 33.3]])

    def test_altitude_ignored_in_normalized_coordinates(self):
        data = _route(
            '<Placemark>%s<MultiGeometry>'
            '<LineString><coordinates>134.1,33.1,50 134.2,33.2,0</coordinates></LineString>'
            '</MultiGeometry></Placemark>' % self._desc("1")
        )
        record = parser.parse_route_file(data, "kochi")["records"][0]
        self.assertEqual(record["geometry"]["coordinates"], [[134.1, 33.1], [134.2, 33.2]])

    def test_invalid_coordinates_fail(self):
        data = _route('<Placemark>%s<LineString><coordinates>200,33 134.2,33.2</coordinates></LineString></Placemark>' % self._desc("1"))
        with self.assertRaisesRegex(ValueError, "outside valid"):
            parser.parse_route_file(data, "tokushima")

    def test_too_short_route_fails(self):
        data = _route('<Placemark>%s<LineString><coordinates>134.1,33.1</coordinates></LineString></Placemark>' % self._desc("1"))
        with self.assertRaisesRegex(ValueError, "at least two"):
            parser.parse_route_file(data, "tokushima")

    def test_missing_fid_uses_geometry_hash_fallback(self):
        data = _route('<Placemark><LineString><coordinates>134.1,33.1 134.2,33.2</coordinates></LineString></Placemark>')
        result = parser.parse_route_file(data, "tokushima")
        self.assertEqual(result["missing_source_fid"], 1)
        record = result["records"][0]
        self.assertIsNone(record["source_fid"])
        self.assertEqual(record["source_identity_kind"], "geometry_sha256")
        self.assertTrue(record["id"].startswith("SHR_tokushima_geometry_"))
        self.assertTrue(record["id"].endswith("_1"))
        self.assertRegex(record["geometry_sha256"], r"^[0-9a-f]{64}$")

    def test_colliding_geometry_hash_fails(self):
        data = _route(
            '<Placemark><LineString><coordinates>134.1,33.1 134.2,33.2</coordinates></LineString></Placemark>'
            '<Placemark><LineString><coordinates>134.1,33.1 134.2,33.2</coordinates></LineString></Placemark>'
        )
        with self.assertRaisesRegex(ValueError, "duplicate geometry identity"):
            parser.parse_route_file(data, "tokushima")

    def test_duplicate_fid_fails(self):
        data = _route(
            '<Placemark>%s<LineString><coordinates>134.1,33.1 134.2,33.2</coordinates></LineString></Placemark>'
            '<Placemark>%s<LineString><coordinates>134.3,33.3 134.4,33.4</coordinates></LineString></Placemark>'
            % (self._desc("5"), self._desc("5"))
        )
        with self.assertRaisesRegex(ValueError, "duplicate route FID"):
            parser.parse_route_file(data, "tokushima")

    def test_unsupported_geometry_in_route_fails(self):
        data = _route('<Placemark>%s<Point><coordinates>134.1,33.1</coordinates></Point></Placemark>' % self._desc("1"))
        with self.assertRaisesRegex(ValueError, "unsupported"):
            parser.parse_route_file(data, "tokushima")

    def test_unsupported_polygon_in_multigeometry_fails(self):
        data = _route(
            '<Placemark>%s<MultiGeometry>'
            '<LineString><coordinates>134.1,33.1 134.2,33.2</coordinates></LineString>'
            '<Polygon><outerBoundaryIs><LinearRing>'
            '<coordinates>134.1,33.1 134.2,33.2 134.3,33.3</coordinates>'
            '</LinearRing></outerBoundaryIs></Polygon>'
            '</MultiGeometry></Placemark>' % self._desc("1")
        )
        with self.assertRaisesRegex(ValueError, "unsupported"):
            parser.parse_route_file(data, "tokushima")

    def test_recursive_multigeometry_is_supported(self):
        data = _route(
            '<Placemark>%s<MultiGeometry><MultiGeometry>'
            '<LineString><coordinates>134.1,33.1 134.2,33.2</coordinates></LineString>'
            '</MultiGeometry></MultiGeometry></Placemark>' % self._desc("1")
        )
        self.assertEqual(len(parser.parse_route_file(data, "tokushima")["records"]), 1)


class TestTempleParser(unittest.TestCase):
    def _temple(self, name: str) -> bytes:
        return _kml(
            '<Placemark><name>%s</name>'
            '<description><![CDATA[<table><tr><td>読み</td><td>りょうぜんじ</td></tr></table>]]></description>'
            '<Point><coordinates>134.502937,34.159375</coordinates></Point></Placemark>' % name
        )

    def test_fullwidth_number_normalization_and_display_name(self):
        result = parser.parse_temple_file(self._temple("第１番札所　霊山寺　（No.1　Ryōzenji）"), "1-23.kml")
        self.assertEqual(len(result), 1)
        temple = result[0]
        self.assertEqual(temple["id"], "TEMPLE_1")
        self.assertEqual(temple["number"], 1)
        self.assertEqual(temple["raw_name"], "第１番札所　霊山寺　（No.1　Ryōzenji）")
        self.assertEqual(temple["name_jp"], "霊山寺")
        self.assertEqual(temple["geometry"]["type"], "Point")
        self.assertEqual(temple["geometry"]["coordinates"], [134.502937, 34.159375])
        self.assertEqual(temple["source_file"], "1-23.kml")

    def test_temple_number_out_of_range_fails(self):
        with self.assertRaisesRegex(ValueError, "out of range"):
            parser.parse_temple_file(self._temple("第９９番札所　テスト寺"), "66-88.kml")

    def test_temple_missing_point_fails(self):
        with self.assertRaisesRegex(ValueError, "exactly one Point"):
            parser.parse_temple_file(
                _kml('<Placemark><name>第１番札所　霊山寺</name></Placemark>'), "1-23.kml")

    def test_temple_multiple_points_fails(self):
        data = _kml(
            '<Placemark><name>第１番札所　霊山寺</name>'
            '<Point><coordinates>134.1,33.1</coordinates></Point>'
            '<Point><coordinates>134.2,33.2</coordinates></Point></Placemark>'
        )
        with self.assertRaisesRegex(ValueError, "exactly one Point"):
            parser.parse_temple_file(data, "1-23.kml")

    def test_temple_unsupported_geometry_fails(self):
        data = _kml(
            '<Placemark><name>第１番札所　霊山寺</name>'
            '<Point><coordinates>134.1,33.1</coordinates></Point>'
            '<LineString><coordinates>134.1,33.1 134.2,33.2</coordinates></LineString></Placemark>'
        )
        with self.assertRaisesRegex(ValueError, "unsupported geometry"):
            parser.parse_temple_file(data, "1-23.kml")


if __name__ == "__main__":
    unittest.main()