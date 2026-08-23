"""Download an immutable snapshot of the Council's 12 KML source files."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ElementTree
from datetime import UTC, datetime

from sekaiisan_henro import graph, normalize, topology

SOURCE_PAGE_URL = "https://88sekaiisan.org/restroommap/"
DATA_URL = "https://88sekaiisan.org/map/data/"
USER_AGENT = "ohenro-map-data/1.0 (source archive)"
FILES = (
    ("routes/tokushima.kml", "tokushimaken_annairu-to36.kml"),
    ("routes/kochi.kml", "koutiken_annairu-to39.kml"),
    ("routes/ehime.kml", "ehimeken_annairu-to38.kml"),
    ("routes/kagawa.kml", "kagawaken_annairu-to37.kml"),
    ("temples/1-23.kml", "1ban23ban.kml"),
    ("temples/24-39.kml", "24ban39ban.kml"),
    ("temples/40-65.kml", "40ban65ban.kml"),
    ("temples/66-88.kml", "66ban88ban.kml"),
    ("toilets/tokushima.kml", "tokushimaken.kml"),
    ("toilets/kochi.kml", "koutiken.kml"),
    ("toilets/ehime.kml", "ehimeken.kml"),
    ("toilets/kagawa.kml", "kagawaken.kml"),
)


def _write(path: str, body: bytes) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "wb") as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _validate_kml(body: bytes) -> None:
    if not body:
        raise ValueError("response is empty")
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as error:
        raise ValueError("response is not valid KML XML: %s" % error) from error
    if root.tag.rsplit("}", 1)[-1] != "kml":
        raise ValueError("response root is not KML")


def _download(url: str, timeout: int) -> tuple[str, bytes]:
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                if response.status != 200:
                    raise ValueError("GET returned HTTP %s" % response.status)
                return response.headers.get("Content-Type", ""), response.read()
        except (urllib.error.URLError, TimeoutError) as error:
            if attempt == 2:
                raise ValueError("GET failed: %s" % error) from error
            time.sleep(attempt + 1)
    raise AssertionError("unreachable")


def fetch(data_dir: str, timeout: int) -> dict:
    """Fetch every source first, so a failed group never changes current.json."""
    downloaded = []
    digest = hashlib.sha256()
    for local_path, source_file in FILES:
        url = DATA_URL + source_file
        content_type, body = _download(url, timeout)
        _validate_kml(body)
        file_hash = hashlib.sha256(body).hexdigest()
        digest.update(local_path.encode() + b"\0" + bytes.fromhex(file_hash))
        downloaded.append({
            "local_path": local_path,
            "source_file": source_file,
            "url": url,
            "content_type": content_type,
            "size": len(body),
            "sha256": file_hash,
            "body": body,
        })

    snapshot_hash = digest.hexdigest()
    snapshot_dir = os.path.join(data_dir, "snapshots", snapshot_hash)
    is_new = not os.path.exists(os.path.join(snapshot_dir, "metadata.json"))
    checked_at = datetime.now(UTC).isoformat()
    if is_new:
        for file in downloaded:
            _write(os.path.join(snapshot_dir, file["local_path"]), file.pop("body"))
        metadata = {
            "schema_version": 1,
            "dataset_id": "88sekaiisan-henro",
            "organization": "四国遍路世界遺産登録推進協議会",
            "source_page_url": SOURCE_PAGE_URL,
            "retrieved_at": checked_at,
            "sha256": snapshot_hash,
            "files": downloaded,
        }
        _write(os.path.join(snapshot_dir, "metadata.json"), json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True).encode() + b"\n")
    _write(os.path.join(data_dir, "current.json"), json.dumps({
        "schema_version": 1,
        "sha256": snapshot_hash,
        "last_checked_at": checked_at,
    }, ensure_ascii=False, indent=2, sort_keys=True).encode() + b"\n")
    return {"new_snapshot": is_new, "sha256": snapshot_hash, "files": len(downloaded)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="source/88sekaiisan-henro")
    parser.add_argument("--timeout", type=int, default=30)
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("fetch", help="download an immutable snapshot (same as no command)")
    normalize_parser = sub.add_parser("normalize", help="Phase 1 normalization to normalized.json")
    normalize_parser.add_argument("--snapshot", default="current")
    normalize_parser.add_argument("--data-dir", default="source/88sekaiisan-henro")
    normalize_parser.add_argument("--output", default="output/sekaiisan-henro-normalized.json")
    inventory_parser = sub.add_parser(
        "topology-inventory", help="Phase 2A read-only diagnostic topology inventory")
    inventory_parser.add_argument("--input", default="output/sekaiisan-henro-normalized.json")
    inventory_parser.add_argument("--output", default="output/sekaiisan-henro-topology-inventory.json")
    graph_parser = sub.add_parser(
        "build-graph", help="Phase 2B exact-only route graph construction")
    graph_parser.add_argument("--input", default="output/sekaiisan-henro-normalized.json")
    graph_parser.add_argument("--inventory", default="output/sekaiisan-henro-topology-inventory.json")
    graph_parser.add_argument("--output", default="output/sekaiisan-henro-graph.json")
    return parser


def dispatch(args: argparse.Namespace) -> dict:
    """Route a parsed command to its implementation (fetch by default)."""
    if args.command == "normalize":
        return normalize.run_normalize(args.data_dir, args.snapshot, args.output)
    if args.command == "topology-inventory":
        return topology.run_inventory(args.input, args.output)
    if args.command == "build-graph":
        return graph.run_graph(args.input, args.inventory, args.output)
    return fetch(args.data_dir, args.timeout)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = dispatch(args)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    if args.command == "normalize":
        print("normalized: snapshot=%s temples=%d output=%s" % (
            result["snapshot_sha256"], result["accounting"]["temples"], args.output))
    elif args.command == "topology-inventory":
        print("topology-inventory: routes=%d output=%s" % (
            result["analysis_accounting"]["route_records"], args.output))
    elif args.command == "build-graph":
        acct = result["accounting"]
        print("build-graph: nodes=%d edges=%d components=%d isolated=%d "
              "exact_t=%d len_err=%.3e output=%s" % (
                  acct["nodes"], acct["edges"], acct["components"],
                  acct["isolated_components"],
                  acct["exact_connections_consumed"]["endpoint_touches_applied"],
                  acct["lengths"]["max_absolute_error_m"], args.output))
    else:
        print("archive: files=%d sha256=%s new_snapshot=%s" % (result["files"], result["sha256"], result["new_snapshot"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
