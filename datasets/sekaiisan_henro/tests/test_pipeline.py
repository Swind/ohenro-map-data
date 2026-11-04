import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from datasets.sekaiisan_henro import pipeline
from datasets.sekaiisan_henro.__main__ import FILES, build_parser, dispatch, fetch
from datasets.sekaiisan_henro.tests import helpers


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.raw, self.output, self.reports = root / "raw", root / "output", root / "reports"
        old = "cd" * 32
        helpers.write_snapshot(str(self.raw), old, helpers.standard_route_counts(), list(range(1, 89)))
        directory = self.raw / "snapshots" / old
        metadata = pipeline.read(directory / "metadata.json")
        combined = hashlib.sha256()
        for name, _ in FILES:
            combined.update(name.encode() + b"\0" + bytes.fromhex(pipeline.digest(directory / name)))
        self.sha = combined.hexdigest()
        metadata["sha256"] = self.sha
        (directory / "metadata.json").write_text(json.dumps(metadata))
        directory.rename(directory.with_name(self.sha))
        (self.raw / "current.json").write_text(json.dumps({"sha256": self.sha}))

    def test_full_build_skip_validate_and_corruption(self):
        result = pipeline.build(self.raw, self.output, self.reports, bridge_m=0)
        self.assertEqual(result["status"], "published")
        self.assertEqual(result["files"], 15)
        with patch.object(pipeline.topology, "run_inventory", side_effect=AssertionError("must skip")):
            self.assertEqual(pipeline.build(self.raw, self.output, self.reports, bridge_m=0)["status"], "unchanged")
        args = build_parser().parse_args(["validate", "--output-dir", str(self.output), "--reports-dir", str(self.reports)])
        with patch.object(pipeline, "DATASET", self.raw):
            self.assertEqual(dispatch(args)["status"], "validated")
        path = self.output / pipeline.FILES["plan"]
        path.write_text("corrupt")
        with patch.object(pipeline, "DATASET", self.raw), self.assertRaisesRegex(ValueError, "Output changed"):
            dispatch(args)
        inputs = pipeline.snapshot_inputs(self.raw)
        self.assertFalse(pipeline.current(self.output, self.reports, inputs, pipeline.settings(0, None)))

    def test_force_failure_keeps_published_group(self):
        pipeline.build(self.raw, self.output, self.reports, bridge_m=0)
        before = {str(p): p.read_bytes() for p in self.output.rglob("*") if p.is_file()}
        with patch.object(pipeline.topology, "run_inventory", side_effect=ValueError("stage failed")):
            with self.assertRaisesRegex(ValueError, "stage failed"):
                pipeline.build(self.raw, self.output, self.reports, bridge_m=0, force=True)
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.output.rglob("*") if p.is_file()})
        self.assertEqual(list(self.output.parent.glob(".sekaiisan-build-*")), [])

    def test_corrupt_local_snapshot_is_rejected(self):
        path = self.raw / "snapshots" / self.sha / FILES[0][0]
        path.write_bytes(b"corrupted source")
        with self.assertRaisesRegex(ValueError, "Snapshot hash mismatch"):
            pipeline.snapshot_inputs(self.raw)

    def test_invalid_fetched_group_keeps_current(self):
        previous = (self.raw / "current.json").read_bytes()
        empty_kml = b'<kml xmlns="http://www.opengis.net/kml/2.2"><Document/></kml>'
        with patch("datasets.sekaiisan_henro.__main__._download", return_value=("application/xml", empty_kml)):
            with self.assertRaises(ValueError):
                fetch(str(self.raw), 30, validate_snapshot=True)
        self.assertEqual((self.raw / "current.json").read_bytes(), previous)

    def test_settings_changes_invalidate_and_reject_invalid_bridge(self):
        first = pipeline.settings(5, None)
        self.assertNotEqual(first, pipeline.settings(0, None))
        reference = self.raw / "reference.json"
        reference.write_text("first")
        before = pipeline.settings(5, reference)
        reference.write_text("changed")
        self.assertNotEqual(before, pipeline.settings(5, reference))
        with self.assertRaisesRegex(ValueError, "finite"):
            pipeline.settings(float("nan"), None)


if __name__ == "__main__":
    unittest.main()
