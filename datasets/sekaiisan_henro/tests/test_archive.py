import os
import tempfile
import unittest
from unittest.mock import patch

from datasets.sekaiisan_henro.__main__ import FILES, fetch


KML = b'<?xml version="1.0"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document/></kml>'


class TestArchive(unittest.TestCase):
    def test_archives_full_group_before_current_pointer(self):
        with tempfile.TemporaryDirectory() as data_dir:
            with patch("datasets.sekaiisan_henro.__main__._download", return_value=("application/vnd.google-earth.kml+xml", KML)):
                result = fetch(data_dir, 30)
            self.assertEqual(result["files"], len(FILES))
            self.assertTrue(os.path.exists(os.path.join(data_dir, "current.json")))

    def test_failed_file_does_not_write_current_pointer(self):
        with tempfile.TemporaryDirectory() as data_dir:
            with patch("datasets.sekaiisan_henro.__main__._download", side_effect=ValueError("failed")):
                with self.assertRaises(ValueError):
                    fetch(data_dir, 30)
            self.assertFalse(os.path.exists(os.path.join(data_dir, "current.json")))
