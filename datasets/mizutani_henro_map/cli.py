"""Command-line entry point for the Mizutani Henro Guide Map pipeline."""

from __future__ import annotations

import argparse
import sys

from datasets.mizutani_henro_map import config
from datasets.mizutani_henro_map.diff import generate_update_report
from datasets.mizutani_henro_map.export_map import export_map
from datasets.mizutani_henro_map.fetch import fetch
from datasets.mizutani_henro_map.inspect import inspect
from datasets.mizutani_henro_map.normalize import normalize
from datasets.mizutani_henro_map.verify import verify


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m datasets.mizutani_henro_map")
    parser.add_argument("--data-dir", default=config.DEFAULT_DATA_DIR)
    parser.add_argument("--timeout", type=int, default=config.DEFAULT_TIMEOUT)
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("fetch", help="download and archive the current KML")
    inspect_parser = subcommands.add_parser("inspect", help="write a KML style and geometry inventory")
    inspect_parser.add_argument("--snapshot", help="snapshot SHA-256 (default: current)")
    inspect_parser.add_argument("--output", default="datasets/mizutani_henro_map/output/mizutani-henro-style-inventory.json")
    normalize_parser = subcommands.add_parser("normalize", help="write deterministic normalized JSON")
    normalize_parser.add_argument("--snapshot", help="snapshot SHA-256 (default: current)")
    normalize_parser.add_argument("--output", default="datasets/mizutani_henro_map/output/mizutani-henro-map.json")
    export_parser = subcommands.add_parser("export-map", help="write route and POI GeoJSON")
    export_parser.add_argument("--input", default="datasets/mizutani_henro_map/output/mizutani-henro-map.json")
    export_parser.add_argument("--routes", default="datasets/mizutani_henro_map/output/mizutani-henro-routes.geojson")
    export_parser.add_argument("--pois", default="datasets/mizutani_henro_map/output/mizutani-henro-pois.geojson")
    export_parser.add_argument("--report", default="datasets/mizutani_henro_map/output/mizutani-henro-report.json")
    verify_parser = subcommands.add_parser("verify", help="verify raw, normalized, and GeoJSON accounting")
    verify_parser.add_argument("--snapshot", help="snapshot SHA-256 (default: current)")
    verify_parser.add_argument("--normalized", default="datasets/mizutani_henro_map/output/mizutani-henro-map.json")
    verify_parser.add_argument("--routes", default="datasets/mizutani_henro_map/output/mizutani-henro-routes.geojson")
    verify_parser.add_argument("--pois", default="datasets/mizutani_henro_map/output/mizutani-henro-pois.geojson")
    diff_parser = subcommands.add_parser("diff", help="write a deterministic report between two snapshots")
    diff_parser.add_argument("old_snapshot")
    diff_parser.add_argument("new_snapshot")
    diff_parser.add_argument("--output", default="datasets/mizutani_henro_map/output/mizutani-henro-update-report.json")
    args = parser.parse_args(argv)
    try:
        if args.command == "fetch":
            result = fetch(args.data_dir, timeout=args.timeout)
            print("fetch: %s (%s, %d bytes)" % (
                "new snapshot" if result["new_snapshot"] else "source unchanged",
                result["sha256"], result["size"],
            ))
            return 0
        if args.command == "inspect":
            result = inspect(args.data_dir, snapshot=args.snapshot, output=args.output)
            counts = result["geometry_counts"]
            print("inspect: placemarks=%d points=%d lines=%d styles=%d" % (
                result["placemark_count"], counts["Point"], counts["LineString"], len(result["styles"]),
            ))
            return 0
        if args.command == "normalize":
            result = normalize(args.data_dir, snapshot=args.snapshot, output=args.output)
            print("normalize: features=%d points=%d lines=%d" % (
                result["summary"]["feature_count"], result["summary"]["point_count"], result["summary"]["line_string_count"],
            ))
            return 0
        if args.command == "export-map":
            result = export_map(args.input, routes_path=args.routes, pois_path=args.pois, report_path=args.report)
            print("export-map: routes=%d pois=%d" % (result["routes"], result["pois"]))
            return 0
        if args.command == "verify":
            result = verify(args.data_dir, snapshot=args.snapshot, normalized_path=args.normalized,
                            routes_path=args.routes, pois_path=args.pois)
            print("verify: %s (points=%d lines=%d)" % (
                "OK" if result["ok"] else "FAILED", result["raw_points"], result["raw_lines"],
            ))
            for message in result["errors"]:
                print("  ERROR: %s" % message)
            for message in result["warnings"]:
                print("  WARN: %s" % message)
            return 0 if result["ok"] else 1
        if args.command == "diff":
            result = generate_update_report(args.data_dir, args.old_snapshot, args.new_snapshot, args.output)
            print("diff: added=%d removed=%d changed=%d" % (
                len(result["features"]["added"]), len(result["features"]["removed"]), len(result["features"]["changed"]),
            ))
            return 0
    except (OSError, ValueError) as error:
        print("error: %s" % error, file=sys.stderr)
        return 1
    return 2
