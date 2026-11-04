import json
import os
import tempfile
import unittest

from datasets.arukihenro_routes.kml import parse_kml
from datasets.arukihenro_routes.normalize import normalize_archive

KML = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>01番～02番札所 極楽寺【A:1.4㎞　B:1.6km】</name>
    <description><![CDATA[<br>2016/08/12]]></description>
    <Style id="icon-1899-DB4436-normal">
      <IconStyle><Icon><href>x</href></Icon></IconStyle>
    </Style>
    <Folder>
      <name>無題のレイヤ</name>
      <Placemark>
        <name>霊山寺仁王門</name>
        <styleUrl>#icon-1899-DB4436</styleUrl>
        <ExtendedData>
          <Data name="gx_media_links">
            <value>https://example.test/a.jpg https://example.test/b.jpg</value>
          </Data>
        </ExtendedData>
        <Point>
          <coordinates>
            134.5029652,34.1592126,0
          </coordinates>
        </Point>
      </Placemark>
    </Folder>
    <Folder>
      <name>旧遍路ルート</name>
      <Placemark>
        <name>日本, 〒779-0230 徳島県鳴門市大麻町板東 から 日本 へのルート</name>
        <styleUrl>#line-1267FF-5000-nodesc</styleUrl>
        <LineString>
          <tessellate>1</tessellate>
          <coordinates>
            134.50245,34.1587,0
            134.50234,34.158,0
          </coordinates>
        </LineString>
      </Placemark>
      <Placemark>
        <name>日本, 〒779-0230 徳島県鳴門市大麻町板東</name>
        <Point><coordinates>134.5024469,34.1587024,0</coordinates></Point>
      </Placemark>
    </Folder>
  </Document>
</kml>"""


class TestParseKml(unittest.TestCase):
    def test_parses_lines_and_points(self):
        result = parse_kml(KML.encode("utf-8"))
        self.assertEqual(result["name"], "01番～02番札所 極楽寺【A:1.4㎞　B:1.6km】")
        self.assertEqual(result["description"], "<br>2016/08/12")
        self.assertEqual(len(result["points"]), 2)
        self.assertEqual(len(result["lines"]), 1)

        point = result["points"][0]
        self.assertEqual(point["name"], "霊山寺仁王門")
        self.assertEqual(point["category"], "temple_related")
        self.assertEqual(point["coordinates"], [134.5029652, 34.1592126])
        self.assertEqual(point["photos"], ["https://example.test/a.jpg", "https://example.test/b.jpg"])
        self.assertEqual(point["folder"], "無題のレイヤ")

        endpoint = result["points"][1]
        self.assertEqual(endpoint["category"], "route_endpoint")

        line = result["lines"][0]
        self.assertEqual(line["source"], "google_directions")
        self.assertEqual(line["folder"], "旧遍路ルート")
        self.assertEqual(line["coordinates"], [[134.50245, 34.1587], [134.50234, 34.158]])


class TestNormalizeArchive(unittest.TestCase):
    def test_writes_deterministic_dataset(self):
        with tempfile.TemporaryDirectory() as directory:
            os.makedirs(os.path.join(directory, "routes", "abc123456789def0", "maps"))
            record = {
                "id": "abc123456789def0",
                "region": "tokushima",
                "title": "01番～02番札所極楽寺　歩きへんろ道",
                "url": "http://ohenro.jp/blog/arukihenro/junnro/michi01to02/",
                "maps": [{
                    "map_id": "map1",
                    "kml_url": "https://www.google.com/maps/d/kml?mid=map1&forcekml=1",
                    "embed_url": "https://www.google.com/maps/d/embed?mid=map1",
                    "local_path": "routes/abc123456789def0/maps/map1.kml",
                }],
            }
            manifest = {"schema_version": 1, "source": "https://ohenro.jp/blog/arukihenro/", "routes": [record]}
            with open(os.path.join(directory, "manifest.json"), "w", encoding="utf-8") as stream:
                json.dump(manifest, stream, ensure_ascii=False)
            with open(os.path.join(directory, "routes", "abc123456789def0", "maps", "map1.kml"), "w", encoding="utf-8") as stream:
                stream.write(KML)

            output = os.path.join(directory, "normalized.json")
            summary = normalize_archive(directory, output)
            self.assertEqual(summary["route_count"], 1)
            self.assertEqual(summary["map_count"], 1)
            self.assertEqual(summary["line_count"], 1)
            self.assertEqual(summary["point_count"], 2)
            self.assertEqual(summary["photo_point_count"], 1)
            self.assertEqual(summary["category_counts"]["temple_related"], 1)
            self.assertEqual(summary["category_counts"]["route_endpoint"], 1)
            self.assertEqual(summary["warning_count"], 0)

            with open(output, encoding="utf-8") as stream:
                dataset = json.load(stream)
            self.assertEqual(dataset["schema_version"], 1)
            route = dataset["routes"][0]
            self.assertEqual(route["id"], "abc123456789def0")
            self.assertEqual(route["maps"][0]["map_name"], "01番～02番札所 極楽寺【A:1.4㎞　B:1.6km】")

            with open(output, "rb") as stream:
                first = stream.read()
            summary = normalize_archive(directory, output)
            with open(output, "rb") as stream:
                second = stream.read()
            self.assertEqual(first, second)

    def test_missing_kml_is_a_warning_not_a_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            record = {"id": "abc", "region": "kochi", "title": "X", "url": "http://example.test/x",
                      "maps": [{"map_id": "m1", "local_path": "routes/abc/maps/missing.kml"}]}
            manifest = {"schema_version": 1, "source": "s", "routes": [record]}
            with open(os.path.join(directory, "manifest.json"), "w", encoding="utf-8") as stream:
                json.dump(manifest, stream, ensure_ascii=False)
            output = os.path.join(directory, "normalized.json")
            summary = normalize_archive(directory, output)
            self.assertEqual(summary["warning_count"], 1)
            self.assertEqual(summary["line_count"], 0)


if __name__ == "__main__":
    unittest.main()