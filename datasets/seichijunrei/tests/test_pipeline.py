import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from datasets.seichijunrei import __main__ as pipeline


def raw_records():
    content = {key: "" for key in (
        "short_name_en short_name_kana_ja long_name_ja long_name_en long_name_kana_ja "
        "tel_ja honzon_ja honzon_en syuha_ja syuha_en kaiki_ja kaiki_en souken_ja "
        "souken_en syukubou_ja rekishiyurai_ja rekishiyurai_en").split()}
    return [{"Spot": {"number": str(n), "id": str(n + 100), "spot_category_id": "3",
                      "latitude": "34.0", "longitude": "134.0", "post_code": "", "pref": "徳島県",
                      "address_ja": "", "address_en": "", "eyecatch": "", "modified": ""},
             "SpotContent": {**content, "id": str(n), "short_name_ja": f"寺{n}"}}
            for n in range(1, 89)]


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.raw = self.root / "raw"
        self.raw.mkdir()
        self.source = self.raw / "spots.json"
        self.source.write_text(json.dumps(raw_records()))

    def fetched(self, data):
        original = pipeline.script

        def script(name, *args):
            if name == "extract_henro.py":
                Path(args[1]).write_text(json.dumps(data))
            else:
                original(name, *args)
        return patch.object(pipeline, "script", side_effect=script)

    def test_bad_fetch_preserves_source(self):
        old = self.source.read_bytes()
        with self.fetched(raw_records()[:-1]):
            with self.assertRaisesRegex(ValueError, "88"):
                pipeline.fetch(self.raw)
        self.assertEqual(self.source.read_bytes(), old)
        self.assertFalse((self.raw / "snapshots").exists())

    def test_unchanged_fetch_then_update_preserves_snapshot(self):
        old = self.source.read_bytes()
        with self.fetched(raw_records()):
            pipeline.fetch(self.raw)
        self.assertFalse((self.raw / "snapshots").exists())
        updated = raw_records()
        updated[0]["SpotContent"]["short_name_ja"] = "更新寺"
        with self.fetched(updated):
            pipeline.fetch(self.raw)
        snapshots = list((self.raw / "snapshots").glob("*.json"))
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0].read_bytes(), old)
        self.assertEqual(json.loads(self.source.read_text()), updated)

    def test_failed_build_preserves_outputs(self):
        output = self.root / "output"
        output.mkdir()
        for name in pipeline.OUTPUTS:
            (output / name).write_text("old output")
        original = pipeline.run

        def fail_docker(command, **kwargs):
            if command[0] == "docker":
                raise ValueError("docker unavailable")
            original(command, **kwargs)
        with patch.object(pipeline.shutil, "which", return_value="tool"), \
             patch.object(pipeline, "run", side_effect=fail_docker):
            with self.assertRaisesRegex(ValueError, "docker unavailable"):
                pipeline.build(self.raw, output, self.root / "reports")
        for name in pipeline.OUTPUTS:
            self.assertEqual((output / name).read_text(), "old output")

    def test_skip_force_and_changed_output(self):
        output = self.root / "output"
        reports = self.root / "reports"
        output.mkdir()
        reports.mkdir()
        for name in pipeline.OUTPUTS:
            (output / name).write_bytes(b"ok")
        raw_hash, config = pipeline.digest(self.source), pipeline.config()
        report = {"input_sha256": raw_hash, "build_config": config,
                  "outputs": {name: {"size": 2, "sha256": pipeline.digest(output / name)} for name in pipeline.OUTPUTS}}
        (reports / "pipeline.json").write_text(json.dumps(report))
        with patch.object(pipeline.shutil, "which", return_value=None) as which:
            pipeline.build(self.raw, output, reports)
            which.assert_not_called()
            with self.assertRaisesRegex(ValueError, "Missing docker"):
                pipeline.build(self.raw, output, reports, force=True)
        (output / pipeline.OUTPUTS[0]).write_bytes(b"xx")
        self.assertFalse(pipeline.current(raw_hash, config, output, reports))
        self.assertFalse(pipeline.current("changed", config, output, reports))


if __name__ == "__main__":
    unittest.main()
