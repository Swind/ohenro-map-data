"""Fetch the Omotenashi Henro Walk inspection-route KML."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import urllib.error
import urllib.request
import xml.etree.ElementTree as ElementTree
from datetime import UTC, datetime

KML_URL = "https://komelabo.sakura.ne.jp/omotenashi-henro-walk/kml/route1102.kml"
SOURCE_PAGE_URL = "https://www.omotenashi88.net/issei/issei-map"
DATASET_ID = "omotenashi-henro-inspection-routes"
USER_AGENT = "ohenro-map-data/1.0 (source archive)"


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
    if root.tag.rsplit("}", 1)[-1] != "kml" or not any(
        element.tag.rsplit("}", 1)[-1] == "LineString" for element in root.iter()
    ):
        raise ValueError("response is not a KML document with route lines")


def fetch(data_dir: str, timeout: int) -> dict:
    request = urllib.request.Request(KML_URL, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                raise ValueError("GET KML returned HTTP %s" % response.status)
            body = response.read()
            content_type = response.headers.get("Content-Type", "")
    except urllib.error.URLError as error:
        raise ValueError("GET KML failed: %s" % error) from error
    _validate_kml(body)

    checksum = hashlib.sha256(body).hexdigest()
    snapshot_dir = os.path.join(data_dir, "snapshots", checksum)
    kml_path = os.path.join(snapshot_dir, "route1102.kml")
    is_new = not os.path.exists(kml_path)
    if is_new:
        _write(kml_path, body)
        _write(os.path.join(snapshot_dir, "metadata.json"), json.dumps({
            "schema_version": 1,
            "dataset_id": DATASET_ID,
            "source_page_url": SOURCE_PAGE_URL,
            "kml_url": KML_URL,
            "retrieved_at": datetime.now(UTC).isoformat(),
            "content_type": content_type,
            "size": len(body),
            "sha256": checksum,
            "purpose": "inspection_activity_route_coverage",
            "limitations": [
                "Not evidence that a road is currently maintained.",
                "Not a navigation or traffic-safety guarantee.",
                "The publisher says route geometry can differ from actual roads and traffic conditions can change.",
            ],
        }, ensure_ascii=False, indent=2, sort_keys=True).encode() + b"\n")
    _write(os.path.join(data_dir, "current.json"), json.dumps({
        "schema_version": 1,
        "sha256": checksum,
        "last_checked_at": datetime.now(UTC).isoformat(),
    }, ensure_ascii=False, indent=2, sort_keys=True).encode() + b"\n")
    return {"new_snapshot": is_new, "sha256": checksum, "size": len(body)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="source/omotenashi-henro-inspection")
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args(argv)
    try:
        result = fetch(args.data_dir, args.timeout)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print("archive: sha256=%s new_snapshot=%s size=%d" % (result["sha256"], result["new_snapshot"], result["size"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
