"""Deterministic coverage and warning report for min88 outputs."""

from __future__ import annotations

from collections import Counter, defaultdict
import json
import os

from min88_lodging.crawler.storage import atomic_write_json
from min88_lodging.pipeline import read_jsonl
from min88_lodging.verify import verify


def _read(path, default):
    try:
        return read_jsonl(path)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return default


def _counts(values):
    return dict(sorted(Counter(value for value in values if value is not None).items()))


def generate_report(data_dir, output_dir, output_path=None):
    with open(os.path.join(data_dir, "index.json"), encoding="utf-8") as handle:
        index = json.load(handle)
    try:
        with open(os.path.join(data_dir, "manifest.json"), encoding="utf-8") as handle:
            manifest = json.load(handle)
    except FileNotFoundError:
        manifest = {}
    raw = _read(os.path.join(output_dir, "raw.jsonl"), [])
    v1 = _read(os.path.join(output_dir, "v1.jsonl"), [])
    geocoded_path = os.path.join(output_dir, "v1-geocoded.jsonl")
    mapped = _read(geocoded_path, v1) if os.path.exists(geocoded_path) else v1

    basic_keys = ("address", "tel", "website", "email", "parking", "rooms", "price",
                  "checkin", "checkout", "wifi", "laundry", "payment", "emoney")
    source_coverage = {
        key: sum(bool((item.get("basic_data") or {}).get(key)) for item in raw) for key in basic_keys
    }
    warning_counts = Counter()
    warning_examples = defaultdict(list)
    for item in mapped:
        source_id = str((item.get("source") or {}).get("source_id"))
        for warning in item.get("_warnings") or []:
            code = warning.get("code", "UNKNOWN")
            warning_counts[code] += 1
            if source_id not in warning_examples[code] and len(warning_examples[code]) < 5:
                warning_examples[code].append(source_id)

    current = {str(item["source_id"]): item for item in index.get("records", [])}
    previous = {str(item["source_id"]): item for item in manifest.get("previous_index_records", [])}
    drift = {
        "added_ids": sorted(set(current) - set(previous), key=int) if previous else [],
        "removed_ids": sorted(set(previous) - set(current), key=int) if previous else [],
        "changed_ids": sorted((key for key in set(current) & set(previous) if current[key] != previous[key]), key=int),
    }
    verification = verify(data_dir, output_dir)
    report = {
        "schema_version": 1,
        "records": {
            "index": len(current), "raw": len(raw), "v1": len(v1), "mapped": len(mapped),
            "by_prefecture": _counts((item.get("source_context") or {}).get("prefecture") for item in raw),
            "by_type": _counts(kind for item in v1 for kind in item.get("lodging_types") or []),
            "by_status": _counts(item.get("business_status") or "not_provided" for item in v1),
        },
        "source_field_coverage": source_coverage,
        "normalization_coverage": {
            "room_count": sum((item.get("rooms") or {}).get("room_count") is not None for item in v1),
            "check_in": sum((item.get("check_in") or {}).get("time") is not None for item in v1),
            "check_out": sum((item.get("check_out") or {}).get("time") is not None for item in v1),
            "pricing": sum(bool((item.get("pricing") or {}).get("items")) for item in v1),
            "payment": sum(any(value not in (None, "not_provided") and value != [] and value != {}
                               for key, value in (item.get("payment") or {}).items()
                                if key not in ("raw_text", "electronic_money_raw_text")) for item in v1),
            "facilities_available": sum(any(facility.get("status") == "available" for facility in item.get("facilities") or [])
                                        for item in v1),
        },
        "map_status": _counts((item.get("location") or {}).get("map_data_status") for item in mapped),
        "coordinate_sources": _counts(((item.get("location") or {}).get("coordinates") or {}).get("source") for item in mapped),
        "warnings": {"total": sum(warning_counts.values()), "by_code": dict(sorted(warning_counts.items())),
                     "example_source_ids": dict(sorted(warning_examples.items()))},
        "issues": {
            "missing_detail_pages": sum(not os.path.exists(os.path.join(data_dir, "records", source_id, "page.html")) for source_id in current),
            "name_mismatches": warning_counts["SOURCE_NAME_MISMATCH"],
            "unknown_basic_data_keys": warning_counts["UNKNOWN_BASIC_DATA_KEY"],
            "unknown_taxonomies": warning_counts["UNKNOWN_TAXONOMY"],
        },
        "drift": drift,
        "verify": verification,
    }
    output_path = output_path or os.path.join(output_dir, "report.json")
    atomic_write_json(output_path, report)
    return report
