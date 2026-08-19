"""Command-line interface for the min88 lodging pipeline."""

from __future__ import annotations

import argparse
import os
import sys

from min88_lodging.geocode import enrich_file
from min88_lodging.pipeline import (crawl_all, crawl_detail_archive,
                                    crawl_index_archive, normalize_file,
                                    parse_archive)
from min88_lodging.report import generate_report
from min88_lodging.verify import verify

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_DATA_DIR = os.path.join(ROOT, "source", "min88-lodging")
DEFAULT_OUTPUT_DIR = os.path.join(ROOT, "output", "min88-lodging")


def _data_argument(parser):
    parser.add_argument("--data-dir", default=DEFAULT_DATA_DIR,
                        help="raw archive directory (default: %(default)s)")


def _crawl_arguments(parser):
    _data_argument(parser)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--delay", type=float, default=0.3)
    parser.add_argument("--force", action="store_true")


def build_parser():
    parser = argparse.ArgumentParser(prog="python3 -m min88_lodging",
                                     description="min88 lodging archive and normalization pipeline")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (("crawl-index", "archive the Japanese lodging list"),
                            ("crawl-details", "archive details listed in index.json"),
                            ("crawl-all", "archive the list and all details")):
        command = commands.add_parser(name, help=help_text)
        _crawl_arguments(command)

    parse = commands.add_parser("parse", help="extract deterministic Raw JSONL offline")
    _data_argument(parse)
    parse.add_argument("--output", default=os.path.join(DEFAULT_OUTPUT_DIR, "raw.jsonl"))

    normalize = commands.add_parser("normalize", help="normalize Raw JSONL to Min88LodgingV1")
    _data_argument(normalize)
    normalize.add_argument("input", nargs="?", default=os.path.join(DEFAULT_OUTPUT_DIR, "raw.jsonl"))
    normalize.add_argument("--output", default=os.path.join(DEFAULT_OUTPUT_DIR, "v1.jsonl"))

    geocode = commands.add_parser("geocode", help="optionally enrich V1 with Google place coordinates")
    _data_argument(geocode)
    geocode.add_argument("input", nargs="?", default=os.path.join(DEFAULT_OUTPUT_DIR, "v1.jsonl"))
    geocode.add_argument("--output", default=os.path.join(DEFAULT_OUTPUT_DIR, "v1-geocoded.jsonl"))
    geocode.add_argument("--cache-dir", default=None)
    geocode.add_argument("--timeout", type=float, default=30)
    geocode.add_argument("--delay", type=float, default=0.3)
    geocode.add_argument("--force", action="store_true")

    for name, help_text in (("verify", "verify archive and generated outputs offline"),
                            ("report", "write deterministic coverage and warning report")):
        command = commands.add_parser(name, help=help_text)
        _data_argument(command)
        command.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
        if name == "report":
            command.add_argument("--output", default=None)
    return parser


def _run(args):
    crawl_kwargs = {"timeout": args.timeout, "delay": args.delay, "force": args.force} \
        if args.command.startswith("crawl-") else None
    if args.command == "crawl-index":
        result = crawl_index_archive(args.data_dir, **crawl_kwargs)
        print("crawl-index: %d records (%s)" % (result["record_count"], result["archive"]["status"]))
        return 0 if result.get("index") else 1
    if args.command == "crawl-details":
        result = crawl_detail_archive(args.data_dir, **crawl_kwargs)
        print("crawl-details: %(fetched)d fetched, %(skipped)d skipped, %(failed)d failed" % result)
        return 0 if not result["failed"] else 1
    if args.command == "crawl-all":
        result = crawl_all(args.data_dir, **crawl_kwargs)
        details = result["details"]
        if details is None:
            print("crawl-all: index failed")
            return 1
        print("crawl-all: %d records, %d detail failures" % (result["index"]["record_count"], details["failed"]))
        return 0 if not details["failed"] else 1
    if args.command == "parse":
        result = parse_archive(args.data_dir, args.output)
        print("parse: %(records)d records, %(skipped)d skipped -> " % result + args.output)
        return 0 if not result["skipped"] else 1
    if args.command == "normalize":
        result = normalize_file(args.input, args.output, args.data_dir)
        print("normalize: %(records)d records, %(warnings)d warnings -> " % result + args.output)
        return 0
    if args.command == "geocode":
        cache_dir = args.cache_dir or os.path.join(args.data_dir, "google-maps")
        result = enrich_file(args.input, args.output, cache_dir, timeout=args.timeout,
                             delay=args.delay, force=args.force)
        fetch_errors = result.get("fetch_errors", result.get("errors", 0))
        print("geocode: %d/%d resolved, %d fetch errors -> %s" %
              (result["geocoded"], result["records"], fetch_errors, args.output))
        return 0 if not fetch_errors else 1
    if args.command == "verify":
        result = verify(args.data_dir, args.output_dir)
        print("verify: %s (index=%d detail=%d raw=%d v1=%d)" %
              (("OK" if result["ok"] else "FAILED"), result.get("index_records", 0),
               result.get("detail_parseable", 0), result.get("raw_records", 0), result.get("v1_records", 0)))
        for error in result["errors"]:
            print("  ERROR: " + error)
        for warning in result["warnings"]:
            print("  WARN: " + warning)
        return 0 if result["ok"] else 1
    if args.command == "report":
        result = generate_report(args.data_dir, args.output_dir, args.output)
        print("report: %d V1 records, %d warnings, verify=%s" %
              (result["records"]["v1"], result["warnings"]["total"],
               "OK" if result["verify"]["ok"] else "FAILED"))
        return 0 if result["verify"]["ok"] else 1
    return 2


def main(argv=None):
    try:
        return _run(build_parser().parse_args(argv))
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    except (OSError, ValueError) as error:
        print("error: %s" % error, file=sys.stderr)
        return 1
