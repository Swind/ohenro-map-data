from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from datasets.henro_helper import tooling


class ToolingTests(unittest.TestCase):
    def test_cached_source_must_match_pin_and_be_unmodified(self):
        with tempfile.TemporaryDirectory() as temporary:
            tools = Path(temporary)
            source = tools / "blutter"
            source.mkdir()
            (source / "blutter.py").write_text("# cached upstream\n")
            for revision, changes in (("wrong", ""), (tooling.BLUTTER_REVISION, " M blutter.py")):
                with self.subTest(revision=revision, changes=changes), patch.object(
                    tooling, "_run", side_effect=[
                        subprocess.CompletedProcess([], 0, stdout=revision),
                        subprocess.CompletedProcess([], 0, stdout=changes),
                    ]
                ), self.assertRaisesRegex(RuntimeError, "modified or not at"):
                    tooling._source(tools)

    def test_disassemble_rejects_existing_output_before_bootstrap(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("libapp.so", "libflutter.so"):
                (root / name).write_bytes(b"library")
            output = root / "output"
            output.mkdir()
            (output / "keep").write_text("old output")
            with patch.object(tooling, "bootstrap") as bootstrap, self.assertRaisesRegex(RuntimeError, "Refusing to overwrite"):
                tooling.disassemble(root, output, root / "tools")
            bootstrap.assert_not_called()
            self.assertEqual((output / "keep").read_text(), "old output")

    def test_disassemble_requires_both_libraries(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "libapp.so").write_bytes(b"library")
            with patch.object(tooling, "bootstrap") as bootstrap, self.assertRaisesRegex(RuntimeError, "libflutter.so"):
                tooling.disassemble(root, root / "output", root / "tools")
            bootstrap.assert_not_called()

    def test_successful_command_without_outputs_is_an_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("libapp.so", "libflutter.so"):
                (root / name).write_bytes(b"library")
            with patch.object(tooling, "bootstrap", return_value={"backend": "host", "source": str(root), "python": "python"}), patch.object(
                tooling, "_host_requirements", return_value=({}, [])
            ), patch.object(tooling, "_run"), self.assertRaisesRegex(RuntimeError, "did not produce"):
                tooling.disassemble(root, root / "output", root / "tools")

