"""Command-line entry point for the Mizutani Henro Guide Map pipeline."""

from __future__ import annotations

import argparse
import fcntl
from pathlib import Path
import subprocess
import sys

from . import config, pipeline
from .diff import generate_update_report
from .export_map import export_map
from .fetch import fetch
from .inspect import inspect
from .normalize import normalize
from .verify import verify


def _options(parser, *, child=False):
    def default(value):
        return argparse.SUPPRESS if child else value
    parser.add_argument("--raw-dir", "--data-dir", dest="raw_dir", type=Path,
                        default=default(Path(config.DEFAULT_DATA_DIR)))
    parser.add_argument("--output-dir", type=Path, default=default(pipeline.DATASET / "output"))
    parser.add_argument("--reports-dir", type=Path, default=default(pipeline.DATASET / "reports"))
    parser.add_argument("--timeout", type=int, default=default(config.DEFAULT_TIMEOUT))
    parser.add_argument("--local", action="store_true", default=default(False),
                        help="run: use the validated local snapshot")
    parser.add_argument("--force", action="store_true", default=default(False),
                        help="run/build: rebuild unchanged data")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m datasets.mizutani_henro_map")
    _options(parser)
    parser.set_defaults(command="run")
    subcommands = parser.add_subparsers(dest="command")
    for command, help_text in (("run", "refresh and publish all JSON and both tile archives (default)"),
                               ("fetch", "download and archive the validated current KML"),
                               ("build", "publish all outputs from the local KML"),
                               ("validate", "verify published JSON, tiles and provenance")):
        _options(subcommands.add_parser(command, help=help_text), child=True)
    inspect_parser = subcommands.add_parser("inspect", help="write a KML style and geometry inventory")
    normalize_parser = subcommands.add_parser("normalize", help="write deterministic normalized JSON")
    export_parser = subcommands.add_parser("export-map", help="write route and POI GeoJSON")
    verify_parser = subcommands.add_parser("verify", help="verify raw, normalized, and GeoJSON accounting")
    diff_parser = subcommands.add_parser("diff", help="write a deterministic report between two snapshots")
    for child in (inspect_parser, normalize_parser, export_parser, verify_parser, diff_parser):
        _options(child, child=True)
    for child in (inspect_parser, normalize_parser, verify_parser):
        child.add_argument("--snapshot", help="snapshot SHA-256 (default: current)")
    inspect_parser.add_argument("--output")
    normalize_parser.add_argument("--output")
    export_parser.add_argument("--input")
    export_parser.add_argument("--routes")
    export_parser.add_argument("--pois")
    export_parser.add_argument("--report")
    verify_parser.add_argument("--normalized")
    verify_parser.add_argument("--routes")
    verify_parser.add_argument("--pois")
    verify_parser.add_argument("--report")
    diff_parser.add_argument("old_snapshot")
    diff_parser.add_argument("new_snapshot")
    diff_parser.add_argument("--output")
    args = parser.parse_args(argv)
    args.command = args.command or "run"
    if args.local and args.command != "run":
        parser.error("--local applies only to run")
    if args.force and args.command not in ("run", "build"):
        parser.error("--force applies only to run/build")
    raw, output, reports = (path.resolve() for path in (args.raw_dir, args.output_dir, args.reports_dir))
    try:
        with (pipeline.DATASET / ".pipeline.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if args.command == "validate":
                pipeline.validate(raw, output, reports)
            elif args.command in ("run", "fetch", "build"):
                previous_snapshot = None
                if (raw / "current.json").exists():
                    previous_snapshot = pipeline.source(raw)["snapshot_sha256"]
                if args.command == "fetch" or (args.command == "run" and not args.local):
                    result = fetch(str(raw), timeout=args.timeout)
                    print("fetch: %s (%s, %d bytes)" % (
                        "new snapshot" if result["new_snapshot"] else "source unchanged",
                        result["sha256"], result["size"]), flush=True)
                if args.command != "fetch":
                    pipeline.build(raw, output, reports, force=args.force, previous_snapshot=previous_snapshot)
            elif args.command == "inspect":
                result = inspect(str(raw), snapshot=args.snapshot,
                                 output=args.output or output / "mizutani-henro-style-inventory.json")
                print("inspect: placemarks=%d points=%d lines=%d styles=%d" % (
                    result["placemark_count"], result["geometry_counts"]["Point"],
                    result["geometry_counts"]["LineString"], len(result["styles"])))
            elif args.command == "normalize":
                result = normalize(str(raw), snapshot=args.snapshot, output=args.output or output / pipeline.NORMALIZED)
                print("normalize: features=%d points=%d lines=%d" % (
                    result["summary"]["feature_count"], result["summary"]["point_count"], result["summary"]["line_string_count"]))
            elif args.command == "export-map":
                result = export_map(args.input or output / pipeline.NORMALIZED,
                                    routes_path=args.routes or output / pipeline.ROUTES,
                                    pois_path=args.pois or output / pipeline.POIS,
                                    report_path=args.report or output / pipeline.EXPORT_REPORT)
                print("export-map: routes=%d pois=%d" % (result["routes"], result["pois"]))
            elif args.command == "verify":
                result = verify(str(raw), snapshot=args.snapshot,
                                normalized_path=args.normalized or output / pipeline.NORMALIZED,
                                routes_path=args.routes or output / pipeline.ROUTES,
                                pois_path=args.pois or output / pipeline.POIS, report_path=args.report)
                print("verify: %s (points=%d lines=%d)" % (
                    "OK" if result["ok"] else "FAILED", result["raw_points"], result["raw_lines"]))
                for message in result["errors"]:
                    print("  ERROR: %s" % message)
                for message in result["warnings"]:
                    print("  WARN: %s" % message)
                return 0 if result["ok"] else 1
            elif args.command == "diff":
                result = generate_update_report(str(raw), args.old_snapshot, args.new_snapshot,
                                                args.output or output / pipeline.DIFF)
                print("diff: added=%d removed=%d changed=%d" % (
                    len(result["features"]["added"]), len(result["features"]["removed"]), len(result["features"]["changed"])))
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, ImportError, subprocess.CalledProcessError) as error:
        print("error: %s" % error, file=sys.stderr)
        return 1
    return 0
