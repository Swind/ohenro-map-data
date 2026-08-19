"""CLI for the Shikoku Nature Trail crawler.

Commands (plan §26):
  crawl-index        download the four prefecture course lists + course-index.json
  crawl-details      download each course detail page + metadata/assets manifests
  download-assets    download content images
  download-kml       download Google My Maps KML files
  crawl-all          run everything (index -> details -> assets -> kml -> report)
  verify             check archive completeness
  report             write the crawl report (JSON + Markdown)
  normalize          build the deterministic Phase 2 dataset offline
  export-map         export normalized routes and POIs for vector tiles
"""

from __future__ import annotations

import argparse
import logging
import sys

from shikoku_nature_trail import config
from shikoku_nature_trail.crawler.assets import download_assets
from shikoku_nature_trail.crawler.detail import crawl_details
from shikoku_nature_trail.crawler.index import crawl_index
from shikoku_nature_trail.crawler.kml import download_kml
from shikoku_nature_trail.crawler.manifest import build_manifest
from shikoku_nature_trail.http import HttpClient
from shikoku_nature_trail.export_map import export_map
from shikoku_nature_trail.normalize import normalize_archive
from shikoku_nature_trail.report import generate_report
from shikoku_nature_trail.verify import verify


def build_parser():
    p = argparse.ArgumentParser(
        prog="python3 -m shikoku_nature_trail",
        description="Shikoku Nature Trail archive and normalization pipeline",
    )
    p.add_argument("--data-dir", default=config.DEFAULT_DATA_DIR,
                   help="raw archive directory (default: %(default)s)")
    p.add_argument("--timeout", type=int, default=config.DEFAULT_TIMEOUT,
                   help="HTTP timeout seconds (default: %(default)s)")
    p.add_argument("--concurrency", type=int, default=config.DEFAULT_CONCURRENCY,
                   help="max concurrent requests (default: %(default)s)")
    p.add_argument("--delay", type=float, default=config.DEFAULT_DELAY,
                   help="min delay between requests, seconds (default: %(default)s)")
    p.add_argument("--force", action="store_true",
                   help="refetch even if already downloaded")
    p.add_argument("--log-level", default="INFO",
                   choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("crawl-index", help="download course lists + build index")
    sub.add_parser("crawl-details", help="download course detail pages")
    sub.add_parser("download-assets", help="download course images")
    sub.add_parser("download-kml", help="download Google My Maps KML")
    sub.add_parser("crawl-all", help="run the full crawl pipeline")
    sub.add_parser("verify", help="check archive completeness")
    sub.add_parser("report", help="write the crawl report")
    normalize = sub.add_parser("normalize", help="build normalized JSON offline")
    normalize.add_argument("--output", default="output/shikoku-nature-trail.json",
                           help="normalized JSON path (default: %(default)s)")
    export = sub.add_parser("export-map", help="export normalized routes and POIs offline")
    export.add_argument("--input", default="output/shikoku-nature-trail.json",
                        help="normalized JSON path (default: %(default)s)")
    export.add_argument("--routes", default="output/shikoku-nature-trail.geojson",
                        help="routes GeoJSON path (default: %(default)s)")
    export.add_argument("--pois", default="output/shikoku-nature-trail-pois.geojson",
                        help="POIs GeoJSON path (default: %(default)s)")
    export.add_argument("--report", default="output/shikoku-nature-trail-report.json",
                        help="export report path (default: %(default)s)")
    return p


def _make_client(args):
    return HttpClient(timeout=args.timeout, concurrency=args.concurrency,
                      delay=args.delay)


def _run(args):
    if args.command == "export-map":
        result = export_map(args.input, args.routes, args.pois, args.report)
        print("export-map: routes=%(route_ids)d segments=%(route_segments)d "
              "route_points=%(route_coordinate_points)d pois=%(kml_pois)d "
              "linked=%(linked_tourism_spots)d unmatched_spots=%(unmatched_tourism_spots)d "
              "unmatched_pois=%(unmatched_pois)d ambiguous=%(ambiguous_names)d" % result)
        return 0

    if args.command == "normalize":
        result = normalize_archive(args.data_dir, args.output)
        print("normalize: courses=%(course_count)d photo_points=%(photo_point_count)d "
              "tourism_spots=%(tourism_spot_count)d placemarks=%(placemark_count)d "
              "warnings=%(warning_count)d" % result)
        return 0

    client = _make_client(args)
    if args.command == "crawl-index":
        result = crawl_index(client, args.data_dir, force=args.force)
        print("crawl-index: %d courses across %d indexes" % (
            result["course_count"], len(result["indexes"])))
        return 0

    if args.command == "crawl-details":
        ok, failures = crawl_details(client, args.data_dir, force=args.force)
        print("crawl-details: %d ok, %d failed" % (ok, len(failures)))
        return 0 if not failures else 1

    if args.command == "download-assets":
        ok, failures = download_assets(client, args.data_dir, force=args.force)
        print("download-assets: %d ok, %d failed" % (ok, len(failures)))
        return 0 if not failures else 1

    if args.command == "download-kml":
        ok, failures = download_kml(client, args.data_dir, force=args.force)
        print("download-kml: %d ok, %d failed" % (ok, len(failures)))
        return 0 if not failures else 1

    if args.command == "crawl-all":
        failures = []
        r1 = crawl_index(client, args.data_dir, force=args.force)
        print("crawl-index: %d courses" % r1["course_count"])
        failures += r1["failures"]
        ok2, f2 = crawl_details(client, args.data_dir, force=args.force)
        print("crawl-details: %d ok, %d failed" % (ok2, len(f2)))
        failures += f2
        ok3, f3 = download_assets(client, args.data_dir, force=args.force)
        print("download-assets: %d ok, %d failed" % (ok3, len(f3)))
        failures += f3
        ok4, f4 = download_kml(client, args.data_dir, force=args.force)
        print("download-kml: %d ok, %d failed" % (ok4, len(f4)))
        failures += f4
        build_manifest(args.data_dir)
        report = generate_report(args.data_dir)
        print("verify: %s" % ("OK" if report["verify_ok"] else "FAILED"))
        return 0 if not failures and report["verify_ok"] else 1

    if args.command == "verify":
        result = verify(args.data_dir)
        print("verify: %s" % ("OK" if result["ok"] else "FAILED"))
        print("courses=%d maps=%d kml_ok=%d images_downloaded=%d pending=%d" % (
            result["course_count"], result["courses_with_map"], result["kml_ok"],
            result["images_downloaded"], result["images_pending"]))
        for e in result["errors"]:
            print("  ERROR: %s" % e)
        for w in result["warnings"]:
            print("  WARN: %s" % w)
        return 0 if result["ok"] else 1

    if args.command == "report":
        report = generate_report(args.data_dir)
        print("report written: %d courses, verify=%s" % (
            report["course_count"], "OK" if report["verify_ok"] else "FAILED"))
        return 0 if report["verify_ok"] else 1

    return 2


def main(argv=None):
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        return _run(args)
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    except (OSError, ValueError) as e:
        print("error: %s" % e, file=sys.stderr)
        return 1
