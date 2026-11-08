"""Refresh an immutable official archive and publish all validated map products."""

import argparse
import fcntl
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from datasets import _pipeline as common
from . import config
from .crawler.assets import download_assets
from .crawler.detail import crawl_details
from .crawler.index import crawl_index
from .crawler.kml import download_kml
from .crawler.manifest import build_manifest
from .export_map import export_map
from .http import HttpClient
from .normalize import normalize_archive
from .verify import verify

DATASET = Path(__file__).resolve().parent
STEM = "shikoku-nature-trail"
FILES = (f"{STEM}.json", f"{STEM}.geojson", f"{STEM}-pois.geojson",
         f"{STEM}-report.json", f"{STEM}.pmtiles")
LAYERS = {"shikoku_nature_trail": FILES[1], "shikoku_nature_trail_pois": FILES[2]}
METADATA = {"attribution": "Shikoku Nature Trail (四国自然歩道) © shikoku-nature-trail.com"}


def require_archive(snapshot):
    result = verify(snapshot)
    if not result["ok"]:
        raise ValueError("Incomplete source archive: " + "; ".join(result["errors"]))
    return result


def source_inputs(snapshot):
    """Ignore retrieval timestamps while retaining every source byte and URL."""
    index = common.read_json(snapshot / "course-index.json")
    files = {f"indexes/{pref.id}.html": common.digest(snapshot / "indexes" / (pref.id + ".html"))
             for pref in config.PREFECTURES}
    for course in index["courses"]:
        directory = snapshot / "courses" / str(course["source_post_id"])
        paths = [directory / "page.html", directory / "map/map.kml"]
        assets = common.read_json(directory / "assets.json")["assets"]
        paths.extend(directory / asset["local_file"] for asset in assets)
        files.update({str(path.relative_to(snapshot)): common.digest(path) for path in paths})
    return {"source": "https://shikoku-nature-trail.com/", "courses": index["courses"], "files": files}


def identity(inputs):
    return hashlib.sha256(json.dumps(inputs, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def resolve(raw):
    selector = raw / "current.json"
    if selector.exists():
        selection = common.read_json(selector)
        snapshot = (raw / selection["snapshot"]).resolve()
        if not snapshot.is_relative_to((raw / "snapshots").resolve()):
            raise ValueError("Invalid current archive selector")
        metadata = common.read_json(snapshot / "snapshot.json")
        if metadata["files"] != common.output_hashes(snapshot, metadata["files"]):
            raise ValueError("Immutable archive file checksum mismatch")
        require_archive(snapshot)
        if identity(source_inputs(snapshot)) != metadata["identity"] or selection["identity"] != metadata["identity"]:
            raise ValueError("Immutable archive identity mismatch")
        return snapshot
    # Existing flat archives remain valid inputs for an offline cutover.
    require_archive(raw)
    return raw


def reuse_images(previous, staged):
    """Only reuse verified images when their exact owning detail page is unchanged."""
    for course in common.read_json(staged / "course-index.json")["courses"]:
        relative = Path("courses") / str(course["source_post_id"])
        old, new = previous / relative, staged / relative
        if not (old / "page.html").exists() or common.digest(old / "page.html") != common.digest(new / "page.html"):
            continue
        prior = common.read_json(old / "assets.json")["assets"]
        manifest = common.read_json(new / "assets.json")
        cached = {asset["source_url"]: asset for asset in prior}
        for index, asset in enumerate(manifest["assets"]):
            saved = cached.get(asset["source_url"])
            if saved and saved["status"] == "downloaded":
                source = old / saved["local_file"]
                if source.is_file() and common.digest(source) == saved["sha256"]:
                    destination = new / saved["local_file"]
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, destination)
                    manifest["assets"][index] = dict(saved)
        common.atomic_json(new / "assets.json", manifest)


def fetch(raw, client):
    raw.mkdir(parents=True, exist_ok=True)
    previous = None
    if (raw / "current.json").exists() or (raw / "course-index.json").exists():
        previous = resolve(raw)
    with tempfile.TemporaryDirectory(prefix=".fetch-", dir=raw) as directory:
        staged = Path(directory)
        result = crawl_index(client, str(staged), force=True)
        if result["failures"] or len(result["indexes"]) != len(config.PREFECTURES):
            raise ValueError("Course list refresh failed: %r" % result["failures"])
        _, failures = crawl_details(client, str(staged), force=True)
        if failures:
            raise ValueError("Course detail refresh failed: %r" % failures)
        if previous:
            reuse_images(previous, staged)
        _, failures = download_assets(client, str(staged))
        if failures:
            raise ValueError("Image refresh failed: %r" % failures)
        _, failures = download_kml(client, str(staged), force=True)
        if failures:
            raise ValueError("KML refresh failed: %r" % failures)
        build_manifest(str(staged))
        summary = require_archive(staged)
        inputs = source_inputs(staged)
        checksum = identity(inputs)
        names = sorted(str(p.relative_to(staged)) for p in staged.rglob("*") if p.is_file())
        common.atomic_json(staged / "snapshot.json", {"identity": checksum, "summary": summary,
                                                      "files": common.output_hashes(staged, names)})
        target = raw / "snapshots" / checksum
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            # Validate an existing immutable snapshot before selecting it again.
            metadata = common.read_json(target / "snapshot.json")
            if (metadata["identity"] != checksum or
                    metadata["files"] != common.output_hashes(target, metadata["files"])):
                raise ValueError("Existing immutable source snapshot is corrupt")
            require_archive(target)
        else:
            os.replace(staged, target)
        common.atomic_json(raw / "current.json", {"snapshot": str(target.relative_to(raw)), "identity": checksum})
    print("Source archive: %s" % target, flush=True)
    return target


def validate_data(output, *, tiles=True):
    dataset = common.read_json(output / FILES[0])
    if dataset.get("schema_version") != 1 or dataset.get("source") != "https://shikoku-nature-trail.com/":
        raise ValueError("Invalid normalized source/schema")
    if dataset["warnings"] or dataset["summary"]["warning_count"]:
        raise ValueError("Normalized source contains missing-data warnings")
    courses = dataset["courses"]
    summary = {"course_count": len(courses),
               "photo_point_count": sum(c["photo_point"] is not None for c in courses),
               "tourism_spot_count": sum(len(c["tourism_spots"]) for c in courses),
               "placemark_count": sum(len(c["kml"]["placemarks"]) for c in courses), "warning_count": 0}
    if not courses or summary != dataset["summary"]:
        raise ValueError("Normalized source accounting mismatch")
    for course in courses:
        for image in course["images"] + [spot["image"] for spot in course["tourism_spots"] if spot["image"]]:
            if not image["source_url"] or not image["local_path"]:
                raise ValueError("Normalized image missing authentic archived asset")
    # Reuse the exporter as the single schema/geometry/accounting implementation.
    with tempfile.TemporaryDirectory(prefix=".validate-") as directory:
        regenerated = Path(directory)
        totals = export_map(output / FILES[0], regenerated / FILES[1], regenerated / FILES[2], regenerated / FILES[3])
        for name in FILES[1:4]:
            if common.read_json(regenerated / name) != common.read_json(output / name):
                raise ValueError("Published map differs from normalized source: %s" % name)
    if (totals["courses"] != summary["course_count"] or totals["route_ids"] != totals["courses"]
            or totals["route_segments"] < totals["route_ids"]
            or totals["route_coordinate_points"] < totals["route_segments"] * 2
            or totals["photo_points"] != summary["photo_point_count"]
            or totals["linked_tourism_spots"] + totals["unmatched_tourism_spots"] != summary["tourism_spot_count"]):
        raise ValueError("Map export/source accounting mismatch")
    if tiles:
        common.validate_pmtiles(output / FILES[4], LAYERS, METADATA)
    return {"normalized": summary, "map": totals}


def validate(output, reports):
    report = common.verify_report(output, reports, FILES)
    summary = validate_data(output)
    if report["summary"] != summary:
        raise ValueError("Published summary mismatch")
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return summary


def build(snapshot, output, reports, force=False, image=common.IMAGE):
    require_archive(snapshot)
    inputs = source_inputs(snapshot)
    settings = {"code": common.code_hash(DATASET), "image": image, "minimum_zoom": 0, "maximum_zoom": 14}
    if not force and common.is_current(output, reports, inputs, settings, FILES):
        validate(output, reports)
        print("Inputs, settings and outputs unchanged; skipping build", flush=True)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".nature-trail-build-", dir=output.parent) as directory:
        staged = Path(directory)
        normalize_archive(str(snapshot), str(staged / FILES[0]))
        export_map(staged / FILES[0], staged / FILES[1], staged / FILES[2], staged / FILES[3])
        summary = validate_data(staged, tiles=False)
        common.build_pmtiles({layer: staged / name for layer, name in LAYERS.items()},
                             staged / FILES[4], METADATA, image=image)
        common.validate_pmtiles(staged / FILES[4], LAYERS, METADATA)
        if source_inputs(snapshot) != inputs or common.code_hash(DATASET) != settings["code"]:
            raise ValueError("Source or pipeline changed during build; not published")
        common.publish(staged, output, reports, FILES, inputs, settings, summary)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", default="run", choices=("run", "fetch", "build", "validate"))
    parser.add_argument("--local", action="store_true", help="run: use the validated local archive, without HTTP")
    parser.add_argument("--force", action="store_true", help="run/build: rebuild unchanged outputs")
    parser.add_argument("--raw-dir", "--data-dir", type=Path, default=DATASET / "raw")
    parser.add_argument("--output-dir", type=Path, default=DATASET / "output")
    parser.add_argument("--reports-dir", type=Path, default=DATASET / "reports")
    parser.add_argument("--timeout", type=int, default=config.DEFAULT_TIMEOUT)
    parser.add_argument("--concurrency", type=int, default=config.DEFAULT_CONCURRENCY)
    parser.add_argument("--delay", type=float, default=config.DEFAULT_DELAY)
    parser.add_argument("--image", default=os.environ.get("TRAIL_IMAGE", common.IMAGE))
    parser.add_argument("--log-level", choices=("DEBUG", "INFO", "WARNING", "ERROR"), default="INFO")
    args = parser.parse_args(argv)
    if args.local and args.command != "run":
        parser.error("--local applies only to run")
    if args.force and args.command not in ("run", "build"):
        parser.error("--force applies only to run/build")
    if args.timeout <= 0 or args.concurrency <= 0 or args.delay < 0:
        parser.error("timeout/concurrency must be positive and delay nonnegative")
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(levelname)s %(name)s: %(message)s")
    raw, output, reports = (path.resolve() for path in (args.raw_dir, args.output_dir, args.reports_dir))
    try:
        with (DATASET / ".pipeline.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if args.command == "validate":
                validate(output, reports)
            else:
                snapshot = (fetch(raw, HttpClient(args.timeout, args.concurrency, args.delay))
                            if args.command == "fetch" or (args.command == "run" and not args.local)
                            else resolve(raw))
                if args.command != "fetch":
                    build(snapshot, output, reports, args.force, args.image)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.CalledProcessError) as error:
        print("ERROR: %s" % error, file=sys.stderr)
        return 1
    return 0
