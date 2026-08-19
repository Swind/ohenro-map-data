"""Parser unit tests against real HTML fixtures (plan §32).

Fixtures are trimmed from live pages to keep the repo small. They verify:
course count, post ID, name, distance, difficulty, detail URL, Google Map ID,
and image URL count.
"""

import os
import unittest

from shikoku_nature_trail.parser.course_detail import parse_course_detail
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


if __name__ == "__main__":
    unittest.main()