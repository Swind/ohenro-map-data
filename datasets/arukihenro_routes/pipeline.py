"""Validated source snapshots and one-command Arukihenro normalization."""

import argparse
from collections import Counter
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import tempfile

from . import fetch, normalize, parser
from .storage import atomic_write_json, read_json, resolve_archive
from .temple_range import parse_temple_range

DATASET = Path(__file__).resolve().parent
OUTPUT = "arukihenro-routes.json"


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def archive_hash(root):
    files = {str(p.relative_to(root)): digest(p) for p in sorted(root.rglob("*")) if p.is_file()}
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()


def validate_archive(root):
    manifest = read_json(root / "manifest.json")
    routes = manifest["routes"]
    if manifest.get("schema_version") != 1 or len(routes) < 88:
        raise ValueError("Expected schema v1 archive with at least 88 routes")
    expected = {}
    for region, url in fetch.INDEX_PAGES.items():
        links = parser.parse_index((root / "indexes" / f"{region}.html").read_text(), url)
        if not links:
            raise ValueError(f"No routes in {region} index")
        for link in links:
            expected.setdefault(link, region)
    for url in fetch.EXTRA_ROUTES:
        expected.setdefault(url, "extra")
    if len({r["url"] for r in routes}) != len(routes) or {r["url"] for r in routes} != set(expected):
        raise ValueError("Manifest route URLs differ from index pages")
    for route in routes:
        ident = hashlib.sha256(route["url"].encode()).hexdigest()[:16]
        if route["id"] != ident or route["region"] != expected[route["url"]]:
            raise ValueError("Route ID/region mismatch")
        directory = root / "routes" / ident
        parsed = parser.parse_route((directory / "page.html").read_text(), route["url"])
        if not parsed["title"] or parsed["title"] != route["title"]:
            raise ValueError(f"Missing/mismatched route title: {route['url']}")
        if len(parsed["maps"]) != len(route["maps"]):
            raise ValueError("Route map count mismatch")
        if not parsed["maps"] and parse_temple_range(parsed["title"])[2] not in ([40, 41], [68, 69]):
            raise ValueError(f"Unexpected route without KML: {route['url']}")
        for embedded, item in zip(parsed["maps"], route["maps"]):
            if item.get("error") or any(item.get(k) != v for k, v in embedded.items()):
                raise ValueError(f"Failed/mismatched KML: {route['url']} {item.get('map_id')}")
            local = item.get("local_path", "")
            path = (root / local).resolve()
            if not local or not path.is_relative_to(root.resolve()):
                raise ValueError("KML path outside archive")
            if digest(path) != item["sha256"]:
                raise ValueError(f"KML hash mismatch: {local}")
            fetch._validate_kml(path.read_bytes())
    return manifest


def validate_dataset(data):
    if data.get("schema_version") != 1 or data.get("source") != normalize.SOURCE:
        raise ValueError("Unexpected dataset schema/source")
    if data.get("warnings") or data["summary"]["warning_count"]:
        raise ValueError("Normalization warnings; refusing partial output")
    routes = data["routes"]
    if len(routes) < 88 or len({r["id"] for r in routes}) != len(routes):
        raise ValueError("Incomplete/duplicate route list")
    maps = [m for r in routes for m in r["maps"]]
    lines = [line for m in maps for line in m["lines"]]
    points = [point for m in maps for point in m["points"]]
    if not lines or any(not m["lines"] and not m["points"] for m in maps):
        raise ValueError("Empty KML contents")
    for line in lines:
        if not line["coordinates"]:
            raise ValueError("Empty LineString")
    for coords in [c for line in lines for c in line["coordinates"]] + [p["coordinates"] for p in points]:
        if len(coords) != 2 or not all(math.isfinite(x) for x in coords) or not (-180 <= coords[0] <= 180 and -90 <= coords[1] <= 90):
            raise ValueError("Invalid coordinates")
    counts = {"route_count": len(routes), "map_count": len(maps), "line_count": len(lines),
              "point_count": len(points), "photo_point_count": sum(bool(p["photos"]) for p in points),
              "temple_range_count": sum(bool(r["temple_range"]) for r in routes),
              "category_counts": dict(Counter(p["category"] for p in points)), "warning_count": 0}
    if data["summary"] != counts:
        raise ValueError("Summary accounting mismatch")
    # My Maps contains a one-vertex directions line (65→66); retain the raw
    # evidence and report it instead of inventing a segment or dropping it.
    return {**counts, "degenerate_line_count": sum(len(line["coordinates"]) < 2 for line in lines)}


def refresh(raw, timeout, delay):
    raw.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".download-", dir=raw) as temporary:
        work = Path(temporary)
        candidate = work / "archive"
        print("==> refreshing indexes, route HTML and KML", flush=True)
        fetch.archive(str(candidate), timeout, delay, force=True)
        validate_archive(candidate)
        normalize.normalize_archive(str(candidate), str(work / OUTPUT))
        validate_dataset(read_json(work / OUTPUT))
        sha = archive_hash(candidate)
        destination = raw / "snapshots" / sha
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if archive_hash(destination) != sha:
                raise ValueError("Existing snapshot is corrupt")
        else:
            os.replace(candidate, destination)
        atomic_write_json(str(raw / "current.json"), {"schema_version": 1, "sha256": sha})
        print(f"Source snapshot: {sha}", flush=True)


def build(raw, output, reports, force=False):
    source = resolve_archive(raw)
    validate_archive(source)
    source_hash = archive_hash(source)
    if (raw / "current.json").exists() and read_json(raw / "current.json")["sha256"] != source_hash:
        raise ValueError("Snapshot hash mismatch")
    config = {p.name: digest(p) for p in sorted(DATASET.glob("*.py"))}
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".normalize-", dir=output) as temporary:
        candidate = Path(temporary) / OUTPUT
        normalize.normalize_archive(str(source), str(candidate))
        summary = validate_dataset(read_json(candidate))
        content_hash = digest(candidate)
        target = output / OUTPUT
        previous = {}
        try:
            previous = read_json(reports / "pipeline.json")
        except (OSError, ValueError):
            pass
        unchanged = (not force and isinstance(previous, dict)
                     and previous.get("source_sha256") == config
                     and previous.get("output_sha256") == content_hash
                     and target.is_file() and digest(target) == content_hash)
        if archive_hash(source) != source_hash:
            raise ValueError("Archive changed during build")
        if not unchanged:
            os.replace(candidate, target)
        atomic_write_json(str(reports / "pipeline.json"), {
            "archive_sha256": source_hash, "source_sha256": config,
            "output": OUTPUT, "output_sha256": content_hash,
            "size": target.stat().st_size, "summary": summary})
    print("Unchanged normalized data; skipping publication" if unchanged else f"Published: {target}", flush=True)


def validate(output, reports):
    report = read_json(reports / "pipeline.json")
    path = output / OUTPUT
    if path.stat().st_size != report["size"] or digest(path) != report["output_sha256"]:
        raise ValueError("Output hash/size differs from published report")
    summary = validate_dataset(read_json(path))
    if summary != report["summary"]:
        raise ValueError("Report summary mismatch")
    print(json.dumps(summary, ensure_ascii=False), flush=True)


def main(argv=None):
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("command", choices=("run", "build", "validate"))
    cli.add_argument("--data-dir", type=Path, default=DATASET / "raw")
    cli.add_argument("--output-dir", type=Path, default=DATASET / "output")
    cli.add_argument("--reports-dir", type=Path, default=DATASET / "reports")
    cli.add_argument("--local", action="store_true")
    cli.add_argument("--force", action="store_true", help="force output publication even if unchanged")
    cli.add_argument("--timeout", type=int, default=30)
    cli.add_argument("--delay", type=float, default=0.3)
    args = cli.parse_args(argv)
    if args.local and args.command != "run":
        cli.error("--local applies only to run")
    if args.force and args.command == "validate":
        cli.error("--force applies only to run/build")
    if args.timeout <= 0 or not math.isfinite(args.delay) or args.delay < 0:
        cli.error("timeout must be positive and delay finite/nonnegative")
    raw, output, reports = (p.resolve() for p in (args.data_dir, args.output_dir, args.reports_dir))
    try:
        with (DATASET / ".pipeline.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if args.command == "validate":
                validate(output, reports)
            else:
                if args.command == "run" and not args.local:
                    refresh(raw, args.timeout, args.delay)
                build(raw, output, reports, args.force)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0
