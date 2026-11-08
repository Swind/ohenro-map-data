"""Validated Henroyado HTML snapshots and complete lodging publication."""

from collections import Counter
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile

from bs4 import BeautifulSoup

from datasets._pipeline import (atomic_json, build_pmtiles, code_hash, digest,
                                is_current, publish, read_json, validate_pmtiles,
                                verify_report)
from .export_map import _feature, export_map
from .fetcher.fetcher import BASE_URL, DEFAULT_RAW_FILENAME, fetch_bytes
from .geocode import embed_url, enrich_file
from .html_parser import detect_records, extract_all
from .normalize import normalize_inn

DATASET = Path(__file__).resolve().parent
TILES = "shikoku-henroyado-lodging.pmtiles"
OUTPUTS = ("detect.jsonl", "raw.jsonl", "v1.jsonl", "v1-geocoded.jsonl", "map.geojson", TILES)
METADATA = {"name": "Shikoku Henroyado lodging", "attribution": "Henroyado lodging data © henroyado.com"}
PREFECTURES = {"tokushima", "kochi", "ehime", "kagawa"}


def validate_html(content):
    """Require the complete four-prefecture page, not a parseable HTML fragment."""
    html = content.decode("utf-8") if isinstance(content, bytes) else content
    if not re.search(r"</body\s*>\s*</html\s*>\s*$", html, re.IGNORECASE):
        raise ValueError("Henroyado HTML is truncated or has no document ending")
    soup = BeautifulSoup(html, "html.parser")
    groups = soup.select("div.js_prefGroup")
    if len(groups) != 4 or {g.get("data-pref") for g in groups} != PREFECTURES:
        raise ValueError("Expected all four Henroyado prefecture groups")
    temples = {int(m.group(1)) for cap in soup.select("caption")
               for m in [re.search(r"js_temple_(\d+)", " ".join(cap.get("class", [])))] if m}
    if temples != set(range(1, 89)):
        raise ValueError("Expected complete Henroyado temple sections 1–88")
    rows = soup.select("tr.bl_table_row_frontInfo")
    details = soup.select("tr.bl_table_row_detail")
    if not rows or len(details) != len(rows):
        raise ValueError("Listing/detail row accounting mismatch")
    for group in groups:
        if not group.select("tr.bl_table_row_frontInfo"):
            raise ValueError("Empty Henroyado prefecture")
    for row in rows:
        detail = row.find_next_sibling("tr")
        if (row.find_parent("div", class_="js_prefGroup") is None or
                detail is None or "bl_table_row_detail" not in detail.get("class", []) or
                len(row.find_all("td", recursive=False)) != 5 or
                detail.select_one("div.bl_card_info") is None):
            raise ValueError("Incomplete or unaccounted Henroyado listing")
    detected, stats = detect_records(html)
    raw = [inn.to_dict() for inn in extract_all(html)]
    if (len(detected) != len(rows) or len(raw) != len(rows) or stats["issues"] or
            [r["name"] for r in detected] != [r["name"] for r in raw]):
        raise ValueError("Detected/extracted Henroyado listing accounting mismatch")
    return html, detected, raw, stats


def snapshot(raw_dir, content, retrieved_at=None):
    raw_dir = Path(raw_dir)
    _, _, records, stats = validate_html(content)
    identity = hashlib.sha256(content).hexdigest()
    destination = raw_dir / "snapshots" / identity
    if destination.exists():
        if digest(destination / DEFAULT_RAW_FILENAME) != identity:
            raise ValueError("Immutable Henroyado snapshot hash mismatch")
    else:
        (raw_dir / "snapshots").mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".fetch-", dir=raw_dir / "snapshots") as directory:
            stage = Path(directory)
            (stage / DEFAULT_RAW_FILENAME).write_bytes(content)
            atomic_json(stage / "metadata.json", {"source_url": BASE_URL, "sha256": identity,
                        "retrieved_at": retrieved_at, "listings": stats["records"]})
            os.rename(stage, destination)
    atomic_json(raw_dir / "current.json", {"snapshot": identity})
    atomic_json(raw_dir / "geocode-inputs.json", [
        {"name": r["name"], "google_maps_search_url": r["google_maps_search_url"]} for r in records])
    return destination


def resolve(raw_dir):
    raw_dir = Path(raw_dir)
    selector = raw_dir / "current.json"
    if not selector.exists():
        legacy = raw_dir / DEFAULT_RAW_FILENAME
        return snapshot(raw_dir, legacy.read_bytes())
    identity = read_json(selector)["snapshot"]
    if not isinstance(identity, str) or not re.fullmatch(r"[0-9a-f]{64}", identity):
        raise ValueError("Invalid Henroyado snapshot selector")
    selected = raw_dir / "snapshots" / identity
    if digest(selected / DEFAULT_RAW_FILENAME) != identity or read_json(selected / "metadata.json")["sha256"] != identity:
        raise ValueError("Henroyado snapshot hash mismatch")
    validate_html((selected / DEFAULT_RAW_FILENAME).read_bytes())
    return selected


def fetch(raw_dir, timeout=60):
    content = fetch_bytes(timeout=timeout)
    return snapshot(raw_dir, content, datetime.now(timezone.utc).isoformat(timespec="seconds"))


def write_jsonl(path, records):
    with Path(path).open("w", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")


def read_jsonl(path):
    with Path(path).open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def normalized(raw):
    record = normalize_inn(raw, retrieved_at=None)
    record["source"]["source_url"] = BASE_URL
    return record


def inputs_for(selected, cache_dir, records):
    cache = {}
    for record in records:
        url = record.get("google_maps_search_url")
        if not url:
            continue
        identity = json.dumps([embed_url(url), record["name"]], ensure_ascii=False)
        key = hashlib.sha256(identity.encode("utf-8")).hexdigest() + ".html"
        path = Path(cache_dir) / key
        cache[key] = digest(path) if path.exists() else None
    return {"html_sha256": digest(selected / DEFAULT_RAW_FILENAME), "google_embed_responses": cache}


def validate_data(output):
    output = Path(output)
    detected, raw, v1, geocoded = [read_jsonl(output / name) for name in OUTPUTS[:4]]
    if not raw or not (len(detected) == len(raw) == len(v1) == len(geocoded)):
        raise ValueError("Henroyado stage listing accounting mismatch")
    if {r["prefecture"] for r in detected} != PREFECTURES:
        raise ValueError("Missing published prefecture")
    statuses = Counter()
    warnings = Counter()
    expected_features = []
    seen = set()
    duplicates = 0
    for detected_record, raw_record, base, enriched in zip(detected, raw, v1, geocoded):
        if (not detected_record["name"] or detected_record["name"] != raw_record["name"] or
                detected_record["prefecture"] != raw_record["source_context"]["prefecture"] or
                detected_record["temple"] != raw_record["source_context"]["temple"] or
                base != normalized(raw_record)):
            raise ValueError("Detected/raw/normalized listing mismatch")
        if ({k: v for k, v in enriched.items() if k not in ("location", "_warnings")} !=
                {k: v for k, v in base.items() if k not in ("location", "_warnings")} or
                enriched["_warnings"][:len(base["_warnings"])] != base["_warnings"]):
            raise ValueError("Geocode changed non-location source data")
        location = enriched["location"]
        status = location["map_data_status"]
        statuses[status] += 1
        warnings.update(w["code"] for w in enriched["_warnings"])
        for key in ("prefecture", "google_maps_search_url", "google_maps_embed_url"):
            if location.get(key) != base["location"].get(key):
                raise ValueError("Geocode changed source map inputs")
        if status == "resolved":
            coordinate = location["coordinates"]
            lat, lon = coordinate["latitude"], coordinate["longitude"]
            if (not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in (lat, lon)) or
                    not (32 <= lat <= 35 and 131 <= lon <= 135.5) or
                    coordinate["source"] != "google_maps_embed_place" or
                    not re.fullmatch(r"0x[0-9a-f]+:0x[0-9a-f]+", location.get("google_maps_place_id") or "")):
                raise ValueError("Invalid resolved Google place coordinate/identity")
        elif status not in {"source_data_incomplete", "place_not_found", "place_outside_shikoku"}:
            raise ValueError(f"Unfinished geocode status: {status}")
        elif location.get("coordinates") is not None:
            raise ValueError("Unresolved listing has coordinates")
        if (not location.get("google_maps_search_url")) != (status == "source_data_incomplete"):
            raise ValueError("Geocode URL/status accounting mismatch")
        feature = _feature(enriched)
        if feature is not None:
            place_id = feature["properties"]["source_id"]
            if place_id in seen:
                duplicates += 1
            else:
                seen.add(place_id)
                expected_features.append(feature)
    geojson = read_json(output / "map.geojson")
    if not expected_features or geojson != {"type": "FeatureCollection", "features": expected_features}:
        raise ValueError("Map does not exactly account for resolved, deduplicated places")
    return {"listings": len(raw), "by_prefecture": dict(Counter(r["prefecture"] for r in detected)),
            "normalizer_warning_count": sum(len(r["_warnings"]) for r in v1),
            "warning_codes": dict(warnings), "geocode_statuses": dict(statuses),
            "all_listings_resolved": statuses["resolved"] == len(raw),
            "map_features": len(expected_features), "duplicate_places": duplicates,
            "unmapped_listings": len(raw) - statuses["resolved"]}


def validate(output, reports):
    report = verify_report(output, reports, OUTPUTS)
    summary = validate_data(output)
    validate_pmtiles(Path(output) / TILES, {"lodging"}, METADATA)
    if report["summary"] != summary:
        raise ValueError("Published Henroyado summary differs from report")
    print(json.dumps(summary, ensure_ascii=False))
    return summary


def build(selected, raw_dir, output, reports, force=False, timeout=30, delay=0.3):
    source, detected, raw, _ = validate_html((selected / DEFAULT_RAW_FILENAME).read_bytes())
    cache_dir = Path(raw_dir) / "google-maps"
    inputs = inputs_for(selected, cache_dir, raw)
    settings = {"code": code_hash(DATASET), "min_zoom": 6, "max_zoom": 14,
                "layer": "lodging", "metadata": METADATA}
    if not force and is_current(output, reports, inputs, settings, OUTPUTS):
        validate(output, reports)
        print("Inputs, settings and outputs unchanged; skipping build")
        return
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".henroyado-build-", dir=Path(output).parent) as directory:
        staged = Path(directory)
        write_jsonl(staged / "detect.jsonl", detected)
        write_jsonl(staged / "raw.jsonl", raw)
        write_jsonl(staged / "v1.jsonl", [normalized(record) for record in raw])
        stats = enrich_file(staged / "v1.jsonl", staged / "v1-geocoded.jsonl", cache_dir,
                            timeout=timeout, delay=delay)
        if stats["errors"]:
            atomic_json(Path(reports) / "geocode-failure.json", {
                "html_sha256": inputs["html_sha256"], "geocode": stats,
                "statuses": dict(Counter(r["location"]["map_data_status"]
                                         for r in read_jsonl(staged / "v1-geocoded.jsonl"))),
                "published": False})
            raise ValueError(f"Google requests failed for {stats['errors']} listings; published dataset preserved")
        export_map(staged / "v1-geocoded.jsonl", staged / "map.geojson")
        summary = validate_data(staged)
        build_pmtiles({"lodging": staged / "map.geojson"}, staged / TILES, METADATA,
                      min_zoom=6, max_zoom=14)
        if digest(selected / DEFAULT_RAW_FILENAME) != inputs["html_sha256"] or code_hash(DATASET) != settings["code"]:
            raise ValueError("Henroyado source/code changed during build; not published")
        inputs = inputs_for(selected, cache_dir, raw)
        publish(staged, output, reports, OUTPUTS, inputs, settings, summary)
        (Path(reports) / "geocode-failure.json").unlink(missing_ok=True)
        print(json.dumps(summary, ensure_ascii=False))


def execute(args):
    raw, output, reports = (Path(p).resolve() for p in (args.raw_dir, args.output_dir, args.reports_dir))
    with (DATASET / ".pipeline.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.command == "validate":
            validate(output, reports)
        else:
            selected = fetch(raw, args.timeout) if args.command == "fetch" or (args.command == "run" and not args.local) else resolve(raw)
            if args.command != "fetch":
                build(selected, raw, output, reports, args.force, args.timeout, args.delay)
    return 0
