#!/usr/bin/env python3
"""Build the phase-2 app map pack manifest.

Produces a deterministic JSON manifest describing the offline map-pack files an
Android app must install.  This is a stdlib-only tool: it streams SHA-256 so it
never loads the (potentially large) PMTiles files fully into RAM, and it writes
the manifest atomically (temp file in the same directory, then os.replace).

See docs/app_map_manifest.md for the schema and usage.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from urllib.parse import quote, urljoin, urlsplit


SCHEMA_VERSION = 4

# Version restricted to ASCII letters/digits/dot/underscore/hyphen.
VERSION_RE = re.compile(r"^[A-Za-z0-9._-]+$")

# The nine unique core roles: (repo-root-relative source, install path, role).
# The install paths intentionally match the source file names.
CORE_PACK = [
    ("map-preview/src/style/style.json", "style.json", "style"),
    ("output/shikoku-basemap.pmtiles", "shikoku-basemap.pmtiles", "basemap"),
    ("output/shikoku-henrohub.pmtiles", "shikoku-henrohub.pmtiles", "henrohub"),
    ("output/shikoku-info-pois.pmtiles", "shikoku-info-pois.pmtiles", "info_pois"),
    ("output/shikoku-nature-trail.pmtiles", "shikoku-nature-trail.pmtiles", "nature_trail"),
    ("output/shikoku-henroyado-lodging.pmtiles", "shikoku-henroyado-lodging.pmtiles", "henroyado"),
    ("output/shikoku-min88-lodging.pmtiles", "shikoku-min88-lodging.pmtiles", "min88"),
    ("output/temples.geojson", "temples.geojson", "temples"),
    ("output/content.sqlite", "content.sqlite", "content"),
]

# Deterministic generated asset spec templates (role -> install subdir, source
# subdir under output/app-map-assets/).  Glyph ranges are filled in from the
# required-range inventory; sprites and licenses are fixed-order.
SPRITE_FILES = [
    "light.json",
    "light.png",
    "light@2x.json",
    "light@2x.png",
]
LICENSE_FILES = [
    "Noto-Sans-CJK-OFL.txt",
    "Tangram-Icons-MIT.txt",
]

# Repo-root-relative inventory of required glyph ranges.
INVENTORY_REL = os.path.join(
    "scripts", "app-map-assets", "noto-sans-cjk-jp-required-ranges.txt")

DEFAULT_OUTPUT = os.path.join("output", "app-map-manifest.json")


def validate_version(version: str) -> str:
    """Return version if it satisfies the schema, else raise ValueError."""
    if not isinstance(version, str) or not version:
        raise ValueError("--version must be a non-empty string")
    if VERSION_RE.fullmatch(version) is None:
        raise ValueError(
            "--version must contain only ASCII letters, digits, '.', '_' or '-'"
        )
    return version


def validate_minimum_app_version_code(code: int) -> int:
    """Return minimum_app_version_code if it is an int >= 4, else raise.

    Schema v4 requires Android app versionCode >= 4.
    """
    if isinstance(code, bool) or not isinstance(code, int) or code < 4:
        raise ValueError("--minimum-app-version-code must be an integer >= 4")
    return code


def normalize_base_url(base_url: str | None) -> str | None:
    """Validate and normalize --base-url.

    Only http/https is accepted.  The result always ends in a trailing slash so
    relative URLs resolve against it as a directory.  Returns None when no base
    URL was supplied.
    """
    if base_url is None:
        return None
    if not isinstance(base_url, str):
        raise ValueError("--base-url must be a string")
    stripped = base_url.strip()
    if not stripped:
        raise ValueError("--base-url must not be empty")
    parts = urlsplit(stripped)
    if parts.scheme not in ("http", "https"):
        raise ValueError("--base-url must use http or https")
    if not parts.netloc:
        raise ValueError("--base-url must include a host")
    if parts.username is not None or parts.password is not None:
        raise ValueError("--base-url must not include credentials")
    if parts.query or parts.fragment:
        raise ValueError("--base-url must not include a query or fragment")
    if not stripped.endswith("/"):
        stripped += "/"
    return stripped


def stream_sha256(path: str, chunk_size: int = 1 << 20) -> str:
    """Return the lowercase hex SHA-256 of a file, streamed in chunks."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            block = handle.read(chunk_size)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def to_posix(path: str) -> str:
    """Convert a native path to POSIX separators for URL-safe output."""
    return path.replace(os.sep, "/") if os.sep != "/" else path


def relative_url(source_abs: str, manifest_dir_abs: str) -> str:
    """Return the manifest-relative URL for a source file (POSIX separators).

    The install path's URL is percent-encoded segment-by-segment with
    ``urllib.parse.quote`` so that URL-unsafe characters (space, ``%``, ``#``,
    ``?``, Unicode, ...) are encoded for use in a URL, while ``/`` separators
    and ``..`` relative segments are preserved.  (The install ``path`` field
    keeps the raw, unencoded name.)
    """
    rel = to_posix(os.path.relpath(source_abs, manifest_dir_abs))
    return quote(rel, safe="/")


def resolve_url(base_url: str | None, rel: str) -> str:
    """Resolve a relative URL against base_url, or return it unchanged."""
    if base_url is None:
        return rel
    return urljoin(base_url, rel)


def build_manifest(
    specs,
    *,
    version: str,
    minimum_app_version_code: int,
    base_url: str | None,
    manifest_dir: str,
    repo_root: str,
):
    """Build the manifest dict from a list of (source_rel, install_path, role).

    Reads each source file's size and streamed SHA-256.  Raises
    FileNotFoundError if a source is missing or not a regular file.
    """
    manifest_dir_abs = os.path.abspath(os.path.join(repo_root, manifest_dir))
    files = []
    total_size = 0
    for source_rel, install_path, role in specs:
        source_abs = os.path.abspath(os.path.join(repo_root, source_rel))
        if not os.path.isfile(source_abs):
            raise FileNotFoundError(
                "manifest source is missing or not a regular file: "
                + os.path.normpath(source_rel)
            )
        size = os.path.getsize(source_abs)
        digest = stream_sha256(source_abs)
        total_size += size
        rel = relative_url(source_abs, manifest_dir_abs)
        files.append(
            {
                "path": install_path,
                "url": resolve_url(base_url, rel),
                "size": size,
                "sha256": digest,
                "role": role,
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "version": version,
        "minimum_app_version_code": minimum_app_version_code,
        "total_size": total_size,
        "files": files,
    }


def atomic_write_json(path: str, data) -> None:
    """Write JSON to path atomically (temp in same dir, then os.replace)."""
    path_abs = os.path.abspath(path)
    directory = os.path.dirname(path_abs) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=directory, prefix=".app-map-manifest-", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path_abs)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def repo_root_from_script() -> str:
    """Return the data repo root derived from this script's own location."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_glyph_ranges(repo_root: str) -> list[str]:
    """Load the required glyph range names (e.g. '0-255') in numeric order."""
    path = os.path.join(repo_root, INVENTORY_REL)
    ranges = []
    seen = set()
    last_start = -1
    with open(path, "r", encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            start_s, sep, end_s = line.partition("-")
            if not sep:
                raise ValueError(f"invalid range line in inventory: {line!r}")
            start, end = int(start_s), int(end_s)
            if start % 256 != 0 or end != start + 255:
                raise ValueError(f"invalid range in inventory: {line!r}")
            if start in seen:
                raise ValueError(f"duplicate range in inventory: {line!r}")
            seen.add(start)
            if start <= last_start:
                raise ValueError(
                    f"inventory ranges must be strictly ascending, "
                    f"got {line!r} after start {last_start}"
                )
            last_start = start
            ranges.append(f"{start}-{end}")
    return ranges


def generated_asset_specs(repo_root: str):
    """Return the repeated-role specs (source_rel, install_path, role).

    Deterministically enumerates every generated asset under
    output/app-map-assets/: sprites, glyphs (numeric range order) and licenses.
    Install paths drop the app-map-assets prefix and live under sprites/,
    fonts/ and licenses/.
    """
    base = os.path.join("output", "app-map-assets")
    # Glyphs follow the MapLibre template fonts/{fontstack}/{range}.pbf, where
    # {fontstack} percent-decodes to the font stack name.
    fonts_dir = os.path.join(base, "fonts", "Noto Sans CJK JP Regular")
    specs = []
    for name in SPRITE_FILES:
        specs.append(
            (os.path.join(base, "sprites", name),
             os.path.join("sprites", name), "sprite")
        )
    for name in load_glyph_ranges(repo_root):
        specs.append(
            (os.path.join(fonts_dir, f"{name}.pbf"),
             os.path.join("fonts", "Noto Sans CJK JP Regular", f"{name}.pbf"),
             "glyph")
        )
    for name in LICENSE_FILES:
        specs.append(
            (os.path.join(base, "licenses", name),
             os.path.join("licenses", name), "license")
        )
    return specs


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the phase-2 app map pack manifest."
    )
    parser.add_argument("--version", required=True, help="manifest version string")
    parser.add_argument(
        "--minimum-app-version-code",
        type=int,
        default=4,
        help="minimum Android app version code (default: 4)",
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help=f"manifest output path (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="http(s) base URL to root absolute file URLs (optional)",
    )
    args = parser.parse_args(argv)

    try:
        version = validate_version(args.version)
        minimum_app_version_code = validate_minimum_app_version_code(
            args.minimum_app_version_code
        )
        base_url = normalize_base_url(args.base_url)
    except ValueError as exc:
        parser.error(str(exc))

    repo_root = repo_root_from_script()
    output_abs = os.path.abspath(os.path.join(repo_root, args.output))
    manifest_dir_rel = os.path.relpath(os.path.dirname(output_abs), repo_root)
    specs = CORE_PACK + generated_asset_specs(repo_root)
    manifest = build_manifest(
        specs,
        version=version,
        minimum_app_version_code=minimum_app_version_code,
        base_url=base_url,
        manifest_dir=manifest_dir_rel,
        repo_root=repo_root,
    )
    atomic_write_json(output_abs, manifest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
