"""Fetch and archive KML snapshots without replacing a valid current version."""

from __future__ import annotations

import os
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ElementTree

from mizutani_henro_map import config
from mizutani_henro_map.storage import atomic_write_bytes, atomic_write_json, sha256_bytes, utc_now


def _validate_kml(body: bytes) -> None:
    if not body or b"<kml" not in body.lower():
        raise ValueError("response is not a non-empty KML document")
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as error:
        raise ValueError("invalid KML XML: %s" % error) from error
    if root.tag.rsplit("}", 1)[-1] != "kml" or not any(
        element.tag.rsplit("}", 1)[-1] == "Document" for element in root.iter()
    ):
        raise ValueError("KML document root or Document element is missing")


def _get(url: str, timeout: int) -> tuple[int | None, dict[str, str], bytes]:
    request = urllib.request.Request(url, headers={"User-Agent": config.USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.getcode(), dict(response.headers.items()), response.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers.items()) if error.headers else {}, error.read()


def _download(timeout: int) -> tuple[int | None, dict[str, str], bytes]:
    last = (None, {}, b"")
    for attempt in range(config.MAX_ATTEMPTS):
        try:
            last = _get(config.KML_URL, timeout)
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            last = (None, {}, b"")
        if last[0] == 200 or last[0] not in {None, 429, 500, 502, 503, 504}:
            return last
        if attempt < config.MAX_ATTEMPTS - 1:
            time.sleep(config.BACKOFF_SECONDS[attempt])
    return last


def fetch(data_dir: str = config.DEFAULT_DATA_DIR, *, timeout: int = config.DEFAULT_TIMEOUT) -> dict:
    """Fetch the source KML and atomically update the current snapshot pointer."""
    status, headers, body = _download(timeout)
    checked_at = utc_now()
    layout = config.data_layout(data_dir)
    try:
        if status != 200:
            raise ValueError("GET KML returned HTTP %s" % (status if status is not None else "network error"))
        _validate_kml(body)
    except ValueError:
        if body:
            atomic_write_bytes(os.path.join(layout["failed"], checked_at.replace(":", "") + ".failed"), body)
        raise

    checksum = sha256_bytes(body)
    snapshot_dir = os.path.join(layout["snapshots"], checksum)
    is_new = not os.path.exists(os.path.join(snapshot_dir, "map.kml"))
    metadata = {
        "schema_version": 1,
        "dataset_id": config.DATASET_ID,
        "map_id": config.MAP_ID,
        "title": config.TITLE,
        "author": config.AUTHOR,
        "source_map_url": config.SOURCE_MAP_URL,
        "source_article_url": config.SOURCE_ARTICLE_URL,
        "kml_url": config.KML_URL,
        "retrieved_at": checked_at,
        "http_status": status,
        "content_type": headers.get("Content-Type", ""),
        "size": len(body),
        "sha256": checksum,
    }
    if is_new:
        atomic_write_bytes(os.path.join(snapshot_dir, "map.kml"), body)
        atomic_write_json(os.path.join(snapshot_dir, "metadata.json"), metadata)

    atomic_write_json(layout["current"], {
        "schema_version": 1,
        "sha256": checksum,
        "last_checked_at": checked_at,
        "snapshot_retrieved_at": metadata["retrieved_at"],
    })
    return {"sha256": checksum, "new_snapshot": is_new, "size": len(body)}
