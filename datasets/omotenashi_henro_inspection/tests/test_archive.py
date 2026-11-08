import tempfile
import unittest
from unittest.mock import MagicMock, patch

from datasets.omotenashi_henro_inspection.__main__ import KML_URL, fetch


KML = b'<?xml version="1.0"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document><Placemark><LineString><coordinates>134,34 135,35</coordinates></LineString></Placemark></Document></kml>'


class TestArchive(unittest.TestCase):
    def test_archives_immutable_snapshot(self):
        response = MagicMock(status=200)
        response.read.return_value = KML
        response.headers.get.return_value = "application/vnd.google-earth.kml+xml"
        response.__enter__.return_value = response
        with tempfile.TemporaryDirectory() as data_dir, \
                patch("datasets.omotenashi_henro_inspection.__main__.discover", return_value=(KML_URL, [])), \
                patch("urllib.request.urlopen", return_value=response):
            first = fetch(data_dir, 30)
            second = fetch(data_dir, 30)
        self.assertTrue(first["new_snapshot"])
        self.assertFalse(second["new_snapshot"])
