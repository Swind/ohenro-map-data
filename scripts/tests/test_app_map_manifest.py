"""Focused unit tests for the app map pack manifest builder (v4).

Uses temporary tiny files (never the real ~117MB PMTiles) and imports the
builder via importlib since its filename contains a hyphen.
"""

import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest

MODULE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "build-app-map-manifest.py",
)

spec = importlib.util.spec_from_file_location("app_map_manifest", MODULE_PATH)
builder = importlib.util.module_from_spec(spec)
sys.modules["app_map_manifest"] = builder
spec.loader.exec_module(builder)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# Small deterministic inventory used in tests (a subset of the real 103 ranges,
# including the supplementary 159744-159999 that tests 0x110000 coverage).
TEST_INVENTORY = "0-255\n256-511\n159744-159999\n"


class TinyRepo:
    """Builds a temporary repo-root with tiny files mirroring the dev layout."""

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def write(self, rel: str, data: bytes):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(data)
        return path

    def write_inventory(self, content: str = TEST_INVENTORY):
        self.write(builder.INVENTORY_REL, content.encode("utf-8"))

    def materialize_core(self):
        for source_rel, _install, _role in builder.CORE_PACK:
            self.write(source_rel, source_rel.encode("utf-8"))

    def materialize_generated(self):
        base = os.path.join("output", "app-map-assets")
        for name in builder.SPRITE_FILES:
            self.write(os.path.join(base, "sprites", name), name.encode())
        for name in ["0-255.pbf", "256-511.pbf", "159744-159999.pbf"]:
            self.write(
                os.path.join(base, "fonts", "Noto Sans CJK JP Regular", name),
                b"glyph",
            )
        for name in builder.LICENSE_FILES:
            self.write(os.path.join(base, "licenses", name), name.encode())

    def cleanup(self):
        self.tmp.cleanup()


class ValidateVersionTest(unittest.TestCase):
    def test_valid_versions(self):
        for version in ("dev-20260824-v2", "1.0.0", "a_b-c.d", "ABC123"):
            self.assertEqual(builder.validate_version(version), version)

    def test_rejects_invalid(self):
        for version in ("", "has space", "v1.0\n", "日本語", "a/b"):
            with self.assertRaises(ValueError):
                builder.validate_version(version)

    def test_rejects_non_string(self):
        with self.assertRaises(ValueError):
            builder.validate_version(123)


class ValidateMinVersionCodeTest(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(builder.validate_minimum_app_version_code(4), 4)
        self.assertEqual(builder.validate_minimum_app_version_code(42), 42)

    def test_invalid_below_4(self):
        for code in (3, 2, 1, 0, -1, 1.5, "1", True, None):
            with self.assertRaises(ValueError):
                builder.validate_minimum_app_version_code(code)


class NormalizeBaseUrlTest(unittest.TestCase):
    def test_none_passthrough(self):
        self.assertIsNone(builder.normalize_base_url(None))

    def test_adds_trailing_slash(self):
        self.assertEqual(
            builder.normalize_base_url("https://example.com/data"),
            "https://example.com/data/",
        )

    def test_preserves_trailing_slash(self):
        self.assertEqual(
            builder.normalize_base_url("http://example.com/data/"),
            "http://example.com/data/",
        )

    def test_strips_whitespace(self):
        self.assertEqual(
            builder.normalize_base_url("  https://example.com  "),
            "https://example.com/",
        )

    def test_rejects_bad_scheme(self):
        for base in ("ftp://example.com", "file:///tmp", "example.com/path"):
            with self.assertRaises(ValueError):
                builder.normalize_base_url(base)

    def test_rejects_empty_or_no_host(self):
        for base in ("", "   ", "https://"):
            with self.assertRaises(ValueError):
                builder.normalize_base_url(base)

    def test_rejects_credentials_query_and_fragment(self):
        for base in (
            "https://user:pass@example.com/data",
            "https://example.com/data?token=x",
            "https://example.com/data#section",
        ):
            with self.assertRaises(ValueError):
                builder.normalize_base_url(base)


class LoadGlyphRangesTest(unittest.TestCase):
    def test_loads_numeric_order_and_validates(self):
        repo = TinyRepo()
        try:
            repo.write_inventory()
            ranges = builder.load_glyph_ranges(repo.root)
            self.assertEqual(
                ranges, ["0-255", "256-511", "159744-159999"]
            )
        finally:
            repo.cleanup()

    def test_rejects_invalid_inventory(self):
        repo = TinyRepo()
        try:
            repo.write_inventory("0-255\n256-511\n256-511\n")
            with self.assertRaises(ValueError):
                builder.load_glyph_ranges(repo.root)
        finally:
            repo.cleanup()

    def test_rejects_out_of_order_inventory(self):
        repo = TinyRepo()
        try:
            repo.write_inventory("256-511\n0-255\n")
            with self.assertRaises(ValueError):
                builder.load_glyph_ranges(repo.root)
        finally:
            repo.cleanup()


class GeneratedAssetSpecsTest(unittest.TestCase):
    def test_deterministic_roles_and_order(self):
        repo = TinyRepo()
        try:
            repo.write_inventory()
            specs = builder.generated_asset_specs(repo.root)
            roles = [role for _s, _p, role in specs]
            self.assertEqual(
                roles,
                ["sprite"] * 4 + ["glyph"] * 3 + ["license"] * 2,
            )
            # Install paths drop the app-map-assets prefix.
            paths = [p for _s, p, _r in specs]
            self.assertTrue(all(not p.startswith("app-map-assets") for p in paths))
            self.assertEqual(
                [p for p in paths if p.startswith("sprites/")],
                ["sprites/light.json", "sprites/light.png",
                 "sprites/light@2x.json", "sprites/light@2x.png"],
            )
            # Glyphs appear in numeric range order, nested under the font stack.
            glyph_paths = [
                p for p in paths if p.startswith("fonts/")
            ]
            self.assertEqual(
                glyph_paths,
                ["fonts/Noto Sans CJK JP Regular/0-255.pbf",
                 "fonts/Noto Sans CJK JP Regular/256-511.pbf",
                 "fonts/Noto Sans CJK JP Regular/159744-159999.pbf"],
            )
            license_paths = [p for p in paths if p.startswith("licenses/")]
            self.assertEqual(
                license_paths,
                ["licenses/Noto-Sans-CJK-OFL.txt",
                 "licenses/Tangram-Icons-MIT.txt"],
            )
        finally:
            repo.cleanup()


class BuildManifestTest(unittest.TestCase):
    def test_v4_schema_repeated_roles_and_order(self):
        repo = TinyRepo()
        try:
            repo.write_inventory()
            repo.materialize_core()
            repo.materialize_generated()
            specs = builder.CORE_PACK + builder.generated_asset_specs(repo.root)
            manifest = builder.build_manifest(
                specs,
                version="dev-test",
                minimum_app_version_code=4,
                base_url=None,
                manifest_dir="output",
                repo_root=repo.root,
            )
            self.assertEqual(manifest["schema_version"], 4)
            self.assertEqual(manifest["version"], "dev-test")
            self.assertEqual(manifest["minimum_app_version_code"], 4)
            # Deterministic order: 9 core (content last), 4 sprite, 3 glyph, 2 license.
            roles = [f["role"] for f in manifest["files"]]
            expected = (
                ["style", "basemap", "henrohub", "info_pois",
                 "nature_trail", "henroyado", "min88", "temples", "content"]
                + ["sprite"] * 4 + ["glyph"] * 3 + ["license"] * 2
            )
            self.assertEqual(roles, expected)
            # total_size equals sum of file sizes.
            expected_total = sum(
                os.path.getsize(os.path.join(repo.root, s))
                for s, _p, _r in specs
            )
            self.assertEqual(manifest["total_size"], expected_total)
            # Generated assets install under sprites/fonts/licenses, URLs
            # manifest-relative into output/app-map-assets/.
            by_path = {f["path"]: f for f in manifest["files"]}
            self.assertEqual(
                by_path["sprites/light.png"]["url"],
                "app-map-assets/sprites/light.png",
            )
            self.assertEqual(
                by_path["fonts/Noto Sans CJK JP Regular/0-255.pbf"]["url"],
                "app-map-assets/fonts/Noto%20Sans%20CJK%20JP%20Regular/0-255.pbf",
            )
            self.assertEqual(
                by_path["licenses/Noto-Sans-CJK-OFL.txt"]["url"],
                "app-map-assets/licenses/Noto-Sans-CJK-OFL.txt",
            )
            # Core role install paths preserved.
            self.assertEqual(by_path["temples.geojson"]["path"], "temples.geojson")
            self.assertEqual(by_path["content.sqlite"]["path"], "content.sqlite")
            self.assertEqual(
                by_path["content.sqlite"]["role"], "content",
            )
            self.assertEqual(
                by_path["style.json"]["url"],
                "../map-preview/src/style/style.json",
            )
        finally:
            repo.cleanup()

    def test_absolute_base_url_resolution(self):
        repo = TinyRepo()
        try:
            repo.write_inventory()
            repo.materialize_core()
            repo.materialize_generated()
            specs = builder.CORE_PACK + builder.generated_asset_specs(repo.root)
            manifest = builder.build_manifest(
                specs,
                version="dev-test",
                minimum_app_version_code=4,
                base_url="https://cdn.example.com/output/",
                manifest_dir="output",
                repo_root=repo.root,
            )
            by_path = {f["path"]: f for f in manifest["files"]}
            self.assertEqual(
                by_path["sprites/light.png"]["url"],
                "https://cdn.example.com/output/app-map-assets/sprites/light.png",
            )
            self.assertEqual(
                by_path["temples.geojson"]["url"],
                "https://cdn.example.com/output/temples.geojson",
            )
            # Encodings retained through --base-url resolution.
            self.assertEqual(
                by_path["fonts/Noto Sans CJK JP Regular/0-255.pbf"]["url"],
                "https://cdn.example.com/output/app-map-assets/fonts/"
                "Noto%20Sans%20CJK%20JP%20Regular/0-255.pbf",
            )
        finally:
            repo.cleanup()

    def test_missing_file_raises(self):
        repo = TinyRepo()
        try:
            repo.write_inventory()
            specs = builder.CORE_PACK + builder.generated_asset_specs(repo.root)
            # Only one core file exists; nothing else.
            repo.write("map-preview/src/style/style.json", b"style")
            with self.assertRaises(FileNotFoundError):
                builder.build_manifest(
                    specs,
                    version="dev-test",
                    minimum_app_version_code=4,
                    base_url=None,
                    manifest_dir="output",
                    repo_root=repo.root,
                )
        finally:
            repo.cleanup()


class AtomicWriteTest(unittest.TestCase):
    def test_writes_deterministic_json_and_cleans_temp(self):
        repo = TinyRepo()
        try:
            out_rel = "output/app-map-manifest.json"
            repo.write("output/.keep", b"")
            out_abs = os.path.join(repo.root, out_rel)
            data = {"b": 2, "a": [1, 3], "files": [{"z": "z", "a": "a"}]}
            builder.atomic_write_json(out_abs, data)
            with open(out_abs, "r", encoding="utf-8") as handle:
                content = handle.read()
            self.assertTrue(content.endswith("\n"))
            self.assertEqual(json.loads(content), data)
            first = json.dumps(data, indent=2, sort_keys=True) + "\n"
            self.assertEqual(content, first)
            leftovers = [
                name for name in os.listdir(os.path.dirname(out_abs))
                if name.startswith(".app-map-manifest-")
            ]
            self.assertEqual(leftovers, [])
        finally:
            repo.cleanup()

    def test_creates_parent_dir(self):
        repo = TinyRepo()
        try:
            out_abs = os.path.join(repo.root, "deep", "nested", "m.json")
            builder.atomic_write_json(out_abs, {"schema_version": 2})
            self.assertTrue(os.path.isfile(out_abs))
        finally:
            repo.cleanup()


class RelativeUrlEncodingTest(unittest.TestCase):
    def test_encodes_unsafe_chars_preserves_slash_and_dotdot(self):
        repo = TinyRepo()
        try:
            manifest_dir = os.path.abspath(os.path.join(repo.root, "output"))
            # Space, %, #, ?, Unicode in a file name under a fontstack dir.
            source = os.path.join(
                repo.root, "output", "app-map-assets", "fonts",
                "Noto Sans CJK JP Regular", "0-255.pbf",
            )
            url = builder.relative_url(source, manifest_dir)
            self.assertEqual(
                url,
                "app-map-assets/fonts/Noto%20Sans%20CJK%20JP%20Regular/0-255.pbf",
            )
            # Unicode percent-encoded as UTF-8.
            src2 = os.path.join(repo.root, "output", "héllo #1?.txt")
            self.assertEqual(
                builder.relative_url(src2, manifest_dir),
                "h%C3%A9llo%20%231%3F.txt",
            )
            # ../ relative segment preserved.
            src3 = os.path.join(repo.root, "map-preview", "src", "style", "style.json")
            self.assertEqual(
                builder.relative_url(src3, manifest_dir),
                "../map-preview/src/style/style.json",
            )
            # Encoded output feeds urljoin without losing encodings.
            self.assertEqual(
                builder.resolve_url(
                    "https://cdn.example.com/output/",
                    builder.relative_url(source, manifest_dir),
                ),
                "https://cdn.example.com/output/app-map-assets/fonts/"
                "Noto%20Sans%20CJK%20JP%20Regular/0-255.pbf",
            )
        finally:
            repo.cleanup()

    def test_install_path_keeps_raw_spaces(self):
        # The install `path` field must keep the unencoded name.
        repo = TinyRepo()
        try:
            repo.write_inventory()
            repo.materialize_core()
            repo.materialize_generated()
            specs = builder.CORE_PACK + builder.generated_asset_specs(repo.root)
            manifest = builder.build_manifest(
                specs,
                version="dev-test",
                minimum_app_version_code=4,
                base_url=None,
                manifest_dir="output",
                repo_root=repo.root,
            )
            by_path = {f["path"]: f for f in manifest["files"]}
            glyph = by_path["fonts/Noto Sans CJK JP Regular/0-255.pbf"]
            self.assertEqual(
                glyph["path"],
                "fonts/Noto Sans CJK JP Regular/0-255.pbf",
            )
            self.assertEqual(
                glyph["url"],
                "app-map-assets/fonts/Noto%20Sans%20CJK%20JP%20Regular/0-255.pbf",
            )
        finally:
            repo.cleanup()


class StreamSha256Test(unittest.TestCase):
    def test_matches_whole_file_hash(self):
        repo = TinyRepo()
        try:
            path = repo.write("blob.bin", b"hello world")
            self.assertEqual(
                builder.stream_sha256(path), sha256_bytes(b"hello world")
            )
        finally:
            repo.cleanup()


if __name__ == "__main__":
    unittest.main()
