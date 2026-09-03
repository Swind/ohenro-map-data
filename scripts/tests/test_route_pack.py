"""Focused end-to-end tests for the generic route-pack builder.

Executes the real Python CLI (scripts/build-route-pack.py) as a subprocess with
temp fixtures and a tiny fake gsi-dem executable that writes controlled profile
JSON.  Covers the manifest/SQLite schema+rows/FKs/metadata, a multisegment
route, deterministic outputs, invalid/duplicate IDs, profile mismatch and
malformed values, base URL resolution, refusing an existing output (with
preservation), and subprocess failure with temp cleanup.
"""

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILDER = os.path.join(SCRIPTS, "build-route-pack.py")

FAKE_GSI_DEM = """#!/usr/bin/env python3
import json, os, sys

def val(flag):
    args = sys.argv[1:]
    if flag not in args:
        sys.exit(2)
    return args[args.index(flag) + 1]

input_path = val("--input")
output_path = val("--output")
interval = float(val("--interval-m"))

mode = os.environ.get("GSI_DEM_FAKE")
if mode == "fail":
    print("fake gsi-dem: simulated failure", file=sys.stderr)
    sys.exit(1)
if mode:
    # Write a controlled/canned profile verbatim.
    with open(mode, "r", encoding="utf-8") as fh:
        data = fh.read()
    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write(data)
    sys.exit(0)

# Auto-generate a minimal valid profile mirroring gsi-dem's grouping
# (routes sorted by route_id, segments in source feature order).
with open(input_path, "r", encoding="utf-8") as fh:
    fc = json.load(fh)
routes = {}
for feature in fc["features"]:
    rid = feature["properties"]["route_id"]
    sid = feature["properties"]["segment_id"]
    coords = feature["geometry"]["coordinates"]
    routes.setdefault(rid, []).append((sid, coords))
D = 100.0
profile_routes = []
for rid in sorted(routes):
    segments = []
    for sid, coords in routes[rid]:
        p0, p1 = coords[0], coords[1]
        segments.append({
            "segment_id": sid,
            "distance_m": D,
            "elevation_min_m": 100.0,
            "elevation_max_m": 120.0,
            "ascent_m": 20.0,
            "descent_m": 0.0,
            "missing_distance_m": 0.0,
            "samples": [
                {"distance_m": 0.0, "lon": p0[0], "lat": p0[1],
                 "elevation_m": 100.0, "layer": 5, "source_code": 4},
                {"distance_m": D, "lon": p1[0], "lat": p1[1],
                 "elevation_m": 120.0, "layer": 5, "source_code": 4},
            ],
        })
    profile_routes.append({"route_id": rid, "segments": segments})
profile = {
    "schema_version": 1,
    "sampling": {"method": "nearest_cell", "interval_m": interval},
    "routes": profile_routes,
}
with open(output_path, "w", encoding="utf-8") as fh:
    json.dump(profile, fh)
sys.exit(0)
"""


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def make_feature(route_id, segment_id, name, coords, extra=None):
    props = {"route_id": route_id, "segment_id": segment_id, "name": name}
    if extra is not None:
        props["extra"] = extra
    return {
        "type": "Feature",
        "properties": props,
        "geometry": {"type": "LineString", "coordinates": coords},
    }


def single_input():
    return {
        "type": "FeatureCollection",
        "features": [
            make_feature("r1", "r1_s1", "Route One",
                         [[133.0, 34.0], [133.001, 34.0], [133.002, 34.0]], "A"),
            make_feature("r2", "r2_s1", "Route Two",
                         [[133.1, 34.1], [133.101, 34.1]], "B"),
        ],
    }


def multi_input():
    return {
        "type": "FeatureCollection",
        "features": [
            make_feature("r1", "r1_s1", "Route One",
                         [[133.0, 34.0], [133.001, 34.0], [133.002, 34.0]]),
            make_feature("r1", "r1_s2", "Route One",
                         [[133.003, 34.0], [133.004, 34.0], [133.005, 34.0]]),
            make_feature("r2", "r2_s1", "Route Two",
                         [[133.1, 34.1], [133.101, 34.1]]),
        ],
    }


def gen_profile(features, interval=20.0):
    """Mirror the fake gsi-dem's auto-generated valid profile."""
    routes = {}
    for feature in features:
        rid = feature["properties"]["route_id"]
        sid = feature["properties"]["segment_id"]
        coords = feature["geometry"]["coordinates"]
        routes.setdefault(rid, []).append((sid, coords))
    profile_routes = []
    for rid in sorted(routes):
        segments = []
        for sid, coords in routes[rid]:
            p0, p1 = coords[0], coords[1]
            segments.append({
                "segment_id": sid,
                "distance_m": 100.0,
                "elevation_min_m": 100.0,
                "elevation_max_m": 120.0,
                "ascent_m": 20.0,
                "descent_m": 0.0,
                "missing_distance_m": 0.0,
                "samples": [
                    {"distance_m": 0.0, "lon": p0[0], "lat": p0[1],
                     "elevation_m": 100.0, "layer": 5, "source_code": 4},
                    {"distance_m": 100.0, "lon": p1[0], "lat": p1[1],
                     "elevation_m": 120.0, "layer": 5, "source_code": 4},
                ],
            })
        profile_routes.append({"route_id": rid, "segments": segments})
    return {
        "schema_version": 1,
        "sampling": {"method": "nearest_cell", "interval_m": interval},
        "routes": profile_routes,
    }


class RoutePackCLITest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name

        # Input GeoJSON.
        self.input_path = os.path.join(self.root, "input.geojson")
        with open(self.input_path, "w", encoding="utf-8") as fh:
            json.dump(single_input(), fh)

        # Nonempty provider PMTiles + elevation DB fixtures.
        self.pmtiles_path = os.path.join(self.root, "routes.pmtiles")
        with open(self.pmtiles_path, "wb") as fh:
            fh.write(b"not-a-real-pmtiles-provider-owns-build")
        self.elevation_db = os.path.join(self.root, "elevation.sqlite")
        with open(self.elevation_db, "wb") as fh:
            fh.write(b"not-a-real-elevation-db")

        # Fake gsi-dem executable.
        self.fake_bin = os.path.join(self.root, "gsi-dem-fake")
        with open(self.fake_bin, "w", encoding="utf-8") as fh:
            fh.write(FAKE_GSI_DEM)
        os.chmod(self.fake_bin, 0o755)

        self.out_dir = os.path.join(self.root, "pack-out")

    def write_input(self, data):
        with open(self.input_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)

    def write_profile(self, data):
        path = os.path.join(self.root, "canned-profile.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        return path

    def base_args(self):
        return [
            "--pack-id", "mizutani-test",
            "--version", "1.0.0",
            "--name", "Test Pack",
            "--provider", "test-provider",
            "--attribution", "Test attribution",
            "--usage", "personal-use",
            "--input", self.input_path,
            "--routes-pmtiles", self.pmtiles_path,
            "--elevation-db", self.elevation_db,
            "--output-dir", self.out_dir,
            "--gsi-dem-bin", self.fake_bin,
        ]

    def run_cli(self, extra=None, env_extra=None):
        cmd = [sys.executable, BUILDER, *self.base_args()]
        if extra:
            cmd.extend(extra)
        env = dict(os.environ)
        env.pop("GSI_DEM_FAKE", None)
        if env_extra:
            env.update(env_extra)
        return subprocess.run(cmd, capture_output=True, text=True, env=env)

    def build_ok(self, extra=None, env_extra=None):
        proc = self.run_cli(extra, env_extra)
        self.assertEqual(
            proc.returncode, 0,
            f"CLI failed: rc={proc.returncode}\nstdout={proc.stdout}\nstderr={proc.stderr}",
        )
        return proc

    def read_manifest(self):
        with open(os.path.join(self.out_dir, "manifest.json"), "r", encoding="utf-8") as fh:
            return json.load(fh)

    def connect_sqlite(self):
        return sqlite3.connect(os.path.join(self.out_dir, "content.sqlite"))

    def temp_leftovers(self):
        parent = os.path.dirname(self.out_dir)
        return [
            name for name in os.listdir(parent)
            if name.startswith(".route-pack-") and name.endswith(".tmp")
        ]


class TestSuccessfulBuild(RoutePackCLITest):
    def test_manifest_schema_rows(self):
        self.build_ok()
        manifest = self.read_manifest()
        self.assertEqual(manifest["schema_version"], 1)
        self.assertEqual(manifest["pack_id"], "mizutani-test")
        self.assertEqual(manifest["version"], "1.0.0")
        self.assertEqual(manifest["name"], "Test Pack")
        self.assertEqual(manifest["provider"], "test-provider")
        self.assertEqual(manifest["attribution"], "Test attribution")
        self.assertEqual(manifest["usage"], "personal-use")
        self.assertEqual(manifest["minimum_app_version_code"], 4)
        self.assertEqual(len(manifest["files"]), 2)
        roles = [f["role"] for f in manifest["files"]]
        self.assertEqual(roles, ["routes", "content"])
        for f, expected_path in zip(manifest["files"], ["routes.pmtiles", "content.sqlite"]):
            self.assertEqual(f["path"], expected_path)
            self.assertEqual(f["url"], expected_path)
            self.assertGreater(f["size"], 0)
            self.assertRegex(f["sha256"], r"^[0-9a-f]{64}$")
            full = os.path.join(self.out_dir, f["path"])
            with open(full, "rb") as fh:
                self.assertEqual(f["sha256"], sha256_bytes(fh.read()))
        self.assertEqual(
            manifest["total_size"], sum(f["size"] for f in manifest["files"])
        )
        # Only the three documented top-level files exist.
        self.assertEqual(
            sorted(os.listdir(self.out_dir)),
            ["content.sqlite", "manifest.json", "routes.pmtiles"],
        )

    def test_content_sqlite_schema_rows_fk_metadata(self):
        self.build_ok()
        conn = self.connect_sqlite()
        try:
            tables = [
                r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%' ORDER BY name"
                )
            ]
            self.assertEqual(
                tables, ["metadata", "route_profile_samples", "route_segments", "routes"]
            )

            # metadata rows.
            meta = dict(conn.execute("SELECT key, value FROM metadata").fetchall())
            self.assertEqual(meta["route_pack_schema_version"], "1")
            self.assertEqual(meta["pack_id"], "mizutani-test")
            self.assertEqual(meta["version"], "1.0.0")
            self.assertEqual(meta["name"], "Test Pack")
            self.assertEqual(meta["provider"], "test-provider")
            self.assertEqual(meta["attribution"], "Test attribution")
            self.assertEqual(meta["usage"], "personal-use")
            self.assertEqual(meta["sampling_method"], "nearest_cell")
            self.assertEqual(meta["sampling_interval_m"], "20.0")

            # routes sorted by id.
            routes = conn.execute(
                "SELECT id, name, payload_json FROM routes"
            ).fetchall()
            self.assertEqual([r[0] for r in routes], ["r1", "r2"])
            for rid, name, payload in routes:
                props = json.loads(payload)
                self.assertEqual(props["route_id"], rid)
                self.assertEqual(name, {"r1": "Route One", "r2": "Route Two"}[rid])

            # segments + FK to routes.
            segments = conn.execute(
                "SELECT id, route_id, sequence, distance_m, ascent_m, descent_m, "
                "elevation_min_m, elevation_max_m, missing_distance_m, payload_json "
                "FROM route_segments"
            ).fetchall()
            self.assertEqual([s[0] for s in segments], ["r1_s1", "r2_s1"])
            by_id = {s[0]: s for s in segments}
            self.assertEqual(by_id["r1_s1"][1], "r1")  # route_id
            self.assertEqual(by_id["r1_s1"][2], 1)  # sequence
            self.assertEqual(by_id["r1_s1"][3], 100.0)  # distance_m
            self.assertEqual(by_id["r1_s1"][5], 0.0)  # descent
            self.assertEqual(json.loads(by_id["r1_s1"][9])["extra"], "A")

            # samples + FK to segments.
            samples = conn.execute(
                "SELECT segment_id, sequence, distance_m, elevation_m, latitude, "
                "longitude, layer, source_code FROM route_profile_samples "
                "ORDER BY segment_id, sequence"
            ).fetchall()
            self.assertEqual(len(samples), 4)  # 2 segments x 2 samples
            first = samples[0]
            self.assertEqual(first[0], "r1_s1")
            self.assertEqual(first[1], 0)
            self.assertEqual(first[2], 0.0)
            self.assertEqual(first[3], 100.0)  # elevation_m
            self.assertEqual(first[6], 5)  # layer
            self.assertEqual(first[7], 4)  # source_code

            integrity = conn.execute("PRAGMA integrity_check").fetchone()
            self.assertEqual(integrity[0], "ok")
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertEqual(conn.execute("PRAGMA page_size").fetchone()[0], 4096)
        finally:
            conn.close()

    def test_multisegment_route(self):
        self.write_input(multi_input())
        self.build_ok()
        conn = self.connect_sqlite()
        try:
            routes = conn.execute("SELECT id, name FROM routes ORDER BY id").fetchall()
            self.assertEqual(routes, [("r1", "Route One"), ("r2", "Route Two")])
            r1_segs = conn.execute(
                "SELECT id, route_id, sequence FROM route_segments "
                "WHERE route_id='r1' ORDER BY sequence"
            ).fetchall()
            self.assertEqual(r1_segs, [("r1_s1", "r1", 1), ("r1_s2", "r1", 2)])
            count = conn.execute(
                "SELECT COUNT(*) FROM route_profile_samples WHERE segment_id='r1_s2'"
            ).fetchone()[0]
            self.assertEqual(count, 2)
        finally:
            conn.close()

    def test_base_url(self):
        self.build_ok(extra=["--base-url", "https://example.com/packs/"])
        manifest = self.read_manifest()
        urls = [f["url"] for f in manifest["files"]]
        self.assertEqual(
            urls, ["https://example.com/packs/routes.pmtiles",
                   "https://example.com/packs/content.sqlite"]
        )

    def test_deterministic_outputs(self):
        self.build_ok()
        out_a = self.out_dir
        manifest_a = self.read_manifest()

        out_b = os.path.join(self.root, "pack-out-b")
        self.build_ok(extra=["--output-dir", out_b])
        with open(os.path.join(out_b, "manifest.json"), "rb") as fh:
            manifest_b_bytes = fh.read()
        with open(os.path.join(out_a, "manifest.json"), "rb") as fh:
            manifest_a_bytes = fh.read()
        self.assertEqual(manifest_a_bytes, manifest_b_bytes)

        def sh(path):
            with open(path, "rb") as fh:
                return sha256_bytes(fh.read())

        self.assertEqual(
            sh(os.path.join(out_a, "content.sqlite")),
            sh(os.path.join(out_b, "content.sqlite")),
        )
        self.assertEqual(
            sh(os.path.join(out_a, "routes.pmtiles")),
            sh(os.path.join(out_b, "routes.pmtiles")),
        )
        self.assertEqual(manifest_a, self.read_manifest())

    def test_refuses_existing_output_and_preserves(self):
        self.build_ok()
        with open(os.path.join(self.out_dir, "content.sqlite"), "rb") as fh:
            before = sha256_bytes(fh.read())
        # Point --input at broken content but same output dir: must refuse.
        self.write_input({})  # invalid input
        proc = self.run_cli()
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("already exists", proc.stderr)
        with open(os.path.join(self.out_dir, "content.sqlite"), "rb") as fh:
            self.assertEqual(before, sha256_bytes(fh.read()))
        self.assertEqual(self.temp_leftovers(), [])


class TestValidationFailures(RoutePackCLITest):
    def _assert_fails(self, fragment, extra=None, env_extra=None, input_data=None):
        if input_data is not None:
            self.write_input(input_data)
        proc = self.run_cli(extra, env_extra)
        self.assertNotEqual(proc.returncode, 0, "expected CLI failure")
        combined = proc.stderr + proc.stdout
        self.assertIn(fragment, combined)
        self.assertFalse(os.path.exists(self.out_dir))
        self.assertEqual(self.temp_leftovers(), [])

    def test_duplicate_segment_id(self):
        bad = single_input()
        bad["features"][1]["properties"]["segment_id"] = "r1_s1"
        self._assert_fails("duplicate segment_id", input_data=bad)

    def test_inconsistent_route_name(self):
        bad = multi_input()
        bad["features"][1]["properties"]["name"] = "Different Name"
        self._assert_fails("inconsistent name", input_data=bad)

    def test_bad_version(self):
        self._assert_fails("--version", extra=["--version", "not safe!"])
        self._assert_fails("--version", extra=["--version", ""])

    def test_bad_pack_id(self):
        self._assert_fails("--pack-id", extra=["--pack-id", "a/b"])

    def test_blank_metadata(self):
        self._assert_fails("--name", extra=["--name", "   "])
        self._assert_fails("--usage", extra=["--usage", ""])

    def test_minimum_app_version_below_4(self):
        self._assert_fails(
            ">= 4", extra=["--minimum-app-version-code", "3"]
        )

    def test_bad_interval(self):
        self._assert_fails("interval", extra=["--interval-m", "0"])
        self._assert_fails("interval", extra=["--interval-m", "-5"])
        self._assert_fails("interval", extra=["--interval-m", "nan"])

    def test_nonempty_files(self):
        with open(self.pmtiles_path, "wb") as fh:
            fh.write(b"")
        self._assert_fails("--routes-pmtiles")
        with open(self.pmtiles_path, "wb") as fh:
            fh.write(b"x")
        with open(self.elevation_db, "wb") as fh:
            fh.write(b"")
        self._assert_fails("--elevation-db")

    def test_bad_geojson_coordinates(self):
        bad = single_input()
        bad["features"][0]["geometry"]["coordinates"][1] = [float("nan"), 34.0]
        self._assert_fails("finite", input_data=bad)

    def test_single_point_line(self):
        bad = single_input()
        bad["features"][0]["geometry"]["coordinates"] = [[133.0, 34.0]]
        self._assert_fails(">= 2", input_data=bad)


class TestProfileValidation(RoutePackCLITest):
    def _run_with_profile(self, profile):
        path = self.write_profile(profile)
        return self.run_cli(env_extra={"GSI_DEM_FAKE": path})

    def test_valid_canned_profile_succeeds(self):
        profile = gen_profile(single_input()["features"])
        proc = self.run_cli(env_extra={"GSI_DEM_FAKE": self.write_profile(profile)})
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_schema_version_mismatch(self):
        profile = gen_profile(single_input()["features"])
        profile["schema_version"] = 2
        proc = self._run_with_profile(profile)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("schema_version", proc.stderr)

    def test_sampling_method_mismatch(self):
        profile = gen_profile(single_input()["features"])
        profile["sampling"]["method"] = "resample"
        proc = self._run_with_profile(profile)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("sampling.method", proc.stderr)

    def test_sampling_interval_mismatch(self):
        profile = gen_profile(single_input()["features"], interval=25.0)
        proc = self._run_with_profile(profile)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("interval", proc.stderr)

    def test_missing_segment(self):
        profile = gen_profile(single_input()["features"])
        profile["routes"][0]["segments"] = profile["routes"][0]["segments"][:0]
        proc = self._run_with_profile(profile)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("segment set mismatch", proc.stderr)

    def test_duplicate_segment_in_profile(self):
        profile = gen_profile(single_input()["features"])
        profile["routes"][0]["segments"].append(profile["routes"][0]["segments"][0])
        proc = self._run_with_profile(profile)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("duplicate segment_id", proc.stderr)

    def test_segment_under_wrong_route(self):
        profile = gen_profile(single_input()["features"])
        profile["routes"][0]["segments"][0]["segment_id"] = "r2_s1"
        proc = self._run_with_profile(profile)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("placed under route", proc.stderr)

    def test_negative_distance(self):
        profile = gen_profile(single_input()["features"])
        profile["routes"][0]["segments"][0]["distance_m"] = -5.0
        proc = self._run_with_profile(profile)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("distance_m must be positive", proc.stderr)

    def test_nonfinite_elevation(self):
        profile = gen_profile(single_input()["features"])
        profile["routes"][0]["segments"][0]["elevation_max_m"] = float("nan")
        proc = self._run_with_profile(profile)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("finite", proc.stderr)

    def test_empty_samples(self):
        profile = gen_profile(single_input()["features"])
        profile["routes"][0]["segments"][0]["samples"] = []
        proc = self._run_with_profile(profile)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("nonempty array", proc.stderr)

    def test_nonmonotonic_samples(self):
        profile = gen_profile(single_input()["features"])
        profile["routes"][0]["segments"][0]["samples"] = [
            {"distance_m": 50.0, "lon": 133.0, "lat": 34.0,
             "elevation_m": 100.0, "layer": 5, "source_code": 4},
            {"distance_m": 100.0, "lon": 133.1, "lat": 34.0,
             "elevation_m": 120.0, "layer": 5, "source_code": 4},
        ]
        proc = self._run_with_profile(profile)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("first sample distance must be 0", proc.stderr)

    def test_last_sample_not_matching_distance(self):
        profile = gen_profile(single_input()["features"])
        profile["routes"][0]["segments"][0]["distance_m"] = 200.0
        proc = self._run_with_profile(profile)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("last sample distance", proc.stderr)

    def test_bad_sample_coordinate(self):
        profile = gen_profile(single_input()["features"])
        profile["routes"][0]["segments"][0]["samples"][1]["lat"] = 999.0
        proc = self._run_with_profile(profile)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("out of range", proc.stderr)

    def test_partial_nodata_tuple(self):
        # elevation present but layer/source_code null -> nodata-or-valued tuple.
        profile = gen_profile(single_input()["features"])
        profile["routes"][0]["segments"][0]["samples"][0]["layer"] = None
        proc = self._run_with_profile(profile)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("all be null (nodata) or all be present", proc.stderr)

    def test_partial_nodata_tuple_missing_elevation(self):
        # layer/source_code present but elevation null -> tuple mismatch.
        profile = gen_profile(single_input()["features"])
        profile["routes"][0]["segments"][0]["samples"][0]["elevation_m"] = None
        proc = self._run_with_profile(profile)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("all be null (nodata) or all be present", proc.stderr)

    def test_layer_not_5_or_10(self):
        profile = gen_profile(single_input()["features"])
        profile["routes"][0]["segments"][0]["samples"][0]["layer"] = 4
        proc = self._run_with_profile(profile)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("layer must be 5 or 10", proc.stderr)

    def test_source_code_out_of_range(self):
        profile = gen_profile(single_input()["features"])
        profile["routes"][0]["segments"][0]["samples"][0]["source_code"] = 0
        proc = self._run_with_profile(profile)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("source_code must be in 1..4", proc.stderr)


class TestSubprocessFailure(RoutePackCLITest):
    def test_fail_closed_and_cleanup(self):
        proc = self.run_cli(env_extra={"GSI_DEM_FAKE": "fail"})
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("gsi-dem profile failed", proc.stderr)
        self.assertFalse(os.path.exists(self.out_dir))
        self.assertEqual(self.temp_leftovers(), [])


if __name__ == "__main__":
    unittest.main()