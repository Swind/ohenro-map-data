"""Phase 1 normalization orchestration for 88sekaiisan route/temple snapshots.

Resolves a snapshot (``current`` or a 64-hex hash), maps archive local paths to
their source filenames/hashes via ``metadata.json``, parses exactly the 4 route
and 4 temple KML files, validates temple numbers 1..88, and writes a
deterministic JSON document atomically (temp -> flush -> fsync -> replace).
"""

from __future__ import annotations

import hashlib
import json
import os
import re

from datasets.sekaiisan_henro import parser

ROUTE_FILES = (
    ("routes/tokushima.kml", "tokushima"),
    ("routes/kochi.kml", "kochi"),
    ("routes/ehime.kml", "ehime"),
    ("routes/kagawa.kml", "kagawa"),
)
TEMPLE_FILES = ("temples/1-23.kml", "temples/24-39.kml", "temples/40-65.kml", "temples/66-88.kml")
TOILET_FILES = (
    ("toilets/tokushima.kml", "tokushima"),
    ("toilets/kochi.kml", "kochi"),
    ("toilets/ehime.kml", "ehime"),
    ("toilets/kagawa.kml", "kagawa"),
)
SNAPSHOT_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


def resolve_snapshot(data_dir: str, snapshot: str) -> tuple[str, str]:
    """Return (snapshot_dir, snapshot_sha256) for ``current`` or a hash."""
    if snapshot == "current":
        current_path = os.path.join(data_dir, "current.json")
        if not os.path.exists(current_path):
            raise ValueError("current.json not found in %s" % data_dir)
        with open(current_path, encoding="utf-8") as stream:
            current = json.load(stream)
        sha = current.get("sha256")
        if not sha:
            raise ValueError("current.json has no sha256")
    else:
        sha = snapshot.lower()
        if not SNAPSHOT_HASH_RE.fullmatch(sha):
            raise ValueError("snapshot must be 'current' or a 64-hex sha256")
    snapshot_dir = os.path.join(data_dir, "snapshots", sha)
    if not os.path.isdir(snapshot_dir):
        raise ValueError("snapshot directory not found: %s" % snapshot_dir)
    return snapshot_dir, sha


def _load_metadata(snapshot_dir: str) -> dict:
    path = os.path.join(snapshot_dir, "metadata.json")
    if not os.path.exists(path):
        raise ValueError("metadata.json not found in %s" % snapshot_dir)
    with open(path, encoding="utf-8") as stream:
        return json.load(stream)


def _read_kml(snapshot_dir: str, local_path: str, expected_sha: str | None) -> bytes:
    path = os.path.join(snapshot_dir, local_path)
    if not os.path.exists(path):
        raise ValueError("archive file missing: %s" % local_path)
    with open(path, "rb") as stream:
        body = stream.read()
    if expected_sha and hashlib.sha256(body).hexdigest() != expected_sha:
        raise ValueError("sha256 mismatch for archive file: %s" % local_path)
    return body


def _file_map(metadata: dict) -> dict:
    """Map local_path -> {"source_file": str, "sha256": str}."""
    mapping = {}
    for entry in metadata.get("files", []):
        mapping[entry["local_path"]] = {
            "source_file": entry.get("source_file"),
            "sha256": entry.get("sha256"),
        }
    return mapping


def build_normalized(data_dir: str, snapshot: str) -> dict:
    """Parse the selected snapshot and return the deterministic output dict."""
    snapshot_dir, sha = resolve_snapshot(data_dir, snapshot)
    metadata = _load_metadata(snapshot_dir)
    file_map = _file_map(metadata)

    routes: list[dict] = []
    accounting = {"routes": 0, "linestrings": 0, "points": 0, "temples": 0, "toilets": 0, "missing_source_fid": 0, "by_prefecture": {}}
    for local_path, prefecture in ROUTE_FILES:
        info = file_map.get(local_path)
        if info is None:
            raise ValueError("route file not in snapshot metadata: %s" % local_path)
        body = _read_kml(snapshot_dir, local_path, info["sha256"])
        parsed = parser.parse_route_file(body, prefecture)
        sub = {
            "routes": parsed["placemark_count"],
            "linestrings": len(parsed["records"]),
            "points": sum(len(record["geometry"]["coordinates"]) for record in parsed["records"]),
            "missing_source_fid": parsed["missing_source_fid"],
        }
        accounting["routes"] += sub["routes"]
        accounting["linestrings"] += sub["linestrings"]
        accounting["points"] += sub["points"]
        accounting["missing_source_fid"] += sub["missing_source_fid"]
        accounting["by_prefecture"][prefecture] = sub
        for record in parsed["records"]:
            record["source_file"] = info["source_file"]
            routes.append(record)

    temples: list[dict] = []
    seen: set[int] = set()
    for local_path in TEMPLE_FILES:
        info = file_map.get(local_path)
        if info is None:
            raise ValueError("temple file not in snapshot metadata: %s" % local_path)
        body = _read_kml(snapshot_dir, local_path, info["sha256"])
        for temple in parser.parse_temple_file(body, info["source_file"]):
            if temple["number"] in seen:
                raise ValueError("duplicate temple number %d" % temple["number"])
            seen.add(temple["number"])
            temples.append(temple)
    if seen != set(range(1, 89)):
        missing = sorted(set(range(1, 89)) - seen)
        raise ValueError("temple numbers missing: %s" % ", ".join(map(str, missing)))
    accounting["temples"] = len(temples)

    toilets: list[dict] = []
    toilet_defects: list[dict] = []
    for local_path, prefecture in TOILET_FILES:
        info = file_map.get(local_path)
        if info is None:
            raise ValueError("toilet file not in snapshot metadata: %s" % local_path)
        body = _read_kml(snapshot_dir, local_path, info["sha256"])
        parsed = parser.parse_toilet_file(body, prefecture)
        for toilet in parsed["toilets"]:
            toilet["source_file"] = info["source_file"]
            toilets.append(toilet)
        for defect in parsed["defects"]:
            defect["source_file"] = info["source_file"]
            toilet_defects.append(defect)
    accounting["toilets"] = len(toilets)
    accounting["toilet_defects"] = len(toilet_defects)
    accounting["by_prefecture"].setdefault("toilets", {})
    accounting["by_prefecture"].setdefault("toilet_defects", {})
    for prefecture in ("tokushima", "kochi", "ehime", "kagawa"):
        accounting["by_prefecture"]["toilets"][prefecture] = sum(
            1 for t in toilets if t["prefecture"] == prefecture
        )
        accounting["by_prefecture"]["toilet_defects"][prefecture] = sum(
            1 for d in toilet_defects if d["prefecture"] == prefecture
        )

    # Deterministic ordering: routes keep the declared ROUTE_FILES order
    # (tokushima, kochi, ehime, kagawa), then source order, then part; temples
    # sorted by number; toilets keep per-file source order. No prefecture
    # re-sort is applied.
    temples = sorted(temples, key=lambda t: t["number"])

    source_files = {}
    for local_path, _ in ROUTE_FILES:
        source_files[local_path] = file_map[local_path]
    for local_path in TEMPLE_FILES:
        source_files[local_path] = file_map[local_path]
    for local_path, _ in TOILET_FILES:
        source_files[local_path] = file_map[local_path]

    return {
        "schema_version": 1,
        "dataset_id": metadata.get("dataset_id"),
        "snapshot_sha256": sha,
        "routes": routes,
        "temples": temples,
        "toilets": toilets,
        "toilet_defects": toilet_defects,
        "source_files": source_files,
        "accounting": accounting,
    }


def write_atomic(path: str, data: dict) -> None:
    """Write ``data`` as pretty JSON to ``path`` atomically.

    On failure the pre-existing output (if any) is left untouched.
    """
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True).encode() + b"\n"
    temporary = path + ".tmp"
    with open(temporary, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def run_normalize(data_dir: str, snapshot: str, output: str) -> dict:
    """Build then atomically write the normalized document; return it."""
    result = build_normalized(data_dir, snapshot)
    write_atomic(output, result)
    return result