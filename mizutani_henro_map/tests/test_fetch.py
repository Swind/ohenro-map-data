import json
import os
import tempfile
import unittest
from unittest.mock import patch

from mizutani_henro_map.fetch import fetch

KML = b'<?xml version="1.0"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document/></kml>'


class TestFetch(unittest.TestCase):
    def test_archives_once_and_updates_current_check(self):
        with tempfile.TemporaryDirectory() as data_dir:
            with patch("mizutani_henro_map.fetch._download", return_value=(200, {"Content-Type": "text/xml"}, KML)):
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
            with patch("mizutani_henro_map.fetch._download", return_value=(200, {}, KML)):
                original = fetch(data_dir)["sha256"]
            with patch("mizutani_henro_map.fetch._download", return_value=(200, {}, b"<html>bad</html>")):
                with self.assertRaises(ValueError):
                    fetch(data_dir)
            with open(os.path.join(data_dir, "current.json"), encoding="utf-8") as stream:
                self.assertEqual(json.load(stream)["sha256"], original)
            self.assertEqual(len(os.listdir(os.path.join(data_dir, "failed"))), 1)
