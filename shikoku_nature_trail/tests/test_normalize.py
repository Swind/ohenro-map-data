import json
import os
import tempfile
import unittest
from unittest.mock import patch

from shikoku_nature_trail.cli import main


class TestNormalizeCli(unittest.TestCase):
    def test_missing_index_is_fatal(self):
        with tempfile.TemporaryDirectory() as root:
            with patch("shikoku_nature_trail.cli._make_client",
                       side_effect=AssertionError("network client constructed")):
                self.assertEqual(main(["--data-dir", root, "normalize"]), 1)

    def test_offline_deterministic_output_and_per_course_kml_warning(self):
        with tempfile.TemporaryDirectory() as root:
            data_dir = os.path.join(root, "archive")
            course_dir = os.path.join(data_dir, "courses", "119")
            os.makedirs(os.path.join(course_dir, "map"))
            fixture = os.path.join(os.path.dirname(__file__), "fixtures", "course-119.html")
            with open(fixture, encoding="utf-8") as source, \
                    open(os.path.join(course_dir, "page.html"), "w", encoding="utf-8") as target:
                target.write(source.read())
            index = {"courses": [{
                "source_post_id": 119,
                "detail_url": "https://shikoku-nature-trail.com/archives/119",
                "prefecture": "ehime",
            }]}
            with open(os.path.join(data_dir, "course-index.json"), "w", encoding="utf-8") as file:
                json.dump(index, file)
            assets = {"assets": [{
                "source_url": "https://shikoku-nature-trail.com/wp-content/uploads/2020/03/03_01ehime.jpg",
                "local_file": "images/003.jpg",
                "status": "downloaded",
            }]}
            with open(os.path.join(course_dir, "assets.json"), "w", encoding="utf-8") as file:
                json.dump(assets, file)
            with open(os.path.join(course_dir, "map", "map.kml"), "w", encoding="utf-8") as file:
                file.write("<kml><broken></kml>")

            output = os.path.join(root, "nested", "normalized.json")
            args = ["--data-dir", data_dir, "normalize", "--output", output]
            with patch("shikoku_nature_trail.cli._make_client",
                       side_effect=AssertionError("network client constructed")):
                self.assertEqual(main(args), 0)
                with open(output, "rb") as file:
                    first = file.read()
                self.assertEqual(main(args), 0)
                with open(output, "rb") as file:
                    self.assertEqual(file.read(), first)

            result = json.loads(first)
            self.assertEqual(result["summary"]["warning_count"], 1)
            self.assertIn("malformed KML", result["warnings"][0])
            spot = result["courses"][0]["tourism_spots"][0]
            self.assertEqual(spot["image"]["local_path"], "courses/119/images/003.jpg")


if __name__ == "__main__":
    unittest.main()
