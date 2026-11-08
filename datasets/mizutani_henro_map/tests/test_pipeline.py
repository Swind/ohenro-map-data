from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from datasets.mizutani_henro_map.fetch import fetch
from datasets.mizutani_henro_map.pipeline import OUTPUTS, build, source

KML = (Path(__file__).parent / "fixtures" / "map.kml").read_bytes()


class TestPipelineSourceBoundary(unittest.TestCase):
    def test_corrupted_source_cannot_replace_any_published_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            raw, output, reports = (Path(directory) / name for name in ("raw", "output", "reports"))
            with patch("datasets.mizutani_henro_map.fetch._download", return_value=(200, {}, KML)):
                snapshot = fetch(str(raw))["sha256"]
            self.assertEqual(source(raw)["snapshot_sha256"], snapshot)
            current = (raw / "current.json").read_bytes()
            output.mkdir()
            reports.mkdir()
            for name in OUTPUTS:
                (output / name).write_bytes(b"previous publication: " + name.encode())
            (reports / "pipeline.json").write_text('{"previous": true}\n')
            old_outputs = {name: (output / name).read_bytes() for name in OUTPUTS}
            old_report = (reports / "pipeline.json").read_bytes()
            # Even well-formed, in-bounds geometry must match its immutable source SHA.
            (raw / "snapshots" / snapshot / "map.kml").write_bytes(
                KML.replace(b"133.5,33.5,10", b"133.6,33.5,10"))
            with self.assertRaisesRegex(ValueError, "integrity"):
                build(raw, output, reports)
            self.assertEqual((raw / "current.json").read_bytes(), current)
            self.assertEqual({name: (output / name).read_bytes() for name in OUTPUTS}, old_outputs)
            self.assertEqual((reports / "pipeline.json").read_bytes(), old_report)
