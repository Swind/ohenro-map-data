"""Offline integrity checks for a min88 archive and its generated datasets."""

from __future__ import annotations

import hashlib
import json
import os

from min88_lodging.crawler import validate_detail_html
from min88_lodging.index_parser import PREFECTURES, canonical_detail_url
from min88_lodging.pipeline import read_jsonl
from henroyado.geocode import is_in_shikoku


def _load(path, errors, label):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        errors.append("%s: %s" % (label, error))
        return None


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _jsonl(path, errors, label):
    try:
        return read_jsonl(path)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        errors.append("%s: %s" % (label, error))
        return None


def _check_ids(label, actual, expected, errors):
    if len(actual) != len(set(actual)):
        errors.append("%s contains duplicate source IDs" % label)
    if actual != expected:
        errors.append("%s source IDs/order do not match index" % label)


def verify(data_dir, output_dir):
    errors = []
    warnings = []
    index = _load(os.path.join(data_dir, "index.json"), errors, "index.json")
    manifest = _load(os.path.join(data_dir, "manifest.json"), errors, "manifest.json")
    if not index or not manifest:
        return {"ok": False, "errors": errors, "warnings": warnings}

    records = index.get("records", [])
    ids = [str(item.get("source_id")) for item in records]
    if len(ids) != len(set(ids)):
        errors.append("index.json contains duplicate source IDs")
    if index.get("record_count") != len(records):
        errors.append("index.json record_count does not match records")
    if [item.get("list_order") for item in records] != sorted(item.get("list_order") for item in records):
        errors.append("index.json records are not in deterministic list order")
    found_prefectures = {item.get("prefecture") for item in records}
    if found_prefectures != set(PREFECTURES):
        errors.append("index.json does not contain all four prefectures")
    for item in records:
        source_id = str(item.get("source_id"))
        if item.get("source_url") != canonical_detail_url(source_id):
            errors.append("post %s: source URL does not match ID" % source_id)
        number = (item.get("temple_context") or {}).get("number")
        if number is not None and not 1 <= number <= 88:
            errors.append("post %s: temple number outside 1..88" % source_id)

    index_page = os.path.join(data_dir, "index", "page.html")
    list_entry = manifest.get("list") or {}
    if not os.path.exists(index_page):
        errors.append("index/page.html missing")
    elif list_entry.get("sha256") != _sha256(index_page):
        errors.append("index/page.html checksum does not match manifest")

    details = manifest.get("details", [])
    summary = manifest.get("detail_summary") or {}
    if not summary:
        errors.append("manifest detail crawl summary missing")
    elif sum(summary.get(key, 0) for key in ("fetched", "skipped", "failed")) != len(records):
        errors.append("detail crawl status counts do not equal index total")
    detail_ids = [str(item.get("source_id")) for item in details]
    _check_ids("manifest details", detail_ids, ids, errors)
    detail_by_id = {str(item.get("source_id")): item for item in details}

    parseable_ids = []
    for source_id in ids:
        page = os.path.join(data_dir, "records", source_id, "page.html")
        if not os.path.exists(page):
            errors.append("post %s: detail page missing" % source_id)
            continue
        try:
            with open(page, "rb") as handle:
                body = handle.read()
            validate_detail_html(body, source_id)
        except (OSError, ValueError) as error:
            errors.append("post %s: invalid detail archive: %s" % (source_id, error))
            continue
        detail = detail_by_id.get(source_id)
        if not detail or detail.get("status") not in ("fetched", "skipped"):
            errors.append("post %s: parseable detail archive has no successful manifest status" % source_id)
            continue
        parseable_ids.append(source_id)
        if detail.get("sha256") != _sha256(page):
            errors.append("post %s: detail checksum does not match manifest" % source_id)
    _check_ids("parseable detail archives", parseable_ids, ids, errors)

    raw = _jsonl(os.path.join(output_dir, "raw.jsonl"), errors, "raw.jsonl")
    v1 = _jsonl(os.path.join(output_dir, "v1.jsonl"), errors, "v1.jsonl")
    if raw is not None:
        raw_ids = [str((item.get("source_context") or {}).get("source_id")) for item in raw]
        _check_ids("Raw", raw_ids, ids, errors)
    if v1 is not None:
        v1_ids = [str((item.get("source") or {}).get("source_id")) for item in v1]
        _check_ids("V1", v1_ids, ids, errors)

    geocoded_path = os.path.join(output_dir, "v1-geocoded.jsonl")
    geocoded = _jsonl(geocoded_path, errors, "v1-geocoded.jsonl") if os.path.exists(geocoded_path) else None
    if geocoded is not None:
        geocoded_ids = [str((item.get("source") or {}).get("source_id")) for item in geocoded]
        _check_ids("V1 geocoded", geocoded_ids, ids, errors)
    for item in geocoded or []:
        location = item.get("location") or {}
        if location.get("map_data_status") != "resolved":
            provenance = ("google_maps_place_id", "google_maps_cid", "google_maps_place_name",
                          "google_maps_place_address", "google_maps_geocode_url")
            if location.get("coordinates") is not None or any(location.get(key) is not None for key in provenance):
                errors.append("post %s: non-resolved location retains coordinates or place provenance" %
                              ((item.get("source") or {}).get("source_id")))
            continue
        coordinates = location.get("coordinates") or {}
        if coordinates.get("source") != "google_maps_embed_place" or not is_in_shikoku(coordinates):
            errors.append("post %s: resolved coordinates lack valid Shikoku place provenance" %
                          ((item.get("source") or {}).get("source_id")))

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "index_records": len(records),
        "detail_parseable": len(parseable_ids),
        "raw_records": len(raw) if raw is not None else 0,
        "v1_records": len(v1) if v1 is not None else 0,
        "geocoded_records": len(geocoded) if geocoded is not None else 0,
    }
