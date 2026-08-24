"""Focused stdlib unit tests for scripts/build-app-map-assets.py.

Tests the pure stdlib pieces (range parsing, hash validation, glyph copying,
atomic directory replacement) without invoking the external font-maker or
spritegen binaries.
"""

import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest

MODULE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "build-app-map-assets.py",
)
spec = importlib.util.spec_from_file_location("app_map_assets", MODULE_PATH)
builder = importlib.util.module_from_spec(spec)
sys.modules["app_map_assets"] = builder
spec.loader.exec_module(builder)


class RangeSetTest(unittest.TestCase):
    def test_parses_valid_ranges(self):
        rs = builder.RangeSet.from_lines(
            ["0-255\n", "256-511\n", "159744-159999\n"]
        )
        self.assertEqual(
            rs.names(), ["0-255", "256-511", "159744-159999"]
        )
        self.assertEqual(len(rs), 3)

    def test_rejects_start_not_multiple_of_256(self):
        with self.assertRaises(ValueError):
            builder.RangeSet.from_lines(["1-256\n"])

    def test_rejects_wrong_end(self):
        with self.assertRaises(ValueError):
            builder.RangeSet.from_lines(["0-256\n"])

    def test_rejects_duplicate(self):
        with self.assertRaises(ValueError):
            builder.RangeSet.from_lines(["0-255\n", "0-255\n"])

    def test_rejects_out_of_order(self):
        with self.assertRaises(ValueError):
            builder.RangeSet.from_lines(["256-511\n", "0-255\n"])

    def test_rejects_non_ascending(self):
        with self.assertRaises(ValueError):
            builder.RangeSet.from_lines(["0-255\n", "512-767\n", "256-511\n"])

    def test_ignores_comments_and_blank_lines(self):
        rs = builder.RangeSet.from_lines(["# note\n", "\n", "0-255\n"])
        self.assertEqual(rs.names(), ["0-255"])


class LoadRangesTest(unittest.TestCase):
    def test_real_inventory_is_103_and_contains_159744(self):
        repo = tempfile.mkdtemp()
        try:
            # Point at the real inventory via a real repo root path.
            real_root = os.path.dirname(
                os.path.dirname(os.path.abspath(MODULE_PATH))
            )
            rs = builder.load_ranges(real_root)
            self.assertEqual(len(rs), 103)
            self.assertIn("159744-159999", rs.names())
            self.assertIn("0-255", rs.names())
            self.assertIn("65280-65535", rs.names())
            # Strictly ascending numeric order, no duplicates.
            self.assertEqual(rs.names(), sorted(rs.names(),
                                                key=lambda n: int(n.split("-")[0])))
            self.assertEqual(len(rs.names()), len(set(rs.names())))
        finally:
            shutil.rmtree(repo)


class VerifyFontTest(unittest.TestCase):
    def test_rejects_wrong_hash(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".otf") as fh:
            fh.write(b"not the pinned font")
            path = fh.name
        try:
            with self.assertRaises(ValueError) as ctx:
                builder.verify_font(path)
            self.assertIn("SHA-256 mismatch", str(ctx.exception))
        finally:
            os.unlink(path)


class CopyGlyphsTest(unittest.TestCase):
    def test_copies_required_non_empty(self):
        tmp = tempfile.mkdtemp()
        try:
            src = os.path.join(tmp, "gen", builder.FONT_STACK)
            os.makedirs(src)
            rs = builder.RangeSet.from_lines(["0-255\n", "256-511\n"])
            for name in rs.names():
                with open(os.path.join(src, f"{name}.pbf"), "wb") as fh:
                    fh.write(b"x")
            dest = os.path.join(tmp, "app", "fonts")
            builder.copy_glyphs(src, dest, rs)
            for name in rs.names():
                self.assertTrue(os.path.isfile(os.path.join(dest, f"{name}.pbf")))
            # Only the required ranges are copied.
            self.assertEqual(
                sorted(os.listdir(dest)), ["0-255.pbf", "256-511.pbf"]
            )
        finally:
            shutil.rmtree(tmp)

    def test_fails_on_missing(self):
        tmp = tempfile.mkdtemp()
        try:
            src = os.path.join(tmp, "gen", builder.FONT_STACK)
            os.makedirs(src)
            rs = builder.RangeSet.from_lines(["0-255\n", "256-511\n"])
            # Only one generated.
            with open(os.path.join(src, "0-255.pbf"), "wb") as fh:
                fh.write(b"x")
            dest = os.path.join(tmp, "app", "fonts")
            with self.assertRaises(RuntimeError) as ctx:
                builder.copy_glyphs(src, dest, rs)
            self.assertIn("256-511", str(ctx.exception))
        finally:
            shutil.rmtree(tmp)

    def test_fails_on_empty(self):
        tmp = tempfile.mkdtemp()
        try:
            src = os.path.join(tmp, "gen", builder.FONT_STACK)
            os.makedirs(src)
            rs = builder.RangeSet.from_lines(["0-255\n"])
            with open(os.path.join(src, "0-255.pbf"), "wb") as fh:
                fh.write(b"")
            dest = os.path.join(tmp, "app", "fonts")
            with self.assertRaises(RuntimeError) as ctx:
                builder.copy_glyphs(src, dest, rs)
            self.assertIn("empty", str(ctx.exception))
        finally:
            shutil.rmtree(tmp)


class SpriteKeysTest(unittest.TestCase):
    def test_complete_required_keys(self):
        keys = builder.REQUIRED_SPRITE_KEYS
        expected = {
            "arrow", "capital", "townspot",
            "beach", "forest", "marina", "park", "peak", "zoo", "garden",
            "bench", "aerodrome", "train_station", "bus_stop", "ferry_terminal",
            "stadium", "university", "library", "school", "animal", "toilets",
            "drinking_water", "post_office", "building", "townhall",
            "restaurant", "fast_food", "cafe", "bar", "supermarket",
            "convenience", "books", "beauty", "electronics", "clothes",
            "attraction", "museum", "theatre", "artwork",
        }
        for prefix in ("US:I", "NL:S-road", "generic_shield"):
            for n in range(1, 6):
                expected.add(f"{prefix}-{n}char")
        self.assertEqual(keys, expected)
        # Spot-check a few.
        for k in ("townhall", "arrow", "train_station", "beach", "artwork",
                  "generic_shield-5char", "US:I-1char", "NL:S-road-3char"):
            self.assertIn(k, keys)


class ReplaceDirAtomicallyTest(unittest.TestCase):
    def test_replaces_successfully(self):
        tmp = tempfile.mkdtemp()
        try:
            target = os.path.join(tmp, "app-map-assets")
            build = os.path.join(tmp, "app-map-assets")
            os.makedirs(os.path.join(target, "sprites"))
            with open(os.path.join(target, "sprites", "old.txt"), "w") as fh:
                fh.write("old")
            # Build a new directory in the same parent.
            new = os.path.join(tmp, ".app-map-assets-build-x")
            os.makedirs(os.path.join(new, "sprites"))
            with open(os.path.join(new, "sprites", "new.txt"), "w") as fh:
                fh.write("new")
            builder.replace_dir_atomically(new, target)
            self.assertTrue(
                os.path.isfile(os.path.join(target, "sprites", "new.txt"))
            )
            self.assertFalse(
                os.path.exists(os.path.join(target, "sprites", "old.txt"))
            )
            self.assertFalse(os.path.exists(new))
            # No leftover backup.
            self.assertFalse(
                os.path.exists(os.path.join(tmp, ".app-map-assets-old"))
            )
        finally:
            shutil.rmtree(tmp)

    def test_preserves_old_target_on_failure(self):
        tmp = tempfile.mkdtemp()
        try:
            target = os.path.join(tmp, "app-map-assets")
            os.makedirs(target)
            with open(os.path.join(target, "keep.txt"), "w") as fh:
                fh.write("keep")
            # build_dir does not exist -> rename fails.
            missing = os.path.join(tmp, ".app-map-assets-build-missing")
            with self.assertRaises(FileNotFoundError):
                builder.replace_dir_atomically(missing, target)
            # Old target preserved, backup cleaned up.
            self.assertTrue(
                os.path.isfile(os.path.join(target, "keep.txt"))
            )
            self.assertFalse(
                os.path.exists(os.path.join(tmp, ".app-map-assets-old"))
            )
        finally:
            shutil.rmtree(tmp)

    def test_installs_when_no_prior_target(self):
        tmp = tempfile.mkdtemp()
        try:
            target = os.path.join(tmp, "app-map-assets")
            build = os.path.join(tmp, ".app-map-assets-build-x")
            os.makedirs(build)
            with open(os.path.join(build, "a.txt"), "w") as fh:
                fh.write("a")
            builder.replace_dir_atomically(build, target)
            self.assertTrue(os.path.isfile(os.path.join(target, "a.txt")))
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()