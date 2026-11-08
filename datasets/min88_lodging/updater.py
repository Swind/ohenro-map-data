"""Transactional source refresh and complete min88 lodging publication."""

from collections import Counter
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile

from datasets import _pipeline as common
from .crawler.archive import validate_detail_html, validate_index_html
from .export_map import _feature, export_map
from .geocode import enrich_file, fetch_place
from .html_parser import parse_detail_html
from .index_parser import LIST_URL, canonical_detail_url
from .pipeline import crawl_all, normalize_file, parse_archive, read_jsonl
from .report import generate_report
from .verify import verify

DATASET = Path(__file__).resolve().parent
TILES = "shikoku-min88-lodging.pmtiles"
FILES = ("raw.jsonl", "v1.jsonl", "v1-geocoded.jsonl", "map.geojson", "report.json", TILES)
TILE_METADATA = {"name": "shikoku-min88-lodging", "attribution": "min88 lodging data © min88.jp"}


def archive_files(snapshot):
    """Validate the original list, complete detail accounting and content hashes."""
    snapshot = Path(snapshot)
    index = common.read_json(snapshot / "index.json")
    manifest = common.read_json(snapshot / "manifest.json")
    parsed = validate_index_html((snapshot / "index/page.html").read_bytes())
    records = index["records"]
    if (index.get("list_url") != LIST_URL or index.get("record_count") != len(records)
            or records != parsed["records"] or index.get("occurrences") != parsed["occurrences"]
            or index.get("temple_header_count") != parsed["temple_header_count"]):
        raise ValueError("Archived index differs from its original list page")
    ids = [row["source_id"] for row in records]
    if not ids or len(ids) != len(set(ids)):
        raise ValueError("Empty or duplicate lodging source IDs")
    details = manifest["details"]
    summary = manifest["detail_summary"]
    if ([row["source_id"] for row in details] != ids or summary.get("total") != len(ids)
            or summary.get("failed") != 0
            or sum(summary.get(key, 0) for key in ("fetched", "skipped")) != len(ids)):
        raise ValueError("Incomplete detail crawl; retaining previous source")
    ledger = [manifest["list"], *details]
    names = ["index/page.html", *(f"records/{source_id}/page.html" for source_id in ids)]
    urls = [LIST_URL, *(canonical_detail_url(source_id) for source_id in ids)]
    for name, entry, url in zip(names, ledger, urls):
        path = snapshot / name
        if (entry.get("status") not in ("fetched", "skipped") or entry.get("local_path") != name
                or entry.get("sha256") != common.digest(path)
                or entry.get("url") != url or entry.get("http_status") != 200
                or (entry.get("latest_fetch") or {}).get("status") == "failed"):
            raise ValueError(f"Invalid archive provenance: {name}")
    for context in records:
        source_id = context["source_id"]
        if context["source_url"] != canonical_detail_url(source_id):
            raise ValueError("Detail URL differs from its source ID")
        body = (snapshot / f"records/{source_id}/page.html").read_bytes()
        validate_detail_html(body, source_id)
        raw = parse_detail_html(body.decode("utf-8"), context).to_dict()
        if not raw.get("name"):
            raise ValueError(f"Missing detail name: {source_id}")
    return {name: common.digest(snapshot / name) for name in ("index.json", *names)}


def identity(files):
    return hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def resolve(raw):
    raw = Path(raw)
    selector = raw / "current.json"
    if not selector.exists():
        archive_files(raw)  # Existing flat archives remain usable, never overwritten.
        return raw
    selected = common.read_json(selector)
    key = selected["snapshot"]
    if not isinstance(key, str) or len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
        raise ValueError("Invalid source snapshot selector")
    snapshot = raw / "snapshots" / key
    files = archive_files(snapshot)
    metadata = common.read_json(snapshot / "metadata.json")
    if metadata != {"source_url": LIST_URL, "files": files, "sha256": identity(files)} or key != identity(files):
        raise ValueError("Source snapshot checksum mismatch")
    return snapshot


def fetch(raw, *, timeout=30, delay=0.3, client=None):
    raw = Path(raw)
    raw.mkdir(parents=True, exist_ok=True)
    previous = None
    if (raw / "current.json").exists():
        previous = resolve(raw)
    elif (raw / "index.json").exists():
        try:
            previous = resolve(raw)
        except (OSError, ValueError, KeyError, TypeError):
            # A partial legacy crawl is not a current source; leave its files untouched.
            pass
    with tempfile.TemporaryDirectory(prefix=".min88-fetch-", dir=raw) as directory:
        staged = Path(directory) / "archive"
        result = crawl_all(str(staged), force=True, timeout=timeout, delay=delay, client=client)
        if not result["index"].get("index") or result["details"] is None or result["details"]["failed"]:
            failures = (result.get("details") or {}).get("records", [])
            failed = [row for row in failures if row["status"] == "failed"]
            raise ValueError(f"Incomplete min88 refresh; source not published: {failed or result['index']['archive']}")
        if previous is not None:
            old = common.read_json(previous / "index.json")["records"]
            current = common.read_json(staged / "index.json")["records"]
            if old != current:
                manifest = common.read_json(staged / "manifest.json")
                manifest["previous_index_records"] = old
                common.atomic_json(staged / "manifest.json", manifest)
        files = archive_files(staged)
        key = identity(files)
        destination = raw / "snapshots" / key
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if archive_files(destination) != files:
                raise ValueError("Existing immutable source snapshot is corrupt")
        else:
            common.atomic_json(staged / "metadata.json", {"source_url": LIST_URL, "files": files, "sha256": key})
            os.replace(staged, destination)
        common.atomic_json(raw / "current.json", {"snapshot": key})
    print(f"Complete min88 archive: {destination} ({len(files) - 2} details)", flush=True)
    return destination


def configuration():
    # The existing Google parser is shared with henroyado, so it is also a build input.
    from datasets.henroyado import geocode
    from datasets.henroyado.normalize import map as map_parser
    return {"code": common.code_hash(DATASET), "google_parser": common.digest(geocode.__file__),
            "google_marker_parser": common.digest(map_parser.__file__),
            "layer": "lodging", "min_zoom": 6, "max_zoom": 14, "metadata": TILE_METADATA}


def cache_files(cache):
    cache = Path(cache)
    return {str(path.relative_to(cache)): common.digest(path) for path in sorted(cache.glob("*"))
            if path.is_file() and path.suffix in (".html", ".url", ".json")}


def inputs_for(snapshot, cache):
    return {"source_url": LIST_URL, "source_files": archive_files(snapshot), "geocode_cache": cache_files(cache)}


def cached_place(request_url, cache_dir, timeout=30, force=False):
    def offline(*args, **kwargs):
        raise ValueError("Google place response missing from local cache; run without --local first")
    return fetch_place(request_url, cache_dir, timeout=timeout, opener=offline)


def validate_data(snapshot, output, *, tiles=True):
    result = verify(str(snapshot), str(output))
    if not result["ok"]:
        raise ValueError("; ".join(result["errors"]))
    rows = read_jsonl(output / "v1.jsonl")
    enriched = read_jsonl(output / "v1-geocoded.jsonl")
    expected = []
    statuses = Counter()
    for base, row in zip(rows, enriched):
        if row.get("schema_version") != 1 or (row.get("source") or {}).get("provider") != "min88":
            raise ValueError("Invalid lodging V1 schema/provider")
        if not (row.get("identity") or {}).get("name") or row.get("raw") != base.get("raw"):
            raise ValueError("Missing lodging name or lost source text")
        if {k: v for k, v in row.items() if k not in ("location", "_warnings")} != {
                k: v for k, v in base.items() if k not in ("location", "_warnings")}:
            raise ValueError("Geocode changed non-location lodging fields")
        if row.get("_warnings", [])[:len(base.get("_warnings", []))] != base.get("_warnings", []):
            raise ValueError("Geocode discarded normalizer warnings")
        location = row["location"]
        status = location.get("map_data_status")
        if status not in {"resolved", "source_data_incomplete", "place_ambiguous", "place_not_found", "place_outside_shikoku"}:
            raise ValueError(f"Incomplete Google enrichment: {status}")
        statuses[status] += 1
        if status == "resolved":
            coordinates = location["coordinates"]
            values = [coordinates.get("longitude"), coordinates.get("latitude")]
            if (not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in values)
                    or not (131 < values[0] < 136 and 31.5 < values[1] < 35.5)
                    or not location.get("google_maps_geocode_url")):
                raise ValueError("Invalid resolved coordinate/provenance")
            expected.append(_feature(row))
    collection = common.read_json(output / "map.geojson")
    if collection != {"type": "FeatureCollection", "features": expected} or not expected:
        raise ValueError("Map geometry/accounting differs from resolved V1 records, or is empty")
    report = common.read_json(output / "report.json")
    # Regenerate accounting in a temporary report, without changing the published artifact.
    with tempfile.TemporaryDirectory(prefix=".min88-report-") as directory:
        actual = generate_report(str(snapshot), str(output), str(Path(directory) / "report.json"))
    if report != actual:
        raise ValueError("Coverage/warning report differs from source/output accounting")
    if tiles:
        tile_info = common.validate_pmtiles(output / TILES, {"lodging"}, TILE_METADATA)
        if int(tile_info.get("minzoom", -1)) != 6 or int(tile_info.get("maxzoom", -1)) != 14:
            raise ValueError("Unexpected lodging tile zoom range")
    return {"records": len(rows), "features": len(expected), "map_status": dict(sorted(statuses.items())),
            "warnings": report["warnings"], "by_prefecture": report["records"]["by_prefecture"]}


def build(snapshot, output, reports, cache, *, force=False, local=False, timeout=30, delay=0.3):
    snapshot, output, reports, cache = map(Path, (snapshot, output, reports, cache))
    inputs, settings = inputs_for(snapshot, cache), configuration()
    if not force and common.is_current(output, reports, inputs, settings, FILES):
        print("Inputs, settings and final output hashes unchanged; skipping build", flush=True)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".min88-build-", dir=output.parent) as directory:
        staged = Path(directory)
        parsed = parse_archive(str(snapshot), str(staged / "raw.jsonl"))
        if parsed["skipped"]:
            raise ValueError(f"Incomplete detail parse: {parsed['errors']}")
        # Retrieval times belong to the source ledger, not deterministic derived records.
        normalize_file(str(staged / "raw.jsonl"), str(staged / "v1.jsonl"))
        stats = enrich_file(str(staged / "v1.jsonl"), str(staged / "v1-geocoded.jsonl"), str(cache),
                            timeout=timeout, delay=delay, fetcher=cached_place if local else fetch_place)
        if stats.get("fetch_errors", stats.get("errors", 0)):
            raise ValueError(f"Google fetch failed for {stats.get('fetch_errors', stats.get('errors'))} records; outputs retained")
        export_map(str(staged / "v1-geocoded.jsonl"), str(staged / "map.geojson"))
        generate_report(str(snapshot), str(staged))
        validate_data(snapshot, staged, tiles=False)
        common.build_pmtiles({"lodging": staged / "map.geojson"}, staged / TILES, TILE_METADATA,
                             min_zoom=6, max_zoom=14)
        summary = validate_data(snapshot, staged)
        updated = inputs_for(snapshot, cache)
        if (inputs["source_files"] != updated["source_files"] or settings != configuration()
                or any(updated["geocode_cache"].get(name) != checksum
                       for name, checksum in inputs["geocode_cache"].items())):
            raise ValueError("Source or pipeline changed during build; outputs retained")
        common.publish(staged, output, reports, FILES, updated, settings, summary)


def validate(snapshot, output, reports, cache):
    report = common.verify_report(output, reports, FILES)
    if report["inputs"] != inputs_for(snapshot, cache) or report["build_config"] != configuration():
        raise ValueError("Source, cache or build configuration changed; rebuild required")
    summary = validate_data(snapshot, output)
    if summary != report["summary"]:
        raise ValueError("Pipeline report summary mismatch")
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return summary


def execute(args):
    raw, output, reports = (Path(p).resolve() for p in (args.raw_dir, args.output_dir, args.reports_dir))
    cache = Path(args.cache_dir).resolve() if args.cache_dir else raw / "google-maps"
    with (DATASET / ".pipeline.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.command == "validate":
            validate(resolve(raw), output, reports, cache)
            return 0
        snapshot = fetch(raw, timeout=args.timeout, delay=args.delay) if (
            args.command == "fetch" or args.command == "run" and not args.local) else resolve(raw)
        if args.command != "fetch":
            build(snapshot, output, reports, cache, force=args.force, local=args.local,
                  timeout=args.timeout, delay=args.delay)
    return 0
