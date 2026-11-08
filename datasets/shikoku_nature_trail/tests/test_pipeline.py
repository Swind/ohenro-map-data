import base64
from pathlib import Path
import tempfile
import unittest

from datasets._pipeline import atomic_json, digest, read_json
from datasets.shikoku_nature_trail import config
from datasets.shikoku_nature_trail.crawler.assets import image_type
from datasets.shikoku_nature_trail.parser.course_detail import parse_course_detail
from datasets.shikoku_nature_trail.parser.course_list import parse_course_list
from datasets.shikoku_nature_trail.pipeline import fetch, source_inputs
from datasets.shikoku_nature_trail.verify import verify


PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aWQAAAABJRU5ErkJggg==")


def archive(root):
    courses, indexes = [], {}
    for post, pref in enumerate(config.PREFECTURES, 1):
        url = "https://shikoku-nature-trail.com/archives/%d" % post
        image_url = "https://shikoku-nature-trail.com/wp-content/uploads/image.png"
        index_html = ('<div class="courselist"><a class="row_line" href="%s">'
                      '<div class="cel cel2">Course %d</div></a></div>') % (url, post)
        index_path = root / "indexes" / (pref.id + ".html")
        index_path.parent.mkdir(exist_ok=True)
        index_path.write_text(index_html)
        parsed = parse_course_list(index_html, pref.url)
        courses.extend({**course, "prefecture": pref.id} for course in parsed)
        indexes[pref.id] = {"course_count": 1, "sha256": digest(index_path)}
        directory = root / "courses" / str(post)
        (directory / "map").mkdir(parents=True)
        (directory / "images").mkdir()
        html = '<h1>Course</h1><iframe src="https://www.google.com/maps/d/embed?mid=map%d"></iframe><img src="%s">' % (post, image_url)
        page = directory / "page.html"
        page.write_text(html)
        detail = parse_course_detail(html, url)
        atomic_json(directory / "metadata.json", {"source_post_id": post, "source_url": url,
                    "sha256": digest(page), "google_my_maps": detail["google_my_maps"],
                    "http": {"downloaded_at": "first retrieval"}})
        kml = directory / "map/map.kml"
        kml.write_text('<kml><Document><Placemark><LineString><coordinates>133,33 133.1,33.1</coordinates></LineString></Placemark></Document></kml>')
        atomic_json(directory / "map/metadata.json", {"map_id": "map%d" % post,
                    "source_url": config.KML_ENDPOINT.format(map_id="map%d" % post),
                    "sha256": digest(kml), "downloaded_at": "first retrieval"})
        image = directory / "images/001.png"
        image.write_bytes(PNG)
        atomic_json(directory / "assets.json", {"image_count": 1, "assets": [{
            "source_url": image_url, "local_file": "images/001.png", "status": "downloaded",
            "sha256": digest(image), "size": len(PNG)}]})
    atomic_json(root / "course-index.json", {"course_count": len(courses), "courses": courses,
                                             "indexes": indexes, "generated_at": "first retrieval"})


class PipelineBoundaryTests(unittest.TestCase):
    def test_source_identity_ignores_retrieval_times_but_retains_image_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive(root)
            self.assertTrue(verify(root)["ok"])
            before = source_inputs(root)
            for path in (root / "course-index.json", root / "courses/1/metadata.json",
                         root / "courses/1/map/metadata.json"):
                data = read_json(path)
                data["downloaded_at"] = "different retrieval"
                data["generated_at"] = "different retrieval"
                atomic_json(path, data)
            self.assertEqual(source_inputs(root), before)
            (root / "courses/1/images/001.png").write_bytes(PNG + b"changed")
            self.assertNotEqual(source_inputs(root), before)
            self.assertFalse(verify(root)["ok"])

    def test_failed_images_and_missing_source_rows_are_not_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive(root)
            path = root / "courses/1/assets.json"
            assets = read_json(path)
            assets["assets"][0]["status"] = "failed"
            atomic_json(path, assets)
            self.assertFalse(verify(root)["ok"])
            assets["assets"][0]["status"] = "downloaded"
            atomic_json(path, assets)
            path = root / "indexes/tokushima.html"
            path.write_text(path.read_text().replace("</div>", '<a class="row_line" href="/missing">Broken</a></div>', 1))
            index = read_json(root / "course-index.json")
            index["indexes"]["tokushima"]["sha256"] = digest(path)
            atomic_json(root / "course-index.json", index)
            self.assertFalse(verify(root)["ok"])

    def test_http_error_body_cannot_be_an_archived_image(self):
        self.assertIsNone(image_type(b"<html>Not found</html>"))
        self.assertEqual(image_type(PNG), "image/png")

    def test_matching_checksums_do_not_make_a_nonroute_map_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive(root)
            kml = root / "courses/1/map/map.kml"
            kml.write_text("<kml><Document><Placemark><Point><coordinates>133,33</coordinates></Point></Placemark></Document></kml>")
            metadata_path = root / "courses/1/map/metadata.json"
            metadata = read_json(metadata_path)
            metadata["sha256"] = digest(kml)
            atomic_json(metadata_path, metadata)
            result = verify(root)
            self.assertFalse(result["ok"])
            self.assertTrue(any("no route geometry" in error for error in result["errors"]))

    def test_incomplete_refresh_does_not_replace_the_valid_archive(self):
        class UnavailableLists:
            def get_bytes(self, url):
                return 200, {"Content-Type": "text/html"}, b"<html>Temporarily unavailable</html>"

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive(root)
            previous = {str(path.relative_to(root)): digest(path)
                        for path in root.rglob("*") if path.is_file()}
            with self.assertRaisesRegex(ValueError, "Incomplete source"):
                fetch(root, UnavailableLists())
            self.assertTrue(verify(root)["ok"])
            self.assertFalse((root / "current.json").exists())
            self.assertEqual(previous, {str(path.relative_to(root)): digest(path)
                                        for path in root.rglob("*") if path.is_file()})


if __name__ == "__main__":
    unittest.main()
