"""Focused unit tests for the temple-first content SQLite builder.

Imports the builder via importlib (its filename contains a hyphen) and builds
against tiny temp fixtures, never the real output/temples.json.  Covers valid
build/schema/rows/payload, strict validation failures, atomic preservation on
failure, and repeat-build byte determinism (when stable on this SQLite version).
"""

import hashlib
import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
import unittest

MODULE_PATH = os.path.join(
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"),
    "build-content-sqlite.py",
)

spec = importlib.util.spec_from_file_location("build_content_sqlite", MODULE_PATH)
builder = importlib.util.module_from_spec(spec)
sys.modules["build_content_sqlite"] = builder
spec.loader.exec_module(builder)

EXPECTED_COLUMNS = [
    "id",
    "provider",
    "kind",
    "name",
    "latitude",
    "longitude",
    "payload_json",
]


def make_record(number, **overrides):
    record = {
        "id": f"temple-{number:03d}",
        "number": number,
        "name": {"ja": f"寺{number}", "en": f"Temple {number}"},
        "full_name": {"ja": f"第{number}番 寺{number}", "en": None},
        "location": {
            "latitude": 34.0 + number * 0.01,
            "longitude": 133.0 + number * 0.01,
            "source": "seichijunrei",
        },
        "phone": f"000-0000-{number:04d}",
        "sources": {"seichijunrei": {"spot_id": str(number)}},
    }
    record.update(overrides)
    return record


def full_fixture(count=88):
    return [make_record(n) for n in range(1, count + 1)]


def sha256_file(path):
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


class BuildSqliteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = os.path.join(self.tmp.name, "content.sqlite")

    def build(self, records, out=None):
        builder.build_sqlite(records, out or self.out)
        return out or self.out

    def read_rows(self, out=None):
        conn = sqlite3.connect(out or self.out)
        try:
            return conn.execute(
                "SELECT id, provider, kind, name, latitude, longitude, payload_json "
                "FROM features"
            ).fetchall()
        finally:
            conn.close()


class TestValidBuild(BuildSqliteTest):
    def test_schema_exact(self):
        path = self.build(full_fixture())
        conn = sqlite3.connect(path)
        try:
            cols = conn.execute("PRAGMA table_info(features)").fetchall()
            self.assertEqual([c[1] for c in cols], EXPECTED_COLUMNS)
            for c, pk, notnull in zip(cols, [1, 0, 0, 0, 0, 0, 0], [1, 1, 1, 1, 1, 1, 1]):
                self.assertEqual(c[5], pk)  # pk flag
                self.assertEqual(c[3], notnull)  # notnull flag
            integrity = conn.execute("PRAGMA integrity_check").fetchone()
            self.assertEqual(integrity[0], "ok")
            row = conn.execute("SELECT COUNT(*) FROM features").fetchone()
            self.assertEqual(row[0], 88)
        finally:
            conn.close()

    def test_one_row_per_temple_sorted_by_id(self):
        path = self.build(full_fixture())
        conn = sqlite3.connect(path)
        try:
            ids = [r[0] for r in conn.execute("SELECT id FROM features")]
            self.assertEqual(len(ids), 88)
            self.assertEqual(ids, sorted(ids))
            self.assertEqual(
                ids, [f"temple-{n:03d}" for n in range(1, 89)]
            )
        finally:
            conn.close()

    def test_columns_mapping(self):
        records = full_fixture()
        self.build(records)
        rows = self.read_rows()
        by_id = {r[0]: r for r in rows}
        for record in records:
            rid = record["id"]
            row = by_id[rid]
            self.assertEqual(row[1], "seichijunrei")  # provider
            self.assertEqual(row[2], "temple")  # kind
            self.assertEqual(row[3], record["name"]["ja"])  # name
            self.assertAlmostEqual(row[4], record["location"]["latitude"])
            self.assertAlmostEqual(row[5], record["location"]["longitude"])

    def test_payload_json_is_complete_canonical_deterministic(self):
        records = full_fixture()
        self.build(records)
        rows = self.read_rows()
        by_id = {r[0]: r for r in rows}
        for record in records:
            rid = record["id"]
            payload = by_id[rid][6]
            # Loads back to the exact canonical record.
            self.assertEqual(json.loads(payload), record)
            # Deterministic formatting: sort_keys, comma/colon separators, utf8.
            self.assertEqual(payload, builder.encode_payload(record))
            self.assertNotIn(": ", payload)
            self.assertNotIn(", ", payload)
            payload.encode("utf-8")  # must be UTF-8 encodable

    def test_page_size_is_deterministic(self):
        path = self.build(full_fixture())
        conn = sqlite3.connect(path)
        try:
            page_size = conn.execute("PRAGMA page_size").fetchone()[0]
            self.assertEqual(page_size, builder.PAGE_SIZE)
        finally:
            conn.close()


class TestValidation(BuildSqliteTest):
    def _assert_raises(self, records, fragment):
        with self.assertRaises(ValueError) as ctx:
            builder.validate_records(records)
        self.assertIn(fragment, str(ctx.exception))

    def test_wrong_count(self):
        self._assert_raises(full_fixture(87), "exactly 88")
        self._assert_raises(full_fixture(89), "exactly 88")
        self._assert_raises([], "exactly 88")

    def test_not_a_list(self):
        with self.assertRaises(ValueError):
            builder.validate_records({})

    def test_duplicate_id(self):
        records = full_fixture()
        records[10]["id"] = records[0]["id"]
        self._assert_raises(records, "duplicate temple id")

    def test_duplicate_number(self):
        records = full_fixture()
        records[10]["number"] = records[0]["number"]
        self._assert_raises(records, "duplicate temple number")

    def test_id_mismatch_number(self):
        records = full_fixture()
        records[5]["id"] = "temple-999"
        self._assert_raises(records, "does not match number")

    def test_missing_number(self):
        records = full_fixture(88)
        records[3]["number"] = 100  # out of range, also breaks 1..88 continuity
        self._assert_raises(records, "out of range")

    def test_non_numeric_coordinate(self):
        records = full_fixture()
        records[0]["location"]["latitude"] = "abc"
        self._assert_raises(records, "latitude must be numeric")

    def test_nonfinite_coordinate(self):
        records = full_fixture()
        records[0]["location"]["longitude"] = float("nan")
        self._assert_raises(records, "coordinates must be finite")
        records = full_fixture()
        records[0]["location"]["longitude"] = float("inf")
        self._assert_raises(records, "coordinates must be finite")

    def test_latitude_out_of_range(self):
        records = full_fixture()
        records[0]["location"]["latitude"] = 91.0
        self._assert_raises(records, "latitude 91.0 outside")

    def test_longitude_out_of_range(self):
        records = full_fixture()
        records[0]["location"]["longitude"] = -181.0
        self._assert_raises(records, "longitude -181.0 outside")

    def test_blank_japanese_name(self):
        records = full_fixture()
        records[0]["name"]["ja"] = "   "
        self._assert_raises(records, "blank Japanese name")

    def test_validation_fails_before_replacing_output(self):
        self.build(full_fixture())
        original = sha256_file(self.out)
        bad = full_fixture()
        bad[0]["location"]["latitude"] = float("nan")
        with self.assertRaises(ValueError):
            builder.build_sqlite(bad, self.out)
        # Output untouched by a validation failure.
        self.assertEqual(sha256_file(self.out), original)


class TestAtomicity(BuildSqliteTest):
    def test_failure_preserves_existing_output(self):
        self.build(full_fixture())
        original = sha256_file(self.out)
        # Construct a records list that passes validation but the build throws
        # on a broken payload (a non-JSON-serializable value injected later).
        records = full_fixture()
        records[0]["weird"] = object()
        with self.assertRaises(TypeError):
            builder.build_sqlite(records, self.out)
        self.assertEqual(sha256_file(self.out), original)
        # No stray temp/sidecar files left in the destination directory.
        leftovers = [
            f
            for f in os.listdir(os.path.dirname(self.out))
            if f.startswith(".content-sqlite-")
        ]
        self.assertEqual(leftovers, [])


class TestDeterminism(BuildSqliteTest):
    def test_repeat_build_identical_when_stable(self):
        records = full_fixture()
        out_a = os.path.join(self.tmp.name, "a.sqlite")
        out_b = os.path.join(self.tmp.name, "b.sqlite")
        builder.build_sqlite(records, out_a)
        builder.build_sqlite(records, out_b)
        if builder.PAGE_SIZE == 4096:  # deterministic layout on this version
            self.assertEqual(sha256_file(out_a), sha256_file(out_b))


class TestEncodePayload(unittest.TestCase):
    def test_compact_utf8_deterministic(self):
        record = {"b": "漢字", "a": 1, "nested": {"z": None, "y": [1, 2]}}
        a = builder.encode_payload(record)
        b = builder.encode_payload(record)
        self.assertEqual(a, b)
        self.assertIn("漢字", a)  # ensure_ascii=False
        self.assertNotIn(" ", a)
        a.encode("utf-8")
        self.assertEqual(json.loads(a), record)


if __name__ == "__main__":
    unittest.main()