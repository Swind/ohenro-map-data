#!/usr/bin/env python3
"""Build the temple-first offline content SQLite for the app.

Reads the canonical 88-temple list (default datasets/seichijunrei/output/temples.json) and produces a
deterministic, stdlib-only SQLite database (default datasets/seichijunrei/output/content.sqlite) with
exactly one row per canonical temple.

Schema (table `features`):

    id          TEXT PRIMARY KEY NOT NULL   -- canonical temple-NNN
    provider    TEXT NOT NULL               -- "seichijunrei"
    kind        TEXT NOT NULL               -- "temple"
    name        TEXT NOT NULL               -- record["name"]["ja"]
    latitude    REAL NOT NULL               -- record["location"]["latitude"]
    longitude   REAL NOT NULL               -- record["location"]["longitude"]
    payload_json TEXT NOT NULL              -- compact deterministic UTF-8 JSON
                                               of the complete canonical record

The input is strictly validated before anything is written: it must be a JSON
array of exactly 88 records with unique ids, numbers exactly 1..88, each id
matching temple-%03d for its number, a non-blank Japanese name, and finite
latitude/longitude within valid ranges.  Any violation fails before the output
is replaced, leaving any pre-existing output untouched.

The database is built in a temporary file in the destination directory, written
inside a single transaction with an explicit deterministic page_size and a final
integrity_check, closed cleanly, then atomically os.replace'd into place.  There
are no WAL/shm sidecars and no timestamps, so a repeat build is byte-for-byte
deterministic for a given SQLite version.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import sys
import tempfile


DEFAULT_INPUT = os.path.join('datasets/seichijunrei/output/temples.json')
DEFAULT_OUTPUT = os.path.join('datasets/seichijunrei/output/content.sqlite')

PROVIDER = "seichijunrei"
KIND = "temple"

LATITUDE_MIN, LATITUDE_MAX = -90.0, 90.0
LONGITUDE_MIN, LONGITUDE_MAX = -180.0, 180.0

EXPECTED_COUNT = 88

# Fixed, deterministic page size set explicitly before any schema/row writes.
PAGE_SIZE = 4096


def _read_records(input_path: str) -> list:
    """Load and parse the input JSON file as a list of records."""
    with open(input_path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError("input must be a JSON array of temple records")
    return data


def validate_records(data: list) -> list:
    """Strictly validate the input and return the canonical records.

    Raises ValueError on the first violation, describing the problem.  The
    returned list is guaranteed to have exactly 88 records with unique ids and
    numbers exactly 1..88.
    """
    if len(data) != EXPECTED_COUNT:
        raise ValueError(
            f"expected exactly {EXPECTED_COUNT} temple records, got {len(data)}"
        )

    seen_ids = set()
    seen_numbers = set()
    for record in data:
        if not isinstance(record, dict):
            raise ValueError(f"non-object temple record: {record!r}")

        rec_id = record.get("id")
        if not isinstance(rec_id, str) or not rec_id:
            raise ValueError(f"record missing non-blank string id: {record!r}")
        if rec_id in seen_ids:
            raise ValueError(f"duplicate temple id: {rec_id!r}")
        seen_ids.add(rec_id)

        number = record.get("number")
        if isinstance(number, bool) or not isinstance(number, int):
            raise ValueError(
                f"{rec_id}: 'number' must be an integer, got {number!r}"
            )
        if number in seen_numbers:
            raise ValueError(f"{rec_id}: duplicate temple number {number}")
        seen_numbers.add(number)
        if not 1 <= number <= EXPECTED_COUNT:
            raise ValueError(f"{rec_id}: number {number} out of range 1..88")
        expected_id = f"temple-{number:03d}"
        if rec_id != expected_id:
            raise ValueError(
                f"{rec_id}: id does not match number {number} "
                f"(expected {expected_id!r})"
            )

        name = record.get("name")
        if not isinstance(name, dict) or not isinstance(name.get("ja"), str):
            raise ValueError(f"{rec_id}: missing object name with 'ja' string")
        if not name["ja"].strip():
            raise ValueError(f"{rec_id}: blank Japanese name")

        location = record.get("location")
        if not isinstance(location, dict):
            raise ValueError(f"{rec_id}: missing object 'location'")
        lat = location.get("latitude")
        lon = location.get("longitude")
        if not isinstance(lat, (int, float)) or isinstance(lat, bool):
            raise ValueError(f"{rec_id}: latitude must be numeric, got {lat!r}")
        if not isinstance(lon, (int, float)) or isinstance(lon, bool):
            raise ValueError(f"{rec_id}: longitude must be numeric, got {lon!r}")
        if not (math.isfinite(lat) and math.isfinite(lon)):
            raise ValueError(f"{rec_id}: coordinates must be finite")
        if not LATITUDE_MIN <= lat <= LATITUDE_MAX:
            raise ValueError(
                f"{rec_id}: latitude {lat} outside "
                f"[{LATITUDE_MIN}, {LATITUDE_MAX}]"
            )
        if not LONGITUDE_MIN <= lon <= LONGITUDE_MAX:
            raise ValueError(
                f"{rec_id}: longitude {lon} outside "
                f"[{LONGITUDE_MIN}, {LONGITUDE_MAX}]"
            )

    missing_numbers = [
        n for n in range(1, EXPECTED_COUNT + 1) if n not in seen_numbers
    ]
    if missing_numbers:
        raise ValueError(
            f"missing temple numbers: {', '.join(str(n) for n in missing_numbers)}"
        )
    return data


def encode_payload(record: dict) -> str:
    """Serialize a complete canonical record as compact deterministic UTF-8 JSON.

    sort_keys=True keeps key order canonical; comma/colon separators and
    ensure_ascii=False produce compact, human-legible UTF-8.
    """
    return json.dumps(
        record,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def ordered_rows(records: list):
    """Yield (id, provider, kind, name, lat, lon, payload) sorted by id."""
    for record in sorted(records, key=lambda r: r["id"]):
        yield (
            record["id"],
            PROVIDER,
            KIND,
            record["name"]["ja"],
            float(record["location"]["latitude"]),
            float(record["location"]["longitude"]),
            encode_payload(record),
        )


def build_sqlite(records: list, output_path: str) -> None:
    """Build content.sqlite at output_path atomically from validated records.

    Writes to a temp file in the destination directory inside one transaction,
    sets an explicit page_size, runs integrity_check, closes cleanly, then
    os.replace's into place.  Raises on any failure without touching an existing
    output.
    """
    output_abs = os.path.abspath(output_path)
    directory = os.path.dirname(output_abs) or "."
    os.makedirs(directory, exist_ok=True)

    # Validate before touching any output: a bad record must fail here, before
    # any temp DB is created or an existing output could be replaced.
    validate_records(records)

    fd, tmp_path = tempfile.mkstemp(
        dir=directory, prefix=".content-sqlite-", suffix=".tmp"
    )
    os.close(fd)
    try:
        conn = sqlite3.connect(tmp_path)
        try:
            conn.execute(f"PRAGMA page_size = {PAGE_SIZE}")
            # Single-writer batch build in one transaction; avoid WAL/shm
            # sidecars entirely (default rollback journal is deleted on commit).
            conn.execute("PRAGMA journal_mode = DELETE")
            with conn:
                conn.execute(
                    "CREATE TABLE features ("
                    "id TEXT PRIMARY KEY NOT NULL, "
                    "provider TEXT NOT NULL, "
                    "kind TEXT NOT NULL, "
                    "name TEXT NOT NULL, "
                    "latitude REAL NOT NULL, "
                    "longitude REAL NOT NULL, "
                    "payload_json TEXT NOT NULL"
                    ")"
                )
                conn.executemany(
                    "INSERT INTO features "
                    "(id, provider, kind, name, latitude, longitude, payload_json) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    list(ordered_rows(records)),
                )
            conn.commit()
            # integrity_check must run after commit, outside the write txn.
            row = conn.execute("PRAGMA integrity_check").fetchone()
            if row is None or row[0] != "ok":
                raise ValueError(
                    f"integrity_check failed: {row[0] if row else 'no result'}"
                )
        finally:
            conn.close()
        os.replace(tmp_path, output_abs)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the temple-first offline content SQLite database."
    )
    parser.add_argument(
        "--input",
        default=DEFAULT_INPUT,
        help=f"input temples JSON (default: {DEFAULT_INPUT})",
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help=f"output SQLite path (default: {DEFAULT_OUTPUT})",
    )
    args = parser.parse_args(argv)

    records = validate_records(_read_records(args.input))
    build_sqlite(records, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())