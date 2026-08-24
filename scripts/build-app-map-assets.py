#!/usr/bin/env python3
"""Build the phase-2b offline map app assets.

Generates the deterministic set of glyph (font) PBFs and sprite sheets that an
Android app installs alongside the phase-2 map pack, plus their license texts.
This is the "data repo" half of phase 2b: it produces everything under
``output/app-map-assets/``.

It is stdlib-only. The only external tools it invokes are:

* ``--font-maker`` -- a patched build of maplibre/font-maker (see
  ``scripts/app-map-assets/font-maker-unicode.patch`` and
  ``docs/app_map_assets.md``) used to rasterize a font into per-range glyph
  PBFs.
* ``--spritegen`` -- the existing Protomaps basemaps sprite generator Cargo
  binary (``basemaps/sprites``), reused to pack icon sprites.

See ``docs/app_map_assets.md`` for the schema, provenance and usage.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

# Pinned Noto Sans CJK JP Regular 2.004 (Sans2.004, commit
# 523d033d6cb47f4a80c58a35753646f5c3608a78). The immutable font is available at
# https://github.com/notofonts/noto-cjk/raw/Sans2.004/Sans/OTF/Japanese/NotoSansCJKjp-Regular.otf
FONT_STACK = "Noto Sans CJK JP Regular"
EXPECTED_FONT_SHA256 = "68a3fc98800b2a27b371f2fb79991daf3633bd89309d4ffaa6946fd587f375b5"

# Sprite icon-image keys reachable by the current map style, including
# ``townhall`` (reachable through the pois layer's dynamic ``['get','kind']``)
# and all road-shield variants.  Validated against each generated sprite index.
REQUIRED_SPRITE_KEYS = {
    "arrow",
    "capital",
    "townspot",
    "beach",
    "forest",
    "marina",
    "park",
    "peak",
    "zoo",
    "garden",
    "bench",
    "aerodrome",
    "train_station",
    "bus_stop",
    "ferry_terminal",
    "stadium",
    "university",
    "library",
    "school",
    "animal",
    "toilets",
    "drinking_water",
    "post_office",
    "building",
    "townhall",
    "restaurant",
    "fast_food",
    "cafe",
    "bar",
    "supermarket",
    "convenience",
    "books",
    "beauty",
    "electronics",
    "clothes",
    "attraction",
    "museum",
    "theatre",
    "artwork",
}
for _prefix in ("US:I", "NL:S-road", "generic_shield"):
    for _n in range(1, 6):
        REQUIRED_SPRITE_KEYS.add(f"{_prefix}-{_n}char")

# Relative (repo-root) paths of the source artifacts this builder reads.
INVENTORY_REL = os.path.join("scripts", "app-map-assets",
                             "noto-sans-cjk-jp-required-ranges.txt")
FLAVOR_REL = os.path.join("scripts", "app-map-assets", "sprites-light.json")
LICENSES_REL = {
    "Noto-Sans-CJK-OFL.txt": os.path.join(
        "scripts", "app-map-assets", "licenses", "Noto-Sans-CJK-OFL.txt"),
    "Tangram-Icons-MIT.txt": os.path.join(
        "scripts", "app-map-assets", "licenses", "Tangram-Icons-MIT.txt"),
}
DEFAULT_SPRITEGEN_REL = os.path.join(
    "basemaps", "sprites", "target", "release", "spritegen")
DEFAULT_REFILL_REL = os.path.join("basemaps", "sprites", "refill.svg")
DEFAULT_OUTPUT = os.path.join("output", "app-map-assets")


class RangeSet:
    """Ordered, validated collection of 256-codepoint glyph ranges."""

    def __init__(self, ranges):
        # ranges: list of (start, end) in ascending order.
        self.ranges = list(ranges)

    @classmethod
    def from_lines(cls, lines):
        ranges = []
        seen = set()
        last_start = -1
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            start_s, sep, end_s = line.partition("-")
            if not sep:
                raise ValueError(f"invalid range line: {line!r}")
            start, end = int(start_s), int(end_s)
            if start < 0 or start % 256 != 0:
                raise ValueError(f"range start not a multiple of 256: {line!r}")
            if end != start + 255:
                raise ValueError(f"range end must be start+255: {line!r}")
            if start in seen:
                raise ValueError(f"duplicate range: {line!r}")
            seen.add(start)
            if start <= last_start:
                raise ValueError(
                    f"ranges must be strictly ascending, got {line!r} "
                    f"after start {last_start}"
                )
            last_start = start
            ranges.append((start, end))
        return cls(ranges)

    def __iter__(self):
        return iter(self.ranges)

    def __len__(self):
        return len(self.ranges)

    def names(self):
        """Return ['0-255', ...] in numeric order."""
        return [f"{a}-{b}" for a, b in self.ranges]


def load_ranges(repo_root: str) -> RangeSet:
    """Load and validate the required range inventory file."""
    path = os.path.join(repo_root, INVENTORY_REL)
    with open(path, "r", encoding="utf-8") as handle:
        return RangeSet.from_lines(handle)


def stream_sha256(path: str, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            block = handle.read(chunk_size)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def verify_font(font_file: str) -> None:
    """Raise ValueError unless the font file's SHA-256 matches the pinned hash."""
    actual = stream_sha256(font_file)
    if actual != EXPECTED_FONT_SHA256:
        raise ValueError(
            f"font SHA-256 mismatch: expected {EXPECTED_FONT_SHA256}, "
            f"got {actual} for {font_file}"
        )


def run_font_maker(font_maker: str, font_file: str, out_dir: str) -> None:
    """Run font-maker into out_dir; returns the generated stack directory.

    font-maker creates out_dir itself and refuses to run into an existing
    directory, so we only ensure its parent exists.
    """
    os.makedirs(os.path.dirname(out_dir), exist_ok=True)
    if os.path.lexists(out_dir):
        raise RuntimeError(f"font-maker output dir already exists: {out_dir}")
    proc = subprocess.run(
        [font_maker, "--name", FONT_STACK, out_dir, font_file],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"font-maker failed (rc={proc.returncode}):\n"
            f"{proc.stdout}\n{proc.stderr}"
        )
    stack_dir = os.path.join(out_dir, FONT_STACK)
    if not os.path.isdir(stack_dir):
        raise RuntimeError(
            f"font-maker did not produce expected stack dir: {stack_dir}"
        )


def copy_glyphs(generated_stack_dir: str, dest_fonts_dir: str, ranges: RangeSet) -> None:
    """Copy exactly the required, non-empty glyph PBFs into dest_fonts_dir."""
    os.makedirs(dest_fonts_dir, exist_ok=True)
    for name in ranges.names():
        src = os.path.join(generated_stack_dir, f"{name}.pbf")
        if not os.path.isfile(src):
            raise RuntimeError(f"required glyph range not generated: {name}")
        if os.path.getsize(src) == 0:
            raise RuntimeError(f"required glyph range is empty: {name}")
        dst = os.path.join(dest_fonts_dir, f"{name}.pbf")
        shutil.copyfile(src, dst)


def generate_sprites(spritegen: str, refill_svg: str, flavor_json: str, dest_sprites_dir: str) -> None:
    """Run the basemaps spritegen into dest_sprites_dir and validate outputs."""
    os.makedirs(dest_sprites_dir, exist_ok=True)
    prefix = os.path.join(dest_sprites_dir, "light")
    proc = subprocess.run(
        [spritegen, refill_svg, flavor_json, prefix],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"spritegen failed (rc={proc.returncode}):\n"
            f"{proc.stdout}\n{proc.stderr}"
        )
    expected = ["light.json", "light.png", "light@2x.json", "light@2x.png"]
    for name in expected:
        path = os.path.join(dest_sprites_dir, name)
        if not os.path.isfile(path) or os.path.getsize(path) == 0:
            raise RuntimeError(f"sprite output missing or empty: {name}")
    for index_name in ("light.json", "light@2x.json"):
        with open(os.path.join(dest_sprites_dir, index_name),
                  "r", encoding="utf-8") as handle:
            index = json.load(handle)
        missing = REQUIRED_SPRITE_KEYS - set(index.keys())
        if missing:
            raise RuntimeError(
                f"sprite index {index_name} missing required icon-image "
                f"keys: {sorted(missing)}"
            )


def copy_licenses(repo_root: str, dest_licenses_dir: str) -> None:
    os.makedirs(dest_licenses_dir, exist_ok=True)
    for name, src_rel in LICENSES_REL.items():
        src = os.path.join(repo_root, src_rel)
        if not os.path.isfile(src) or os.path.getsize(src) == 0:
            raise RuntimeError(f"license source missing or empty: {src_rel}")
        shutil.copyfile(src, os.path.join(dest_licenses_dir, name))


def replace_dir_atomically(build_dir: str, target: str) -> None:
    """Replace target dir with build_dir via a transactional same-filesystem swap.

    The old target (if any) is moved aside first; only after the new directory
    is in place is the old copy removed.  On failure the previous target is
    restored.  build_dir must live in the same parent as target.  This is
    rollback-safe, not a crash-atomic guarantee: a crash mid-swap can leave
    temporary/backup directories behind.
    """
    target = os.path.abspath(target)
    parent = os.path.dirname(target) or "."
    backup = os.path.join(parent, ".app-map-assets-old")
    if os.path.lexists(backup):
        if os.path.isdir(backup) and not os.path.islink(backup):
            shutil.rmtree(backup)
        else:
            os.unlink(backup)
    if os.path.lexists(target):
        os.rename(target, backup)
    try:
        os.rename(build_dir, target)
    except BaseException:
        if os.path.lexists(backup) and not os.path.lexists(target):
            os.rename(backup, target)
        raise
    if os.path.lexists(backup):
        if os.path.isdir(backup) and not os.path.islink(backup):
            shutil.rmtree(backup)
        else:
            os.unlink(backup)


def repo_root_from_script() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def build_assets(
    *,
    repo_root: str,
    font_maker: str,
    font_file: str,
    spritegen: str,
    output: str,
) -> None:
    ranges = load_ranges(repo_root)
    if "159744-159999" not in ranges.names():
        raise ValueError(
            "required range inventory is missing 159744-159999 (U+270F4)"
        )

    verify_font(font_file)

    target = os.path.abspath(os.path.join(repo_root, output))
    parent = os.path.dirname(target)
    os.makedirs(parent, exist_ok=True)

    build_root = tempfile.mkdtemp(prefix=".app-map-assets-build-", dir=parent)
    try:
        app_dir = os.path.join(build_root, "app-map-assets")

        # 1. Glyphs.  The MapLibre glyph template is
        #    fonts/{fontstack}/{range}.pbf; on disk {fontstack} percent-decodes
        #    to the font stack name, so glyphs nest under
        #    fonts/<FONT_STACK>/<range>.pbf.
        raw_fonts = os.path.join(build_root, "raw", "fonts")
        run_font_maker(font_maker, font_file, raw_fonts)
        generated_stack = os.path.join(raw_fonts, FONT_STACK)
        dest_fonts = os.path.join(app_dir, "fonts", FONT_STACK)
        copy_glyphs(generated_stack, dest_fonts, ranges)

        # 2. Sprites.
        flavor = os.path.join(repo_root, FLAVOR_REL)
        refill = os.path.join(repo_root, DEFAULT_REFILL_REL)
        generate_sprites(spritegen, refill, flavor,
                         os.path.join(app_dir, "sprites"))

        # 3. Licenses.
        copy_licenses(repo_root, os.path.join(app_dir, "licenses"))

        # 4. Atomic swap into place.
        replace_dir_atomically(app_dir, target)
    finally:
        shutil.rmtree(build_root, ignore_errors=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the phase-2b offline map app assets."
    )
    parser.add_argument("--font-maker", required=True,
                        help="path to the patched font-maker binary")
    parser.add_argument("--font-file", required=True,
                        help="path to the pinned Noto Sans CJK JP Regular OTF")
    parser.add_argument(
        "--spritegen",
        default=None,
        help="path to the basemaps spritegen binary "
             "(default: basemaps/sprites/target/release/spritegen)",
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help=f"output directory (default: {DEFAULT_OUTPUT})",
    )
    args = parser.parse_args(argv)

    repo_root = repo_root_from_script()
    spritegen = args.spritegen or os.path.join(repo_root, DEFAULT_SPRITEGEN_REL)
    if not os.path.isfile(spritegen):
        parser.error(
            f"spritegen binary not found: {spritegen}. "
            "Build it with: cargo build --release --manifest-path "
            "basemaps/sprites/Cargo.toml"
        )

    try:
        build_assets(
            repo_root=repo_root,
            font_maker=args.font_maker,
            font_file=args.font_file,
            spritegen=spritegen,
            output=args.output,
        )
    except (ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())