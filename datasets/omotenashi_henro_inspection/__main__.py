"""Update the inspection-activity KML archive and normalized route GeoJSON."""

from __future__ import annotations

import argparse
from collections import Counter
import fcntl
import hashlib
from html.parser import HTMLParser
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ElementTree
from datetime import UTC, datetime

from datasets import _pipeline as pipeline

KML_URL = "https://komelabo.sakura.ne.jp/omotenashi-henro-walk/kml/route1102.kml"
SOURCE_PAGE_URL = "https://www.omotenashi88.net/issei/issei-map"
DATASET_ID = "omotenashi-henro-inspection-routes"
DATASET = Path(__file__).resolve().parent
USER_AGENT = "ohenro-map-data/1.0 (source archive)"
OUTPUTS = ("omotenashi-henro-inspection-routes.geojson", "source-metadata.json")
PURPOSE = "inspection_activity_route_coverage"
LIMITATIONS = [
    "Not evidence that a road is currently maintained.",
    "Not a navigation or traffic-safety guarantee.",
    "The publisher says route geometry can differ from actual roads and traffic conditions can change.",
]
RIGHTS = "All Rights Reserved; obtain permission before redistribution or packaging."


def _write(path, body):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _tag(element):
    return element.tag.rsplit("}", 1)[-1]


def _text(element, name):
    return next((child.text or "" for child in element if _tag(child) == name), "")


def normalize(body):
    """Keep each placemark and its independent source lines, without joining gaps."""
    if not body:
        raise ValueError("response is empty")
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as error:
        raise ValueError(f"response is not valid KML XML: {error}") from error
    if _tag(root) != "kml":
        raise ValueError("response is not a KML document")
    if any(_tag(e) in {"NetworkLink", "Point", "Polygon", "Model", "Track", "LinearRing"} for e in root.iter()):
        raise ValueError("Route source contains unsupported geometry or unresolved network links")
    features = []
    source_lines = sum(_tag(e) == "LineString" for e in root.iter())

    def visit(element, folders, documents):
        kind = _tag(element)
        if kind == "Folder":
            folders = [*folders, _text(element, "name")]
        elif kind == "Document":
            documents = [*documents, _text(element, "name")]
        if kind == "Placemark":
            parts = []
            for line in element.iter():
                if _tag(line) != "LineString":
                    continue
                coordinate_elements = [e for e in line if _tag(e) == "coordinates"]
                if len(coordinate_elements) != 1:
                    raise ValueError("Each source line must have exactly one coordinate sequence")
                coordinates = []
                for token in (coordinate_elements[0].text or "").split():
                    try:
                        point = [float(value) for value in token.split(",")]
                    except ValueError as error:
                        raise ValueError(f"Invalid KML coordinate: {token}") from error
                    if (len(point) not in (2, 3) or not all(math.isfinite(v) for v in point)
                            or not (131 <= point[0] <= 136 and 31.5 <= point[1] <= 35.5)):
                        raise ValueError(f"Invalid Shikoku coordinate: {token}")
                    coordinates.append(point)
                if len(coordinates) < 2 or len({tuple(p[:2]) for p in coordinates}) < 2:
                    raise ValueError("Empty or degenerate source route line")
                if len({len(p) for p in coordinates}) != 1:
                    raise ValueError("Inconsistent coordinate dimensions within source line")
                parts.append(coordinates)
            if not parts:
                raise ValueError("Placemark contains no route lines")
            index = len(features)
            features.append({"type": "Feature", "id": f"inspection-{index + 1:04d}",
                             "properties": {"source": DATASET_ID, "source_placemark_index": index,
                                            "source_placemark_id": element.get("id"),
                                            "name": _text(element, "name"), "folders": folders,
                                            "documents": documents, "description": _text(element, "description"),
                                            "style_url": _text(element, "styleUrl"), "purpose": PURPOSE},
                             "geometry": {"type": "LineString" if len(parts) == 1 else "MultiLineString",
                                          "coordinates": parts[0] if len(parts) == 1 else parts}})
            return
        for child in element:
            visit(child, folders, documents)

    visit(root, [], [])
    actual_lines = sum(1 if f["geometry"]["type"] == "LineString" else len(f["geometry"]["coordinates"])
                       for f in features)
    if not features or actual_lines != source_lines:
        raise ValueError("Empty source or unaccounted route geometry outside placemarks")
    return {"type": "FeatureCollection", "name": DATASET_ID, "features": features}


def _validate_kml(body):
    normalize(body)


class _Links(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.links = []
        self.scripts = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])
        if tag == "script" and attrs.get("src"):
            self.scripts.append(attrs["src"])


def _download(url, timeout):
    if urllib.parse.urlsplit(url).scheme not in ("http", "https"):
        raise ValueError(f"Unsupported source URL: {url}")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                raise ValueError(f"GET {url} returned HTTP {response.status}")
            return response.read(), response.headers.get("Content-Type", "")
    except urllib.error.URLError as error:
        raise ValueError(f"GET {url} failed: {error}") from error


def discover(timeout):
    """Follow the official page's map and its route declaration, never a dated fallback."""
    evidence = []

    def document(url):
        body, _ = _download(url, timeout)
        evidence.append({"url": url, "sha256": hashlib.sha256(body).hexdigest()})
        return body.decode("utf-8-sig")

    page = _Links(document(SOURCE_PAGE_URL))
    urls = {urllib.parse.urljoin(SOURCE_PAGE_URL, href) for href in page.links
            if re.search(r"\.kml(?:\?.*)?$", href, re.I)}
    if not urls:
        maps = sorted({urllib.parse.urljoin(SOURCE_PAGE_URL, href) for href in page.links
                       if "/omotenashi-henro-walk/app/map" in href})
        if len(maps) != 1:
            raise ValueError("Official source page must declare one inspection map")
        map_url = maps[0]
        map_page = _Links(document(map_url))
        for href in map_page.links:
            if re.search(r"\.kml(?:\?.*)?$", href, re.I):
                urls.add(urllib.parse.urljoin(map_url, href))
        for src in map_page.scripts:
            script_url = urllib.parse.urljoin(map_url, src)
            if (urllib.parse.urlsplit(script_url).netloc != urllib.parse.urlsplit(map_url).netloc
                    or not urllib.parse.urlsplit(script_url).path.startswith(urllib.parse.urlsplit(map_url).path)):
                continue
            script = document(script_url)
            script = re.sub(r"/\*.*?\*/", "", script, flags=re.S)
            script = re.sub(r"^\s*//.*$", "", script, flags=re.M)
            directories = re.findall(r"\b(?:let|const|var)\s+kmlDir\s*=\s*['\"]([^'\"]+)['\"]", script)
            routes = re.findall(r"\b(?:let|const|var)\s+\w*route\w*\s*=\s*omnivore\.kml\(\s*kmlDir\s*\+\s*['\"]([^'\"]+\.kml(?:\?[^'\"]*)?)['\"]", script, re.I)
            if routes and len(directories) != 1:
                raise ValueError("Ambiguous map route directory")
            for route in routes:
                urls.add(urllib.parse.urljoin(urllib.parse.urljoin(map_url, directories[0]), route))
            for route in re.findall(r"\b(?:let|const|var)\s+\w*route\w*\s*=\s*omnivore\.kml\(\s*['\"]([^'\"]+\.kml(?:\?[^'\"]*)?)['\"]", script, re.I):
                urls.add(urllib.parse.urljoin(map_url, route))
    if len(urls) != 1:
        raise ValueError(f"Expected one current inspection route KML, found {sorted(urls)}")
    return urls.pop(), evidence


def _snapshot(raw, checksum):
    if not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", checksum):
        raise ValueError("Invalid snapshot checksum")
    snapshot = Path(raw) / "snapshots" / checksum
    metadata = pipeline.read_json(snapshot / "metadata.json")
    name = metadata.get("kml_file", "route1102.kml")
    if not isinstance(name, str) or Path(name).name != name or not name.endswith(".kml"):
        raise ValueError("Invalid snapshot KML filename")
    path = snapshot / name
    if (metadata["sha256"] != checksum or metadata["dataset_id"] != DATASET_ID
            or metadata["size"] != path.stat().st_size or pipeline.digest(path) != checksum):
        raise ValueError("Snapshot metadata or KML integrity mismatch")
    _validate_kml(path.read_bytes())
    return snapshot, metadata, path


def resolve(raw):
    current = pipeline.read_json(Path(raw) / "current.json")
    return _snapshot(raw, current["sha256"])


def fetch(data_dir, timeout=30):
    raw = Path(data_dir)
    kml_url, evidence = discover(timeout)
    body, content_type = _download(kml_url, timeout)
    _validate_kml(body)
    checksum = hashlib.sha256(body).hexdigest()
    snapshot = raw / "snapshots" / checksum
    is_new = not snapshot.exists()
    if is_new:
        raw.mkdir(parents=True, exist_ok=True)
        filename = Path(urllib.parse.urlsplit(kml_url).path).name
        if not filename.endswith(".kml"):
            raise ValueError("Discovered source is not a KML filename")
        with tempfile.TemporaryDirectory(prefix=".inspection-fetch-", dir=raw) as temporary:
            staged = Path(temporary) / "snapshot"
            staged.mkdir()
            _write(staged / filename, body)
            pipeline.atomic_json(staged / "metadata.json", {
                "schema_version": 1, "dataset_id": DATASET_ID, "source_page_url": SOURCE_PAGE_URL,
                "kml_url": kml_url, "kml_file": filename, "discovery": evidence,
                "retrieved_at": datetime.now(UTC).isoformat(), "content_type": content_type,
                "size": len(body), "sha256": checksum, "purpose": PURPOSE,
                "limitations": LIMITATIONS, "rights": RIGHTS,
            })
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged, snapshot)
    _snapshot(raw, checksum)
    pipeline.atomic_json(raw / "current.json", {
        "schema_version": 1, "sha256": checksum, "kml_url": kml_url,
        "last_checked_at": datetime.now(UTC).isoformat(),
    })
    return {"new_snapshot": is_new, "sha256": checksum, "size": len(body)}


def _provenance(metadata):
    return {"schema_version": 1, "dataset_id": DATASET_ID,
            "source_page_url": metadata["source_page_url"], "kml_url": metadata["kml_url"],
            "source_sha256": metadata["sha256"], "source_size": metadata["size"],
            "discovery": metadata.get("discovery", []),
            "purpose": PURPOSE, "limitations": LIMITATIONS, "rights": RIGHTS,
            "coordinate_reference_system": "OGC:CRS84 (KML longitude, latitude, optional altitude)",
            "geometry_policy": "Source placemarks and independent lines preserved; no joins or simplification."}


def _summary(collection):
    parts = [line for feature in collection["features"]
             for line in ([feature["geometry"]["coordinates"]] if feature["geometry"]["type"] == "LineString"
                          else feature["geometry"]["coordinates"])]
    points = [point for part in parts for point in part]
    return {"feature_count": len(collection["features"]), "line_count": len(parts),
            "coordinate_count": len(points),
            "geometry_types": dict(Counter(f["geometry"]["type"] for f in collection["features"])),
            "bounds": [min(p[0] for p in points), min(p[1] for p in points),
                       max(p[0] for p in points), max(p[1] for p in points)]}


def validate_data(output, snapshot):
    _, metadata, path = snapshot
    expected = normalize(path.read_bytes())
    if pipeline.read_json(output / OUTPUTS[0]) != expected:
        raise ValueError("Normalized routes differ from source placemarks, folders or coordinates")
    if pipeline.read_json(output / OUTPUTS[1]) != _provenance(metadata):
        raise ValueError("Published provenance differs from selected source")
    return _summary(expected)


def _inputs(snapshot):
    directory, metadata, _ = snapshot
    return {"kml_sha256": metadata["sha256"], "metadata_sha256": pipeline.digest(directory / "metadata.json")}


def validate(output, reports, snapshot):
    report = pipeline.verify_report(output, reports, OUTPUTS)
    summary = validate_data(output, snapshot)
    if report["inputs"] != _inputs(snapshot) or report["summary"] != summary:
        raise ValueError("Published report differs from selected source or route accounting")
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return summary


def build(snapshot, output, reports, force=False):
    inputs = _inputs(snapshot)
    settings = {"schema_version": 1, "code": pipeline.code_hash(DATASET)}
    if not force and pipeline.is_current(output, reports, inputs, settings, OUTPUTS):
        validate(output, reports, snapshot)
        print("Inputs, settings and outputs unchanged; skipping build", flush=True)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".inspection-build-", dir=output.parent) as temporary:
        staged = Path(temporary)
        pipeline.atomic_json(staged / OUTPUTS[0], normalize(snapshot[2].read_bytes()))
        pipeline.atomic_json(staged / OUTPUTS[1], _provenance(snapshot[1]))
        summary = validate_data(staged, snapshot)
        if (inputs != _inputs(snapshot) or pipeline.digest(snapshot[2]) != inputs["kml_sha256"]
                or settings["code"] != pipeline.code_hash(DATASET)):
            raise ValueError("Source or normalizer changed during build; not published")
        pipeline.publish(staged, output, reports, OUTPUTS, inputs, settings, summary)
    validate(output, reports, snapshot)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", default="run", choices=("run", "fetch", "build", "validate"))
    parser.add_argument("--local", action="store_true", help="run: use the selected local snapshot")
    parser.add_argument("--force", action="store_true", help="run/build: rebuild unchanged outputs")
    parser.add_argument("--raw-dir", "--data-dir", dest="raw_dir", type=Path, default=DATASET / "raw")
    parser.add_argument("--output-dir", type=Path, default=DATASET / "output")
    parser.add_argument("--reports-dir", type=Path, default=DATASET / "reports")
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args(argv)
    if args.local and args.command != "run":
        parser.error("--local applies only to run")
    if args.force and args.command not in ("run", "build"):
        parser.error("--force applies only to run/build")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    raw, output, reports = (p.resolve() for p in (args.raw_dir, args.output_dir, args.reports_dir))
    try:
        with (DATASET / ".pipeline.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if args.command == "fetch" or (args.command == "run" and not args.local):
                result = fetch(raw, args.timeout)
                print("archive: sha256=%s new_snapshot=%s size=%d" %
                      (result["sha256"], result["new_snapshot"], result["size"]))
            if args.command != "fetch":
                snapshot = resolve(raw)
                if args.command == "validate":
                    validate(output, reports, snapshot)
                else:
                    build(snapshot, output, reports, args.force)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
