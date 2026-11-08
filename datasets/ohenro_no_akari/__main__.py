"""Refresh the authoritative Henro no Akari web route and publish validated GeoJSON."""
import argparse
import fcntl
import json
from pathlib import Path
import sys
import tempfile

from datasets._pipeline import atomic_json, code_hash, is_current, publish, read_json, verify_report
from . import downloader

DATASET = Path(__file__).resolve().parent
FILES = ("henro-no-akari-route.geojson", "manifest.json")


def validate_data(output):
    collection = read_json(output / FILES[0])
    manifest = read_json(output / "manifest.json")
    counts = downloader.complete_route(collection, manifest)
    if downloader.authoritative_url(downloader.APP_URL, manifest["source_url"]) != manifest["source_url"]:
        raise ValueError("Invalid manifest source URL")
    for key in ("source_sha256", "source_snapshot", "source_html_sha256"):
        value = manifest.get(key)
        if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError(f"Invalid manifest provenance: {key}")
    return counts


def validate(output, reports):
    report = verify_report(output, reports, FILES)
    summary = validate_data(output)
    if report["summary"] != summary:
        raise ValueError("Published route summary differs from report")
    collection = read_json(output / FILES[0])
    if report["inputs"] != {"route_sha256": downloader.identity(collection)}:
        raise ValueError("Published route differs from reported source identity")
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return summary


def build(snapshot, output, reports, force=False):
    metadata, collection, manifest = downloader.verify(snapshot)
    inputs = {"route_sha256": metadata["route"]["route_sha256"]}
    settings = {"code": code_hash(DATASET)}
    if not force and is_current(output, reports, inputs, settings, FILES):
        validate(output, reports)
        print("Route data, settings and outputs unchanged; skipping build", flush=True)
        return
    manifest.update(source_sha256=metadata["route"]["bundle_sha256"],
                    source_snapshot=snapshot.name, source_html_sha256=metadata["html"]["sha256"])
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".akari-build-", dir=output.parent) as directory:
        staged = Path(directory)
        atomic_json(staged / FILES[0], collection)
        atomic_json(staged / "manifest.json", manifest)
        summary = validate_data(staged)
        if downloader.identity(read_json(staged / FILES[0])) != inputs["route_sha256"]:
            raise ValueError("Staged route differs from extracted source")
        if settings != {"code": code_hash(DATASET)} or downloader.verify(snapshot)[0] != metadata:
            raise ValueError("Source or extractor changed during build; not published")
        publish(staged, output, reports, FILES, inputs, settings, summary)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", default="run", choices=("run", "fetch", "build", "validate"))
    parser.add_argument("--local", action="store_true", help="run: use the verified local snapshot without fetching")
    parser.add_argument("--force", action="store_true", help="run/build: rebuild unchanged route data")
    parser.add_argument("--raw-dir", type=Path, default=DATASET / "raw")
    parser.add_argument("--output-dir", type=Path, default=DATASET / "output")
    parser.add_argument("--reports-dir", type=Path, default=DATASET / "reports")
    args = parser.parse_args(argv)
    if args.local and args.command != "run":
        parser.error("--local applies only to run")
    if args.force and args.command not in ("run", "build"):
        parser.error("--force applies only to run/build")
    raw, output, reports = (path.resolve() for path in (args.raw_dir, args.output_dir, args.reports_dir))
    try:
        with (DATASET / ".pipeline.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if args.command == "validate":
                validate(output, reports)
            else:
                snapshot = (downloader.fetch(raw) if args.command == "fetch" or
                            (args.command == "run" and not args.local) else downloader.resolve(raw))
                if args.command != "fetch":
                    build(snapshot, output, reports, args.force)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
