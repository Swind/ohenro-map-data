"""Archive index pages, route pages, and their Google My Maps KML."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET

from datasets.arukihenro_routes.parser import parse_index, parse_route

INDEX_PAGES = {
    "tokushima": "https://ohenro.jp/blog/arukihenro/tera-tokushima/",
    "kochi": "https://ohenro.jp/blog/arukihenro/tera-kochi/",
    "ehime": "https://ohenro.jp/blog/arukihenro/tera-ehime/",
    "kagawa": "https://ohenro.jp/blog/arukihenro/tera-kagawa/",
}
EXTRA_ROUTES = ["https://ohenro.jp/blog/arukihenro/betsu/betsu-04/"]
USER_AGENT = "ohenro-map-data/1.0 (offline archive)"


def _write(path: str, data: bytes) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _get(url: str, timeout: int) -> bytes:
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                if response.status != 200:
                    raise ValueError("GET %s returned HTTP %s" % (url, response.status))
                return response.read()
        except (urllib.error.URLError, TimeoutError):
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


def _validate_kml(body: bytes) -> None:
    try:
        root = ET.fromstring(body)
    except ET.ParseError as error:
        raise ValueError("response is not valid KML XML") from error
    if root.tag.rsplit("}", 1)[-1] != "kml":
        raise ValueError("response is not KML")


def _fetch(url: str, path: str, timeout: int, delay: float, force: bool, validate=None) -> bytes:
    if not force and os.path.exists(path):
        with open(path, "rb") as stream:
            return stream.read()
    body = _get(url, timeout)
    if validate:
        validate(body)
    _write(path, body)
    time.sleep(delay)
    return body


def archive(data_dir: str, timeout: int, delay: float, force: bool) -> dict:
    """Download the declared source pages and KML without replacing valid files."""
    routes: list[dict] = []
    for region, url in INDEX_PAGES.items():
        body = _fetch(url, os.path.join(data_dir, "indexes", region + ".html"), timeout, delay, force)
        for route_url in parse_index(body.decode("utf-8"), url):
            routes.append({"region": region, "url": route_url})
    routes.extend({"region": "extra", "url": url} for url in EXTRA_ROUTES)

    seen = set()
    records = []
    for route in routes:
        if route["url"] in seen:
            continue
        seen.add(route["url"])
        record_id = hashlib.sha256(route["url"].encode()).hexdigest()[:16]
        record_dir = os.path.join(data_dir, "routes", record_id)
        html = _fetch(route["url"], os.path.join(record_dir, "page.html"), timeout, delay, force).decode("utf-8")
        record = {"id": record_id, **route, **parse_route(html, route["url"])}
        for map_data in record["maps"]:
            kml_path = os.path.join(record_dir, "maps", map_data["map_id"] + ".kml")
            try:
                kml = _fetch(map_data["kml_url"], kml_path, timeout, delay, force, _validate_kml)
                map_data["local_path"] = os.path.relpath(kml_path, data_dir)
                map_data["sha256"] = hashlib.sha256(kml).hexdigest()
            except (OSError, ValueError, urllib.error.URLError) as error:
                map_data["error"] = str(error)
        _write(os.path.join(record_dir, "metadata.json"), json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True).encode() + b"\n")
        records.append(record)
    manifest = {"schema_version": 1, "source": "https://ohenro.jp/blog/arukihenro/", "routes": records}
    _write(os.path.join(data_dir, "manifest.json"), json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode() + b"\n")
    return {"routes": len(records), "maps": sum(len(record["maps"]) for record in records)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="datasets/arukihenro_routes/raw")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--delay", type=float, default=0.3)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = archive(args.data_dir, args.timeout, args.delay, args.force)
    except (OSError, ValueError, urllib.error.URLError) as error:
        parser.error(str(error))
    print("archive: routes=%d maps=%d" % (result["routes"], result["maps"]))
    return 0
