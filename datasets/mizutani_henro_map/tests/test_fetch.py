import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from datasets.mizutani_henro_map.fetch import fetch

KML = (Path(__file__).parent / "fixtures" / "map.kml").read_bytes()


class TestFetch(unittest.TestCase):
    def test_archives_once_and_updates_current_check(self):
        with tempfile.TemporaryDirectory() as data_dir:
            with patch("datasets.mizutani_henro_map.fetch._download", return_value=(200, {"Content-Type": "text/xml"}, KML)):
                first = fetch(data_dir)
                second = fetch(data_dir)

            self.assertTrue(first["new_snapshot"])
            self.assertFalse(second["new_snapshot"])
            snapshot = os.path.join(data_dir, "snapshots", first["sha256"])
            with open(os.path.join(snapshot, "metadata.json"), encoding="utf-8") as stream:
                metadata = json.load(stream)
            self.assertEqual(metadata["sha256"], first["sha256"])
            self.assertEqual(metadata["map_id"], "1FYOrTzLZCmGi4wGFf5bNhIe3K18")
            with open(os.path.join(data_dir, "current.json"), encoding="utf-8") as stream:
                self.assertEqual(json.load(stream)["sha256"], first["sha256"])

    def test_invalid_response_keeps_current_snapshot(self):
        with tempfile.TemporaryDirectory() as data_dir:
            with patch("datasets.mizutani_henro_map.fetch._download", return_value=(200, {}, KML)):
                original = fetch(data_dir)["sha256"]
            with patch("datasets.mizutani_henro_map.fetch._download", return_value=(200, {}, b"<html>bad</html>")):
                with self.assertRaises(ValueError):
                    fetch(data_dir)
            with open(os.path.join(data_dir, "current.json"), encoding="utf-8") as stream:
                self.assertEqual(json.load(stream)["sha256"], original)
            self.assertEqual(len(os.listdir(os.path.join(data_dir, "failed"))), 1)

    def test_incomplete_or_invalid_geometry_never_selects_a_snapshot(self):
        invalid_documents = (
            b"<kml><Document/></kml>",
            b"<kml><Document><NetworkLink><Link><href>https://example.test/kml</href></Link></NetworkLink></Document></kml>",
            KML.replace(b"133.5,33.5,10", b"nan,33.5,10"),
            KML.replace(b"133.5,33.5,10", b"0,0,10"),
            KML.replace(b"<Point>", b"<Polygon>").replace(b"</Point>", b"</Polygon>"),
            KML.replace(b"#line-blue", b"#missing-style"),
        )
        with tempfile.TemporaryDirectory() as directory:
            with patch("datasets.mizutani_henro_map.fetch._download", return_value=(200, {}, KML)):
                fetch(directory)
            current = Path(directory, "current.json").read_bytes()
            for body in invalid_documents:
                with self.subTest(body=body):
                    with patch("datasets.mizutani_henro_map.fetch._download", return_value=(200, {}, body)):
                        with self.assertRaises(ValueError):
                            fetch(directory)
                    self.assertEqual(Path(directory, "current.json").read_bytes(), current)
            self.assertEqual(len(list(Path(directory, "snapshots").iterdir())), 1)

    def test_unchanged_fetch_preserves_snapshot_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("datasets.mizutani_henro_map.fetch._download", return_value=(200, {}, KML)):
                with patch("datasets.mizutani_henro_map.fetch.utc_now", return_value="2026-01-01T00:00:00Z"):
                    first = fetch(directory)
                metadata = Path(directory, "snapshots", first["sha256"], "metadata.json").read_bytes()
                with patch("datasets.mizutani_henro_map.fetch.utc_now", return_value="2026-02-01T00:00:00Z"):
                    fetch(directory)
            self.assertEqual(Path(directory, "snapshots", first["sha256"], "metadata.json").read_bytes(), metadata)
            current = json.loads(Path(directory, "current.json").read_text())
            self.assertEqual(current["snapshot_retrieved_at"], "2026-01-01T00:00:00Z")
            self.assertEqual(current["last_checked_at"], "2026-02-01T00:00:00Z")
