#!/usr/bin/env python3
"""Build a phase-4 downloadable route pack (route geometry + elevation profile).

The generic route-pack builder consumes canonical LineString GeoJSON plus an
already-built, provider-specific PMTiles, produces the elevation profile
``content.sqlite`` by invoking the existing GSI-DEM profile tool, and emits the
pack ``manifest.json``.  It does **not** build the PMTiles (that remains
provider-specific) and does not verify PMTiles contents.

Output is a single new directory containing exactly:

    manifest.json
    routes.pmtiles
    content.sqlite

The directory is built atomically: everything is staged in a sibling temp
directory (fsync'd where practical, SQLite integrity/foreign-key checked), then
``os.replace``'d into place.  Building is refused if the output directory
already exists, and the temp directory is cleaned up on every failure.

See docs/route_pack.md for the authoritative contract.  This is a stdlib-only
tool with no third-party dependencies.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from urllib.parse import urljoin, urlsplit


SCHEMA_VERSION = 1
SAMPLING_METHOD = "nearest_cell"

# Pack id / version restricted to ASCII letters/digits/dot/underscore/hyphen.
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")

# Fixed, deterministic page size set explicitly before any schema/row writes.
PAGE_SIZE = 4096

MINIMUM_APP_VERSION_CODE = 4

DEFAULT_INTERVAL_M = 20.0

LATITUDE_MIN, LATITUDE_MAX = -90.0, 90.0
LONGITUDE_MIN, LONGITUDE_MAX = -180.0, 180.0


def repo_root_from_script() -> str:
    """Return the data repo root derived from this script's own location."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


DEFAULT_GSI_DEM_BIN = os.path.join(
    repo_root_from_script(), "gsi-dem", "target", "release", "gsi-dem"
)


def encode_payload(value) -> str:
    """Serialize source properties as compact deterministic sorted UTF-8 JSON."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


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


def validate_safe_id(value: str, flag: str) -> str:
    """Return value if it is nonblank safe ASCII, else raise ValueError."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{flag} must be a non-empty string")
    if SAFE_ID_RE.fullmatch(value) is None:
        raise ValueError(
            f"{flag} must contain only ASCII letters, digits, '.', '_' or '-'"
        )
    return value


def validate_nonblank(value: str, flag: str) -> str:
    """Return value if it is a nonblank string, else raise ValueError."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{flag} must be a non-empty string")
    return value


def validate_minimum_app_version_code(code: int) -> int:
    """Return minimum_app_version_code if it is an int >= 4, else raise."""
    if isinstance(code, bool) or not isinstance(code, int) or code < MINIMUM_APP_VERSION_CODE:
        raise ValueError(
            f"--minimum-app-version-code must be an integer >= "
            f"{MINIMUM_APP_VERSION_CODE}"
        )
    return code


def validate_interval_m(interval: float) -> float:
    """Return interval_m if it is a positive finite number, else raise."""
    if isinstance(interval, bool) or not isinstance(interval, (int, float)):
        raise ValueError("--interval-m must be a number")
    interval = float(interval)
    if not math.isfinite(interval) or interval <= 0.0:
        raise ValueError("--interval-m must be a positive finite number")
    return interval


def normalize_base_url(base_url: str | None) -> str | None:
    """Validate and normalize --base-url (http/https, no creds/query/fragment).

    The result always ends in a trailing slash so relative URLs resolve against
    it as a directory.  Returns None when no base URL was supplied.
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


def _require_nonempty_regular_file(path: str, flag: str) -> None:
    if not os.path.isfile(path):
        raise ValueError(f"{flag} is missing or not a regular file: {path}")
    if os.path.getsize(path) <= 0:
        raise ValueError(f"{flag} must be a nonempty regular file: {path}")


def _validate_coordinate(position, context: str) -> None:
    """Validate a single [lon, lat] position is finite and in range."""
    if not isinstance(position, (list, tuple)) or len(position) < 2:
        raise ValueError(f"{context}: expected [lon, lat] position")
    lon, lat = position[0], position[1]
    if isinstance(lon, bool) or not isinstance(lon, (int, float)):
        raise ValueError(f"{context}: longitude must be numeric")
    if isinstance(lat, bool) or not isinstance(lat, (int, float)):
        raise ValueError(f"{context}: latitude must be numeric")
    if not (math.isfinite(float(lon)) and math.isfinite(float(lat))):
        raise ValueError(f"{context}: coordinates must be finite")
    if not LONGITUDE_MIN <= float(lon) <= LONGITUDE_MAX:
        raise ValueError(f"{context}: longitude out of range")
    if not LATITUDE_MIN <= float(lat) <= LATITUDE_MAX:
        raise ValueError(f"{context}: latitude out of range")


def read_and_validate_input(input_path: str) -> dict:
    """Load and strictly validate the canonical route GeoJSON input.

    Returns a structured dict:

        routes:           route_id -> {"name", "payload_properties", "segments"}
        route_ids:        set of route_ids
        segment_ids:      set of segment_ids
        segment_to_route: segment_id -> route_id

    Each feature must be a LineString with >= 2 finite, in-range coordinates and
    nonblank string route_id/segment_id/name properties.  segment_id is globally
    unique and a route's name must be consistent across its segments.
    """
    with open(input_path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict) or data.get("type") != "FeatureCollection":
        raise ValueError("input must be a GeoJSON FeatureCollection")

    features = data.get("features")
    if not isinstance(features, list) or not features:
        raise ValueError("input FeatureCollection must have at least one feature")

    routes: dict = {}
    route_ids = set()
    segment_ids = set()
    segment_to_route = {}
    for index, feature in enumerate(features, start=1):
        if not isinstance(feature, dict):
            raise ValueError(f"feature {index}: must be an object")
        properties = feature.get("properties")
        if not isinstance(properties, dict):
            raise ValueError(f"feature {index}: properties must be an object")

        route_id = properties.get("route_id")
        if not isinstance(route_id, str) or not route_id.strip():
            raise ValueError(f"feature {index}: properties.route_id must be nonblank")
        segment_id = properties.get("segment_id")
        if not isinstance(segment_id, str) or not segment_id.strip():
            raise ValueError(f"feature {index}: properties.segment_id must be nonblank")
        name = properties.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"feature {index}: properties.name must be nonblank")

        if segment_id in segment_ids:
            raise ValueError(f"duplicate segment_id: {segment_id!r}")
        segment_ids.add(segment_id)

        geometry = feature.get("geometry")
        if not isinstance(geometry, dict) or geometry.get("type") != "LineString":
            raise ValueError(f"feature {index} ({segment_id}): geometry must be a LineString")
        coordinates = geometry.get("coordinates")
        if not isinstance(coordinates, list) or len(coordinates) < 2:
            raise ValueError(
                f"feature {index} ({segment_id}): LineString needs >= 2 coordinates"
            )
        for point_index, position in enumerate(coordinates, start=1):
            _validate_coordinate(
                position, f"feature {index} ({segment_id}) coordinate {point_index}"
            )

        if route_id in routes:
            if routes[route_id]["name"] != name:
                raise ValueError(
                    f"route {route_id!r}: inconsistent name across segments"
                )
            routes[route_id]["segments"].append(feature)
        else:
            routes[route_id] = {
                "name": name,
                "payload_properties": properties,
                "segments": [feature],
            }
        route_ids.add(route_id)
        segment_to_route[segment_id] = route_id

    return {
        "routes": routes,
        "route_ids": route_ids,
        "segment_ids": segment_ids,
        "segment_to_route": segment_to_route,
    }


def _validate_finite_number(value, field: str, allow_none: bool = False):
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"profile {field} must be numeric")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"profile {field} must be finite")
    return value


def validate_profile(
    profile, input_data: dict, interval_m: float
) -> dict:
    """Strictly validate the gsi-dem profile output and index segments by id.

    Returns ``{segment_id: {distance_m, elevation_min_m, elevation_max_m,
    ascent_m, descent_m, missing_distance_m, samples}}``.

    Fail-closed on any mismatch; never silently repairs the profile.
    """
    if not isinstance(profile, dict):
        raise ValueError("profile must be a JSON object")
    if profile.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"profile schema_version must be {SCHEMA_VERSION}, "
            f"got {profile.get('schema_version')!r}"
        )
    sampling = profile.get("sampling")
    if not isinstance(sampling, dict):
        raise ValueError("profile must include an object 'sampling'")
    if sampling.get("method") != SAMPLING_METHOD:
        raise ValueError(
            f"profile sampling.method must be {SAMPLING_METHOD!r}, "
            f"got {sampling.get('method')!r}"
        )
    sampling_interval = sampling.get("interval_m")
    if isinstance(sampling_interval, bool) or not isinstance(
        sampling_interval, (int, float)
    ):
        raise ValueError("profile sampling.interval_m must be numeric")
    if not math.isclose(float(sampling_interval), interval_m):
        raise ValueError(
            f"profile sampling.interval_m {sampling_interval!r} does not match "
            f"requested interval {interval_m!r}"
        )

    routes = profile.get("routes")
    if not isinstance(routes, list):
        raise ValueError("profile must include an array 'routes'")

    seen_route = set()
    seen_segment = set()
    profile_segments: dict = {}
    for route_entry in routes:
        if not isinstance(route_entry, dict):
            raise ValueError("profile route entries must be objects")
        route_id = route_entry.get("route_id")
        if not isinstance(route_id, str) or not route_id.strip():
            raise ValueError("profile route_id must be nonblank")
        if route_id in seen_route:
            raise ValueError(f"profile contains duplicate route_id {route_id!r}")
        seen_route.add(route_id)

        segments = route_entry.get("segments")
        if not isinstance(segments, list):
            raise ValueError(f"profile route {route_id!r}: 'segments' must be an array")
        for segment_entry in segments:
            segment_id = (
                segment_entry.get("segment_id") if isinstance(segment_entry, dict) else None
            )
            if not isinstance(segment_id, str) or not segment_id.strip():
                raise ValueError(f"profile route {route_id!r}: segment_id must be nonblank")
            if segment_id in seen_segment:
                raise ValueError(f"profile contains duplicate segment_id {segment_id!r}")
            seen_segment.add(segment_id)
            if input_data["segment_to_route"].get(segment_id) != route_id:
                raise ValueError(
                    f"profile segment {segment_id!r} placed under route "
                    f"{route_id!r}, expected "
                    f"{input_data['segment_to_route'].get(segment_id)!r}"
                )
            profile_segments[segment_id] = _validate_profile_segment(
                segment_entry, segment_id
            )

    if seen_route != input_data["route_ids"]:
        missing = sorted(input_data["route_ids"] - seen_route)
        extra = sorted(seen_route - input_data["route_ids"])
        raise ValueError(
            f"profile route set mismatch: missing={missing} extra={extra}"
        )
    if seen_segment != input_data["segment_ids"]:
        missing = sorted(input_data["segment_ids"] - seen_segment)
        extra = sorted(seen_segment - input_data["segment_ids"])
        raise ValueError(
            f"profile segment set mismatch: missing={missing} extra={extra}"
        )
    return profile_segments


def _validate_profile_segment(segment, segment_id: str) -> dict:
    if not isinstance(segment, dict):
        raise ValueError(f"profile segment {segment_id!r} must be an object")

    distance_m = _validate_finite_number(
        segment.get("distance_m"), f"{segment_id}.distance_m"
    )
    if distance_m <= 0.0:
        raise ValueError(f"profile {segment_id}.distance_m must be positive")

    elevation_min_m = _validate_finite_number(
        segment.get("elevation_min_m"), f"{segment_id}.elevation_min_m", allow_none=True
    )
    elevation_max_m = _validate_finite_number(
        segment.get("elevation_max_m"), f"{segment_id}.elevation_max_m", allow_none=True
    )
    if (
        elevation_min_m is not None
        and elevation_max_m is not None
        and elevation_min_m > elevation_max_m
    ):
        raise ValueError(
            f"profile {segment_id}.elevation_min_m exceeds elevation_max_m"
        )

    ascent_m = _validate_finite_number(segment.get("ascent_m"), f"{segment_id}.ascent_m")
    descent_m = _validate_finite_number(
        segment.get("descent_m"), f"{segment_id}.descent_m"
    )
    missing_distance_m = _validate_finite_number(
        segment.get("missing_distance_m"), f"{segment_id}.missing_distance_m"
    )
    if ascent_m < 0.0 or descent_m < 0.0 or missing_distance_m < 0.0:
        raise ValueError(
            f"profile {segment_id}: ascent/descent/missing_distance must be >= 0"
        )

    samples = segment.get("samples")
    if not isinstance(samples, list) or not samples:
        raise ValueError(f"profile {segment_id}: samples must be a nonempty array")

    sample_rows = []
    for index, sample in enumerate(samples):
        if not isinstance(sample, dict):
            raise ValueError(f"profile {segment_id} sample {index}: must be an object")
        sample_distance = _validate_finite_number(
            sample.get("distance_m"), f"{segment_id} sample {index}.distance_m"
        )
        lon = _validate_finite_number(
            sample.get("lon"), f"{segment_id} sample {index}.lon"
        )
        lat = _validate_finite_number(
            sample.get("lat"), f"{segment_id} sample {index}.lat"
        )
        if not LONGITUDE_MIN <= lon <= LONGITUDE_MAX:
            raise ValueError(f"profile {segment_id} sample {index}.lon out of range")
        if not LATITUDE_MIN <= lat <= LATITUDE_MAX:
            raise ValueError(f"profile {segment_id} sample {index}.lat out of range")

        # elevation_m / layer / source_code form one nodata-or-valued tuple: they
        # must all be null (nodata) or all be present (a real DEM sample).
        elevation_m = sample.get("elevation_m")
        layer = sample.get("layer")
        source_code = sample.get("source_code")
        present = [
            name
            for name, value in (
                ("elevation_m", elevation_m),
                ("layer", layer),
                ("source_code", source_code),
            )
            if value is not None
        ]
        if present and len(present) != 3:
            raise ValueError(
                f"profile {segment_id} sample {index}: elevation_m/layer/"
                f"source_code must all be null (nodata) or all be present"
            )
        if elevation_m is not None:
            elevation_m = _validate_finite_number(
                elevation_m, f"{segment_id} sample {index}.elevation_m"
            )
        for value, field in ((layer, "layer"), (source_code, "source_code")):
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int)
            ):
                raise ValueError(
                    f"profile {segment_id} sample {index}.{field} must be "
                    f"an integer or null"
                )
        if layer is not None and layer not in (5, 10):
            raise ValueError(
                f"profile {segment_id} sample {index}.layer must be 5 or 10"
            )
        if source_code is not None and not 1 <= source_code <= 4:
            raise ValueError(
                f"profile {segment_id} sample {index}.source_code must be in 1..4"
            )
        sample_rows.append(
            {
                "distance_m": sample_distance,
                "lon": lon,
                "lat": lat,
                "elevation_m": elevation_m,
                "layer": layer,
                "source_code": source_code,
            }
        )

    # Sample distances must be monotonic from 0 through the segment distance.
    first = sample_rows[0]["distance_m"]
    if not math.isclose(first, 0.0):
        raise ValueError(
            f"profile {segment_id}: first sample distance must be 0, got {first!r}"
        )
    previous = first
    for sample in sample_rows[1:]:
        if sample["distance_m"] < previous:
            raise ValueError(
                f"profile {segment_id}: sample distances are not monotonic"
            )
        previous = sample["distance_m"]
    if not math.isclose(sample_rows[-1]["distance_m"], distance_m):
        raise ValueError(
            f"profile {segment_id}: last sample distance "
            f"{sample_rows[-1]['distance_m']!r} does not match segment "
            f"distance {distance_m!r}"
        )

    return {
        "distance_m": distance_m,
        "elevation_min_m": elevation_min_m,
        "elevation_max_m": elevation_max_m,
        "ascent_m": ascent_m,
        "descent_m": descent_m,
        "missing_distance_m": missing_distance_m,
        "samples": sample_rows,
    }


def run_gsi_dem(gsi_dem_bin: str, elevation_db: str, input_path: str,
                profile_path: str, interval_m: float) -> None:
    """Invoke the existing gsi-dem profile tool; fail closed on nonzero exit."""
    cmd = [
        gsi_dem_bin,
        "profile",
        elevation_db,
        "--input", input_path,
        "--output", profile_path,
        "--interval-m", str(interval_m),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(
            f"gsi-dem profile failed (exit {result.returncode}): {detail}"
        )


def build_sqlite(db_path: str, input_data: dict, profile_segments: dict,
                 metadata_values: dict) -> None:
    """Build content.sqlite deterministically from validated inputs."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(f"PRAGMA page_size = {PAGE_SIZE}")
        conn.execute("PRAGMA journal_mode = DELETE")
        conn.execute("PRAGMA foreign_keys = ON")
        with conn:
            conn.execute(
                "CREATE TABLE metadata ("
                "key   TEXT PRIMARY KEY, "
                "value TEXT NOT NULL"
                ")"
            )
            conn.execute(
                "CREATE TABLE routes ("
                "id           TEXT PRIMARY KEY, "
                "name         TEXT NOT NULL, "
                "payload_json TEXT NOT NULL"
                ")"
            )
            conn.execute(
                "CREATE TABLE route_segments ("
                "id                 TEXT PRIMARY KEY, "
                "route_id           TEXT NOT NULL REFERENCES routes(id), "
                "sequence           INTEGER NOT NULL, "
                "distance_m         REAL NOT NULL, "
                "ascent_m           REAL NOT NULL, "
                "descent_m          REAL NOT NULL, "
                "elevation_min_m    REAL, "
                "elevation_max_m    REAL, "
                "missing_distance_m REAL NOT NULL, "
                "payload_json       TEXT NOT NULL"
                ")"
            )
            conn.execute(
                "CREATE TABLE route_profile_samples ("
                "segment_id  TEXT NOT NULL REFERENCES route_segments(id), "
                "sequence    INTEGER NOT NULL, "
                "distance_m  REAL NOT NULL, "
                "elevation_m REAL, "
                "latitude    REAL NOT NULL, "
                "longitude   REAL NOT NULL, "
                "layer       INTEGER, "
                "source_code INTEGER, "
                "PRIMARY KEY (segment_id, sequence)"
                ")"
            )
            conn.executemany(
                "INSERT INTO metadata (key, value) VALUES (?, ?)",
                list(metadata_values.items()),
            )
            for route_id in sorted(input_data["routes"]):
                route = input_data["routes"][route_id]
                conn.execute(
                    "INSERT INTO routes (id, name, payload_json) VALUES (?, ?, ?)",
                    (route_id, route["name"], encode_payload(route["payload_properties"])),
                )
                for sequence, feature in enumerate(route["segments"], start=1):
                    segment_id = feature["properties"]["segment_id"]
                    prof = profile_segments[segment_id]
                    conn.execute(
                        "INSERT INTO route_segments ("
                        "id, route_id, sequence, distance_m, ascent_m, descent_m, "
                        "elevation_min_m, elevation_max_m, missing_distance_m, "
                        "payload_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            segment_id,
                            route_id,
                            sequence,
                            prof["distance_m"],
                            prof["ascent_m"],
                            prof["descent_m"],
                            prof["elevation_min_m"],
                            prof["elevation_max_m"],
                            prof["missing_distance_m"],
                            encode_payload(feature["properties"]),
                        ),
                    )
                    for sample_sequence, sample in enumerate(prof["samples"]):
                        conn.execute(
                            "INSERT INTO route_profile_samples ("
                            "segment_id, sequence, distance_m, elevation_m, "
                            "latitude, longitude, layer, source_code"
                            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            (
                                segment_id,
                                sample_sequence,
                                sample["distance_m"],
                                sample["elevation_m"],
                                sample["lat"],
                                sample["lon"],
                                sample["layer"],
                                sample["source_code"],
                            ),
                        )
        conn.commit()
        integrity = conn.execute("PRAGMA integrity_check").fetchone()
        if integrity is None or integrity[0] != "ok":
            raise ValueError(
                f"integrity_check failed: {integrity[0] if integrity else 'no result'}"
            )
        fk_issues = conn.execute("PRAGMA foreign_key_check").fetchall()
        if fk_issues:
            raise ValueError(
                f"foreign_key_check failed: {fk_issues!r}"
            )
    finally:
        conn.close()


def build_manifest(metadata, base_url: str | None, pack_dir: str) -> dict:
    """Build the manifest dict with exactly ordered routes/content entries."""
    files = []
    total_size = 0
    for role, path in (("routes", "routes.pmtiles"), ("content", "content.sqlite")):
        full = os.path.join(pack_dir, path)
        size = os.path.getsize(full)
        digest = stream_sha256(full)
        total_size += size
        url = path if base_url is None else urljoin(base_url, path)
        files.append(
            {
                "role": role,
                "path": path,
                "url": url,
                "size": size,
                "sha256": digest,
            }
        )
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "pack_id": metadata["pack_id"],
        "version": metadata["version"],
        "name": metadata["name"],
        "provider": metadata["provider"],
        "attribution": metadata["attribution"],
        "usage": metadata["usage"],
        "minimum_app_version_code": metadata["minimum_app_version_code"],
        "total_size": total_size,
        "files": files,
    }
    return manifest


def _fsync_dir(path: str) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _fsync_file(path: str) -> None:
    with open(path, "rb") as handle:
        os.fsync(handle.fileno())


def atomic_write_json(path: str, data) -> None:
    """Write JSON to path atomically (temp in same dir, then os.replace)."""
    directory = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".manifest-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def build_route_pack(args, metadata) -> str:
    """Build the route pack at args.output_dir, returning its absolute path."""
    output_abs = os.path.abspath(args.output_dir)
    parent = os.path.dirname(output_abs) or "."
    if os.path.exists(output_abs):
        raise FileExistsError(
            f"output directory already exists, refusing to overwrite: {output_abs}"
        )
    os.makedirs(parent, exist_ok=True)

    input_data = read_and_validate_input(args.input)
    _require_nonempty_regular_file(args.routes_pmtiles, "--routes-pmtiles")
    _require_nonempty_regular_file(args.elevation_db, "--elevation-db")

    temp_dir = tempfile.mkdtemp(dir=parent, prefix=".route-pack-", suffix=".tmp")
    try:
        profile_path = os.path.join(temp_dir, ".profile.json")
        run_gsi_dem(
            args.gsi_dem_bin, args.elevation_db, args.input, profile_path,
            args.interval_m,
        )
        with open(profile_path, "r", encoding="utf-8") as handle:
            profile = json.load(handle)
        profile_segments = validate_profile(profile, input_data, args.interval_m)
        os.unlink(profile_path)

        # Copy provider PMTiles into the pack as routes.pmtiles.
        routes_pmtiles = os.path.join(temp_dir, "routes.pmtiles")
        with open(args.routes_pmtiles, "rb") as src, open(routes_pmtiles, "wb") as dst:
            shutil.copyfileobj(src, dst)
        _fsync_file(routes_pmtiles)

        metadata_values = {
            "route_pack_schema_version": str(SCHEMA_VERSION),
            "pack_id": metadata["pack_id"],
            "version": metadata["version"],
            "name": metadata["name"],
            "provider": metadata["provider"],
            "attribution": metadata["attribution"],
            "usage": metadata["usage"],
            "sampling_method": SAMPLING_METHOD,
            "sampling_interval_m": str(args.interval_m),
        }
        content_sqlite = os.path.join(temp_dir, "content.sqlite")
        build_sqlite(content_sqlite, input_data, profile_segments, metadata_values)

        manifest = build_manifest(metadata, args.base_url, temp_dir)
        atomic_write_json(os.path.join(temp_dir, "manifest.json"), manifest)

        os.replace(temp_dir, output_abs)
        _fsync_dir(parent)
    except BaseException:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    return output_abs


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a phase-4 downloadable route pack (manifest + PMTiles "
        "copy + elevation profile SQLite)."
    )
    parser.add_argument("--pack-id", required=True, help="stable pack identifier")
    parser.add_argument("--version", required=True, help="pack version string")
    parser.add_argument("--name", required=True, help="human-readable pack name")
    parser.add_argument("--provider", required=True, help="data provider")
    parser.add_argument("--attribution", required=True, help="required attribution text")
    parser.add_argument("--usage", required=True, help="usage restriction")
    parser.add_argument(
        "--input", required=True, help="canonical route GeoJSON FeatureCollection"
    )
    parser.add_argument(
        "--routes-pmtiles", required=True,
        help="provider-built routes PMTiles to copy into the pack",
    )
    parser.add_argument(
        "--elevation-db", required=True,
        help="build-time GSI elevation SQLite database (not shipped)",
    )
    parser.add_argument("--output-dir", required=True, help="output pack directory")
    parser.add_argument(
        "--base-url", default=None,
        help="http(s) base URL to resolve absolute file URLs (optional)",
    )
    parser.add_argument(
        "--minimum-app-version-code", type=int, default=MINIMUM_APP_VERSION_CODE,
        help=f"minimum Android app version code (default: {MINIMUM_APP_VERSION_CODE})",
    )
    parser.add_argument(
        "--interval-m", type=float, default=DEFAULT_INTERVAL_M,
        help=f"profile sampling interval in meters (default: {DEFAULT_INTERVAL_M})",
    )
    parser.add_argument(
        "--gsi-dem-bin", default=DEFAULT_GSI_DEM_BIN,
        help="path to the gsi-dem binary (default: repo gsi-dem release binary)",
    )
    args = parser.parse_args(argv)

    try:
        metadata = {
            "pack_id": validate_safe_id(args.pack_id, "--pack-id"),
            "version": validate_safe_id(args.version, "--version"),
            "name": validate_nonblank(args.name, "--name"),
            "provider": validate_nonblank(args.provider, "--provider"),
            "attribution": validate_nonblank(args.attribution, "--attribution"),
            "usage": validate_nonblank(args.usage, "--usage"),
            "minimum_app_version_code": validate_minimum_app_version_code(
                args.minimum_app_version_code
            ),
        }
        args.interval_m = validate_interval_m(args.interval_m)
        args.base_url = normalize_base_url(args.base_url)
    except ValueError as exc:
        parser.error(str(exc))

    build_route_pack(args, metadata)
    return 0


if __name__ == "__main__":
    sys.exit(main())