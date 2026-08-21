import argparse
import json
import os
import sys
from datetime import datetime, timezone

from henroyado.fetcher import DEFAULT_RAW_FILENAME, fetch
from henroyado.export_map import export_map
from henroyado.geocode import enrich_file
from henroyado.html_parser import detect_records, extract_all
from henroyado.normalize import normalize_inn

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SOURCE_DIR = os.path.join(ROOT, "source")
OUTPUT_DIR = os.path.join(ROOT, "output", "henroyado")
DEFAULT_RAW_HTML = os.path.join(SOURCE_DIR, DEFAULT_RAW_FILENAME)


def build_parser():
    p = argparse.ArgumentParser(
        prog="python3 -m henroyado",
        description="Henroyado crawler (Phase 1)",
    )
    sub = p.add_subparsers(dest="command")

    f = sub.add_parser("fetch", help="download the full Shikoku inn list and save a raw HTML snapshot")
    f.add_argument("--output", default=DEFAULT_RAW_HTML,
                   help="output HTML path (default: %(default)s)")
    f.add_argument("--timeout", type=int, default=60, help="HTTP timeout seconds (default: %(default)s)")

    d = sub.add_parser("detect", help="detect every accommodation record in a raw HTML snapshot (plan Step 2)")
    d.add_argument("input", nargs="?", default=DEFAULT_RAW_HTML, help="raw HTML file (default: %(default)s)")
    d.add_argument("--output", default=os.path.join(OUTPUT_DIR, "detect.jsonl"),
                   help="detected records JSONL (default: %(default)s)")

    pr = sub.add_parser("parse", help="extract RawInn for every accommodation (plan Step 3)")
    pr.add_argument("input", nargs="?", default=DEFAULT_RAW_HTML, help="raw HTML file (default: %(default)s)")
    pr.add_argument("--output", default=os.path.join(OUTPUT_DIR, "raw.jsonl"),
                    help="RawInn JSONL output (default: %(default)s)")

    n = sub.add_parser("normalize", help="normalize RawInn -> HenroyadoInnV1 (plan Step 4/5)")
    n.add_argument("input", nargs="?", default=os.path.join(OUTPUT_DIR, "raw.jsonl"),
                   help="RawInn JSONL (default: %(default)s)")
    n.add_argument("--output", default=os.path.join(OUTPUT_DIR, "v1.jsonl"),
                   help="V1 JSONL output (default: %(default)s)")
    n.add_argument("--raw-html", default=DEFAULT_RAW_HTML,
                   help="raw HTML snapshot whose mtime becomes source.retrieved_at (default: %(default)s)")

    g = sub.add_parser("geocode", help="enrich V1 records from Google Maps embed place results")
    g.add_argument("input", nargs="?", default=os.path.join(OUTPUT_DIR, "v1.jsonl"),
                   help="V1 JSONL input (default: %(default)s)")
    g.add_argument("--output", default=os.path.join(OUTPUT_DIR, "v1-geocoded.jsonl"),
                   help="geocoded V1 JSONL output (default: %(default)s)")
    g.add_argument("--cache-dir", default=os.path.join(SOURCE_DIR, "henroyado-google-maps"),
                   help="raw Google embed response cache (default: %(default)s)")
    g.add_argument("--timeout", type=int, default=30, help="HTTP timeout seconds (default: %(default)s)")
    g.add_argument("--delay", type=float, default=0.3, help="delay after uncached requests (default: %(default)s)")
    g.add_argument("--force", action="store_true", help="replace cached responses")

    export = sub.add_parser("export-map", help="export geocoded V1 as compact GeoJSON")
    export.add_argument("input", nargs="?", default=os.path.join(OUTPUT_DIR, "v1-geocoded.jsonl"),
                        help="geocoded V1 JSONL input (default: %(default)s)")
    export.add_argument("--output", default=os.path.join(OUTPUT_DIR, "map.geojson"),
                        help="GeoJSON output (default: %(default)s)")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.command is None:
        build_parser().print_help()
        return 1

    if args.command == "fetch":
        path = fetch(args.output, timeout=args.timeout)
        print("fetched -> %s" % path)
        return 0

    if args.command == "detect":
        with open(args.input, "r", encoding="utf-8") as f:
            records, stats = detect_records(f.read())
        if args.output:
            os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                for r in records:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            print("wrote %d records -> %s" % (len(records), args.output))
        print("records: %d (distinct names: %d)" % (stats["records"], stats["distinct_names"]))
        print("  with detail: %d | without detail: %d" % (stats["records_with_detail"], stats["records_without_detail"]))
        print("  by_prefecture: %s" % json.dumps(stats["by_prefecture"], ensure_ascii=False))
        print("  by_table_kind: %s" % json.dumps(stats["by_table_kind"], ensure_ascii=False))
        if stats["duplicate_listings"]:
            print("  duplicate listings: %s" % json.dumps(stats["duplicate_listings"], ensure_ascii=False))
        if stats["issues"]:
            print("  issues: %s" % json.dumps(stats["issues"], ensure_ascii=False))
        return 0

    if args.command == "parse":
        with open(args.input, "r", encoding="utf-8") as f:
            inns = extract_all(f.read())
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            for inn in inns:
                f.write(json.dumps(inn.to_dict(), ensure_ascii=False) + "\n")
        with_content = sum(1 for i in inns
                           if any((i.description, i.route, i.notice, i.room, i.meal,
                                   i.check_in, i.check_out, i.facilities, i.pricing_items,
                                   i.google_maps_search_url, i.images)))
        print("extracted %d RawInn records -> %s" % (len(inns), args.output))
        print("  with detail content: %d | front-row only: %d" % (
            with_content, len(inns) - with_content))
        no_phone = sum(1 for i in inns if not i.phone)
        no_coords = sum(1 for i in inns if not i.google_maps_embed_url)
        print("  no phone: %d | no map embed: %d" % (no_phone, no_coords))
        return 0

    if args.command == "normalize":
        retrieved_at = None
        if os.path.exists(args.raw_html):
            mtime = datetime.fromtimestamp(os.path.getmtime(args.raw_html), tz=timezone.utc)
            retrieved_at = mtime.isoformat(timespec="seconds")
        v1s = []
        with open(args.input, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                raw = json.loads(line)
                v1s.append(normalize_inn(raw, retrieved_at=retrieved_at))
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            for v in v1s:
                f.write(json.dumps(v, ensure_ascii=False) + "\n")
        warn_count = sum(1 for v in v1s if v["_warnings"])
        total_warn = sum(len(v["_warnings"]) for v in v1s)
        print("normalized %d records -> %s" % (len(v1s), args.output))
        print("  records with warnings: %d | total warnings: %d" % (warn_count, total_warn))
        return 0

    if args.command == "geocode":
        stats = enrich_file(args.input, args.output, args.cache_dir,
                            timeout=args.timeout, delay=args.delay, force=args.force)
        print("geocoded %d/%d records -> %s" % (
            stats["geocoded"], stats["records"], args.output))
        print("  no URL: %d | place not found: %d | errors: %d" % (
            stats["no_url"], stats["not_found"], stats["errors"]))
        return 0 if stats["errors"] == 0 else 1

    if args.command == "export-map":
        stats = export_map(args.input, args.output)
        print("export-map: %(features)d/%(records)d features, %(duplicates)d duplicate places -> " % stats + args.output)
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
