import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from datasets.gsi import __main__ as pipeline


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.raw = self.root / "raw"
        self.reports = self.root / "reports"

    def archive(self, date="20250620"):
        path = self.raw / "DEM5/5A" / f"FG-GML-493203-DEM5A-{date}.zip"
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("sample.xml", "<test/>")
        return path

    def test_duplicate_versions_rejected(self):
        self.archive()
        self.archive("20260101")
        with self.assertRaisesRegex(ValueError, "Multiple versions"):
            pipeline.inventory(self.raw)

    def test_wrong_directory_rejected(self):
        path = self.archive()
        path.rename(self.raw / path.name)
        with self.assertRaisesRegex(ValueError, "Place"):
            pipeline.inventory(self.raw)

    def test_corrupt_zip_rejected(self):
        self.archive().write_bytes(b"not a ZIP")
        with self.assertRaises(zipfile.BadZipFile):
            pipeline.inventory(self.raw, verify=True)

    def test_update_report_and_build_gate(self):
        path = self.archive()
        record = {"file_name": path.name.replace("20250620", "20260101"),
                  "type_code": "DEM5A", "place_code": "493203"}
        data = json.dumps({"result": {"status": "success"}, "results": [record]}).encode()
        with patch.object(pipeline, "urlopen", return_value=io.BytesIO(data)):
            self.assertFalse(pipeline.check(self.raw, self.reports))
        report = json.loads((self.reports / "updates.json").read_text())
        self.assertEqual(report["obsolete_or_extra"], [path.name])
        self.assertEqual(report["missing_or_updated"], [record["file_name"]])
        with patch.object(pipeline, "DATASET", self.root), patch.object(pipeline, "check", return_value=False), patch.object(pipeline, "build") as build:
            self.assertEqual(pipeline.main([]), 1)
            build.assert_not_called()

    def test_failed_conversion_keeps_existing_outputs(self):
        self.archive()
        output = self.root / "output"
        output.mkdir()
        for name in pipeline.OUTPUTS:
            (output / name).write_bytes(b"last good build")
        with patch.object(pipeline.shutil, "which", return_value="tool"), \
             patch.object(pipeline.importlib.util, "find_spec", return_value=True), \
             patch.object(pipeline, "run"), \
             patch.object(pipeline.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)), \
             patch.object(pipeline, "rust", side_effect=ValueError("conversion failed")):
            with self.assertRaisesRegex(ValueError, "conversion failed"):
                pipeline.build(self.raw, output, self.reports)
        for name in pipeline.OUTPUTS:
            self.assertEqual((output / name).read_bytes(), b"last good build")
        self.assertEqual(list(self.root.glob(".gsi-build-*")), [])

    def current_build(self):
        path = self.archive()
        output = self.root / "output"
        output.mkdir()
        for name in pipeline.OUTPUTS:
            (output / name).write_bytes(b"validated output")
        hashes = {path.name: pipeline.digest(path)}
        config = pipeline.build_config()
        report = {"input_sha256": hashes, "build_config": config,
                  "outputs": {name: {"size": (output / name).stat().st_size,
                                      "sha256": pipeline.digest(output / name)} for name in pipeline.OUTPUTS}}
        pipeline.write_json(self.reports / "pipeline.json", report)
        return output, hashes, config

    def test_unchanged_skips_tools_but_force_rebuilds(self):
        output, _hashes, _config = self.current_build()
        with patch.object(pipeline.shutil, "which", return_value=None) as which:
            pipeline.build(self.raw, output, self.reports)
            which.assert_not_called()
            with self.assertRaisesRegex(ValueError, "Missing cargo"):
                pipeline.build(self.raw, output, self.reports, force=True)

    def test_changed_inputs_settings_or_outputs_invalidate_build(self):
        output, hashes, config = self.current_build()
        self.assertTrue(pipeline.is_current(output, self.reports, hashes, config))
        self.assertFalse(pipeline.is_current(output, self.reports, {}, config))
        with patch.dict(pipeline.os.environ, {"CONTOUR_INTERVAL": "40"}):
            self.assertFalse(pipeline.is_current(output, self.reports, hashes, pipeline.build_config()))
        path = output / pipeline.OUTPUTS[0]
        path.write_bytes(b"corrupted output")  # Same size: hash, not just size, must be checked.
        self.assertFalse(pipeline.is_current(output, self.reports, hashes, config))
        path.unlink()
        self.assertFalse(pipeline.is_current(output, self.reports, hashes, config))

    def test_missing_old_or_malformed_report_requires_build(self):
        output, hashes, config = self.current_build()
        path = self.reports / "pipeline.json"
        report = json.loads(path.read_text())
        del report["build_config"]
        pipeline.write_json(path, report)
        self.assertFalse(pipeline.is_current(output, self.reports, hashes, config))
        path.write_text("broken json")
        self.assertFalse(pipeline.is_current(output, self.reports, hashes, config))
        path.unlink()
        self.assertFalse(pipeline.is_current(output, self.reports, hashes, config))


if __name__ == "__main__":
    unittest.main()
