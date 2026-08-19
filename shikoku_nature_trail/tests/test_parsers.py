"""Parser unit tests against real HTML fixtures (plan §32).

Fixtures are trimmed from live pages to keep the repo small. They verify:
course count, post ID, name, distance, difficulty, detail URL, Google Map ID,
and image URL count.
"""

import os
import unittest

from shikoku_nature_trail.parser.course_detail import parse_course_detail
from shikoku_nature_trail.parser.kml import parse_kml
from shikoku_nature_trail.parser.course_list import parse_course_list

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _read(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return f.read()


class TestCourseListParser(unittest.TestCase):
    def test_ehime_list_count(self):
        courses = parse_course_list(
            _read("ehime-list.html"),
            "https://shikoku-nature-trail.com/courselist_ehime",
        )
        self.assertEqual(len(courses), 33)

    def test_ehime_first_row_fields(self):
        courses = parse_course_list(
            _read("ehime-list.html"),
            "https://shikoku-nature-trail.com/courselist_ehime",
        )
        first = courses[0]
        self.assertEqual(first["course_number"], "1")
        self.assertEqual(first["name_ja"], "旧宿毛街道のみち")
        self.assertEqual(first["source_post_id"], 95)
        self.assertEqual(first["detail_url"],
                         "https://shikoku-nature-trail.com/archives/95")
        self.assertEqual(first["location_raw"], "愛南町小川～愛南町御荘平城")
        self.assertEqual(first["distance_raw"], "17.6km")
        self.assertEqual(first["distance_km"], 17.6)
        self.assertEqual(first["difficulty_raw"], "★★☆")
        self.assertEqual(first["difficulty"], 2)
        self.assertIn("遍路", first["features"])

    def test_three_kanji_terrace_entry(self):
        courses = parse_course_list(
            _read("ehime-list.html"),
            "https://shikoku-nature-trail.com/courselist_ehime",
        )
        entry = next(c for c in courses if c["source_post_id"] == 119)
        self.assertEqual(entry["name_ja"], "三間盆地2ヵ寺参りのみち")
        self.assertEqual(entry["course_number"], "3")
        self.assertEqual(entry["distance_km"], 9.0)
        self.assertEqual(entry["difficulty"], 1)


class TestCourseDetailParser(unittest.TestCase):
    def test_title(self):
        d = parse_course_detail(
            _read("course-119.html"),
            "https://shikoku-nature-trail.com/archives/119",
        )
        self.assertEqual(d["title"], "三間盆地2ヵ寺参りのみち")

    def test_google_map_id(self):
        d = parse_course_detail(
            _read("course-119.html"),
            "https://shikoku-nature-trail.com/archives/119",
        )
        self.assertIsNotNone(d["google_my_maps"])
        self.assertEqual(d["google_my_maps"]["map_id"], "1NqcxWDXSF_LHZ7ej5FhAS4bLV66w9KX1")
        self.assertIn("mid=1NqcxWDXSF_LHZ7ej5FhAS4bLV66w9KX1",
                      d["google_my_maps"]["embed_url"])

    def test_image_urls_are_content_only(self):
        d = parse_course_detail(
            _read("course-119.html"),
            "https://shikoku-nature-trail.com/archives/119",
        )
        urls = [img["url"] for img in d["images"]]
        # all content images live under /wp-content/uploads/
        self.assertTrue(all("/wp-content/uploads/" in u for u in urls))
        # theme images (logos/icons under /wp-content/themes/) are excluded
        self.assertTrue(all("/wp-content/themes/" not in u for u in urls))
        # a couple of specific content images present
        self.assertTrue(any(u.endswith("/2020/03/03_01ehime.jpg") for u in urls))
        self.assertTrue(any(u.endswith("/2020/03/ehime03-1.png") for u in urls))

    def test_many_images_count(self):
        d = parse_course_detail(
            _read("course-many-images.html"),
            "https://shikoku-nature-trail.com/archives/3857",
        )
        self.assertEqual(len(d["images"]), 13)

    def test_without_map(self):
        d = parse_course_detail(
            _read("course-without-map.html"),
            "https://shikoku-nature-trail.com/archives/119",
        )
        self.assertIsNone(d["google_my_maps"])

    def test_phase_2_content(self):
        d = parse_course_detail(
            _read("course-119.html"),
            "https://shikoku-nature-trail.com/archives/119",
        )
        self.assertTrue(d["description"].startswith("愛媛県内の四国のみち"))
        self.assertEqual(d["photo_point"]["title"], "第42番札所佛木寺[山門]")
        self.assertEqual(
            d["photo_point"]["description"],
            "認定証を希望する方は、各コースの定められた撮影ポイントで申請者自身を入れた写真を撮影してください。",
        )
        first = d["tourism_spots"][0]
        self.assertEqual(first["number"], "1")
        self.assertEqual(first["title"], "龍光寺(りゅうこうじ)")
        self.assertEqual(
            first["description"],
            "龍光寺は、第41 番札所です。三間平野を見下ろす小高い丘にある寺で、土地の人から「お稲荷さん」と呼ばれています。"
            "土地の庄屋が川原でうたた寝している所を龍に襲われましたが腰の刀が自然に抜けて龍の目をくりぬいた、という伝説にちなむ龍の目が奉納されています。"
            "三間の農家の守り神です。大同２年（807年）、弘法大師がこの地を巡礼した時にお告げがあり、自ら尊像を刻み堂宇を立てて安置し稲荷山護国院龍光寺と名付けました。"
            "正面に稲荷神社があります。",
        )
        self.assertEqual(
            first["image_url"],
            "https://shikoku-nature-trail.com/wp-content/uploads/2020/03/03_01ehime.jpg",
        )


class TestKmlParser(unittest.TestCase):
    KML = """<?xml version="1.0"?>
    <kml xmlns="http://www.opengis.net/kml/2.2"><Document>
      <name> Course </name><description><![CDATA[one<br> two]]></description>
      <Placemark><name>point</name><Point><coordinates>134.1,33.2,5</coordinates></Point></Placemark>
      <Placemark><name>line</name><description><![CDATA[<b>walk</b> here]]></description>
        <LineString><coordinates>134,33 135,34,10</coordinates></LineString></Placemark>
      <Placemark><name>multi</name><MultiGeometry>
        <Point><coordinates>133,32</coordinates></Point>
        <LineString><coordinates>133,32 134,33</coordinates></LineString>
      </MultiGeometry></Placemark>
    </Document></kml>"""

    def test_namespaces_and_geometries(self):
        result = parse_kml(self.KML)
        self.assertEqual(result["name"], "Course")
        self.assertEqual(result["description"], "one two")
        self.assertEqual(result["placemarks"][0]["geometry"], {
            "type": "Point", "coordinates": [134.1, 33.2, 5.0],
        })
        self.assertEqual(result["placemarks"][1]["description"], "walk here")
        self.assertEqual(result["placemarks"][1]["geometry"]["type"], "LineString")
        self.assertEqual(result["placemarks"][2]["geometry"]["type"], "GeometryCollection")
        self.assertEqual(len(result["placemarks"][2]["geometry"]["geometries"]), 2)

    def test_malformed_xml(self):
        with self.assertRaisesRegex(ValueError, "malformed KML"):
            parse_kml("<kml><broken></kml>")


if __name__ == "__main__":
    unittest.main()
