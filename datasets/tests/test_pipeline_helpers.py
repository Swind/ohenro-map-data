import json
from pathlib import Path
import tempfile
import unittest

from datasets import _pipeline as pipeline


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.stage = self.root / "stage"
        self.output = self.root / "output"
        self.reports = self.root / "reports"
        self.stage.mkdir()
        self.output.mkdir()

    def test_missing_staged_file_does_not_replace_any_published_file(self):
        (self.output / "a.json").write_text("old a")
        (self.output / "b.json").write_text("old b")
        (self.stage / "a.json").write_text("new a")
        with self.assertRaises(FileNotFoundError):
            pipeline.publish(self.stage, self.output, self.reports, ("a.json", "b.json"), {}, {}, {})
        self.assertEqual((self.output / "a.json").read_text(), "old a")
        self.assertEqual((self.output / "b.json").read_text(), "old b")
        self.assertFalse((self.reports / "pipeline.json").exists())

    def test_publication_preserves_unmanaged_files_and_detects_later_corruption(self):
        (self.output / "user.json").write_text("user data")
        (self.stage / "data.json").write_text('{"count": 7}')
        pipeline.publish(self.stage, self.output, self.reports, ("data.json",), {"source": "abc"}, {}, {"count": 7})
        self.assertEqual((self.output / "user.json").read_text(), "user data")
        self.assertTrue(pipeline.is_current(self.output, self.reports, {"source": "abc"}, {}, ("data.json",)))
        (self.output / "data.json").write_text('{"count": 8}')
        self.assertFalse(pipeline.is_current(self.output, self.reports, {"source": "abc"}, {}, ("data.json",)))
        with self.assertRaisesRegex(ValueError, "hash"):
            pipeline.verify_report(self.output, self.reports, ("data.json",))

    def test_changed_source_or_settings_never_skips_build(self):
        (self.stage / "data.json").write_text("{}")
        pipeline.publish(self.stage, self.output, self.reports, ("data.json",), {"source": "abc"}, {"zoom": 14}, {})
        self.assertFalse(pipeline.is_current(self.output, self.reports, {"source": "def"}, {"zoom": 14}, ("data.json",)))
        self.assertFalse(pipeline.is_current(self.output, self.reports, {"source": "abc"}, {"zoom": 13}, ("data.json",)))

    def test_temporary_build_outputs_do_not_change_source_code_identity(self):
        source = self.root / "dataset"
        source.mkdir()
        (source / "__main__.py").write_text("print('source')\n")
        baseline = pipeline.code_hash(source)
        temporary = source / ".dataset-build-work"
        temporary.mkdir()
        (temporary / "generated.json").write_text('{"generated": true}')
        self.assertEqual(pipeline.code_hash(source), baseline)
        (source / "__main__.py").write_text("print('new source')\n")
        self.assertNotEqual(pipeline.code_hash(source), baseline)


if __name__ == "__main__":
    unittest.main()
