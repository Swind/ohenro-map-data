"""End-to-end file orchestration for the min88 worker modules."""

from __future__ import annotations

import hashlib
import json
import os

from min88_lodging.crawler import crawl_details, crawl_index
from min88_lodging.crawler.storage import atomic_write_bytes, atomic_write_json
from min88_lodging.html_parser import parse_detail_html
from min88_lodging.normalize import normalize_lodging

PARSER_VERSION = "min88-phase1-v1"


def _load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return default


def read_jsonl(path):
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_jsonl(path, records):
    data = b"".join(
        (json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        for record in records
    )
    atomic_write_bytes(path, data)


def _manifest_path(data_dir):
    return os.path.join(data_dir, "manifest.json")


def _archive_sha256(data_dir, archive):
    path = os.path.join(data_dir, archive.get("local_path", ""))
    if not archive.get("local_path") or not os.path.isfile(path):
        return archive
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    archive["sha256"] = digest.hexdigest()
    return archive


def _merge_archive(data_dir, current, previous):
    if current["status"] == "failed" and previous and previous.get("status") != "failed":
        retained = dict(previous)
        retained["latest_fetch"] = current
        return _archive_sha256(data_dir, retained)
    merged = dict(current)
    if current["status"] == "skipped":
        for key in ("retrieved_at", "http_status", "etag", "last_modified"):
            merged[key] = previous.get(key) or current.get(key)
    return _archive_sha256(data_dir, merged)


def _write_manifest(data_dir, *, index_result=None, detail_result=None):
    path = _manifest_path(data_dir)
    manifest = _load_json(path, {}) or {}
    manifest.setdefault("schema_version", 1)
    manifest["parser_version"] = PARSER_VERSION

    if index_result is not None:
        old_archive = manifest.get("list", {})
        manifest["list"] = _merge_archive(data_dir, index_result["archive"], old_archive)
        index = index_result.get("index")
        if index:
            old_records = manifest.get("index", {}).get("records", [])
            if old_records and old_records != index["records"]:
                manifest["previous_index_records"] = old_records
            prefectures = {}
            closure_markers = 0
            temple_numbers = set()
            for record in index["records"]:
                prefecture = record.get("prefecture")
                prefectures[prefecture] = prefectures.get(prefecture, 0) + 1
                closure_markers += bool(record.get("closure_marker"))
                temple = record.get("temple_context") or {}
                if temple.get("number") is not None:
                    temple_numbers.add(temple["number"])
            manifest["index"] = {
                "record_count": index["record_count"],
                "occurrence_count": index["occurrence_count"],
                "temple_header_count": index["temple_header_count"],
                "prefectures": prefectures,
                "temple_numbers": sorted(temple_numbers),
                "closure_marker_count": closure_markers,
                "records": index["records"],
            }

    if detail_result is not None:
        previous = {item["source_id"]: item for item in manifest.get("details", [])}
        details = []
        for item in detail_result["records"]:
            old = previous.get(item["source_id"], {})
            details.append(_merge_archive(data_dir, item, old))
        manifest["details"] = details
        manifest["detail_summary"] = {
            key: detail_result[key] for key in ("total", "fetched", "skipped", "failed")
        }

    atomic_write_json(path, manifest)
    return manifest


def crawl_index_archive(data_dir, **kwargs):
    result = crawl_index(data_dir, **kwargs)
    _write_manifest(data_dir, index_result=result)
    return result


def crawl_detail_archive(data_dir, **kwargs):
    result = crawl_details(data_dir, **kwargs)
    _write_manifest(data_dir, detail_result=result)
    return result


def crawl_all(data_dir, **kwargs):
    index_result = crawl_index_archive(data_dir, **kwargs)
    if not index_result.get("index"):
        return {"index": index_result, "details": None}
    detail_result = crawl_detail_archive(data_dir, **kwargs)
    return {"index": index_result, "details": detail_result}


def parse_archive(data_dir, output_path):
    index = _load_json(os.path.join(data_dir, "index.json"))
    if not index:
        raise FileNotFoundError("index.json missing; run crawl-index first")
    records = []
    errors = []
    for context in index.get("records", []):
        source_id = str(context["source_id"])
        page_path = os.path.join(data_dir, "records", source_id, "page.html")
        try:
            with open(page_path, encoding="utf-8") as handle:
                raw = parse_detail_html(handle.read(), context).to_dict()
            records.append(raw)
        except Exception as error:
            errors.append({"source_id": source_id, "error": str(error)})
    write_jsonl(output_path, records)
    return {"records": len(records), "skipped": len(errors), "errors": errors}


def normalize_file(input_path, output_path, data_dir=None):
    retrieved = {}
    if data_dir:
        manifest = _load_json(_manifest_path(data_dir), {}) or {}
        retrieved = {item["source_id"]: item.get("retrieved_at") for item in manifest.get("details", [])}
    normalized = []
    for raw in read_jsonl(input_path):
        source_id = str((raw.get("source_context") or {}).get("source_id"))
        normalized.append(normalize_lodging(raw, retrieved_at=retrieved.get(source_id)))
    write_jsonl(output_path, normalized)
    return {
        "records": len(normalized),
        "records_with_warnings": sum(bool(item.get("_warnings")) for item in normalized),
        "warnings": sum(len(item.get("_warnings") or []) for item in normalized),
    }
