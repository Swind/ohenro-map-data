import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from datasets.arukihenro_routes import fetch, pipeline
from datasets.arukihenro_routes.storage import resolve_archive


KML = b'<kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>route</name><Placemark><LineString><coordinates>134,34 134.01,34.01</coordinates></LineString></Placemark></Document></kml>'


def responses():
    pages = {}
    urls = [f"https://ohenro.jp/blog/arukihenro/junnro/michi{i:02d}to{i % 88 + 1:02d}/" for i in range(1, 89)]
    for n, url in enumerate(fetch.INDEX_PAGES.values()):
        pages[url] = "".join(f'<a href="{link}">route</a>' for link in urls[n::4]).encode()
    for i, url in enumerate(urls + fetch.EXTRA_ROUTES):
        pages[url] = (f'<h1 class="entry-title">{i % 88 + 1}番～{(i + 1) % 88 + 1}番</h1>'
                      f'<iframe src="https://www.google.com/maps/d/embed?mid=map{i}"></iframe>').encode()
        pages[f"https://www.google.com/maps/d/kml?mid=map{i}&forcekml=1"] = KML
    return pages


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.raw, self.output, self.reports = root / "raw", root / "output", root / "reports"
        self.pages = responses()

    def refresh(self):
        with patch.object(fetch, "_get", side_effect=lambda url, timeout: self.pages[url]):
            pipeline.refresh(self.raw, 30, 0)

    def test_refresh_build_and_semantically_unchanged_output(self):
        self.refresh()
        pipeline.build(self.raw, self.output, self.reports)
        path = self.output / pipeline.OUTPUT
        before = path.stat().st_mtime_ns
        current = (self.raw / "current.json").read_bytes()
        # A page-only change is archived but must not republish identical data.
        url = next(iter(fetch.INDEX_PAGES.values()))
        self.pages[url] += b"<!-- updated WordPress footer -->"
        self.refresh()
        self.assertNotEqual(current, (self.raw / "current.json").read_bytes())
        pipeline.build(self.raw, self.output, self.reports)
        self.assertEqual(before, path.stat().st_mtime_ns)
        pipeline.validate(self.output, self.reports)
        path.write_text("broken")
        with self.assertRaisesRegex(ValueError, "hash/size"):
            pipeline.validate(self.output, self.reports)
        pipeline.build(self.raw, self.output, self.reports)
        pipeline.validate(self.output, self.reports)

    def test_failed_kml_keeps_previous_snapshot(self):
        self.refresh()
        before = (self.raw / "current.json").read_bytes()
        self.pages["https://www.google.com/maps/d/kml?mid=map0&forcekml=1"] = b"<html>error</html>"
        with self.assertRaisesRegex(ValueError, "Failed/mismatched KML"):
            self.refresh()
        self.assertEqual(before, (self.raw / "current.json").read_bytes())

    def test_corrupt_snapshot_prevents_publication(self):
        self.refresh()
        path = next(resolve_archive(self.raw).glob("routes/*/maps/*.kml"))
        path.write_bytes(KML + b"changed")
        with self.assertRaisesRegex(ValueError, "KML hash mismatch"):
            pipeline.build(self.raw, self.output, self.reports)
        self.assertFalse((self.output / pipeline.OUTPUT).exists())

    def test_kml_root_validation(self):
        for body in (b"<kml>", b"<html><kml/></html>"):
            with self.assertRaises(ValueError):
                fetch._validate_kml(body)


if __name__ == "__main__":
    unittest.main()
