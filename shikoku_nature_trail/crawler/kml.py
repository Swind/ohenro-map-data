"""Download Google My Maps KML for each course that has a map (plan §14/§15).

KML URL: https://www.google.com/maps/d/kml?mid={mid}&forcekml=1
Validation: HTTP 200 + non-empty + body contains `<kml`. Google can return
HTML error/auth pages even with 200, so Content-Type is not trusted. Failed
downloads never overwrite an existing valid map.kml (temp file -> validate ->
rename).
"""

from __future__ import annotations

import logging
import os

from shikoku_nature_trail import config
from shikoku_nature_trail.http import HttpClient
from shikoku_nature_trail.storage import (
    atomic_write_bytes,
    atomic_write_json,
    local_now,
    sha256_bytes,
)

logger = logging.getLogger(__name__)


def _looks_like_kml(body: bytes) -> bool:
    return b"<kml" in body[:4096] or b"<kml" in body


def _kml_url(map_id: str) -> str:
    return config.KML_ENDPOINT.format(map_id=map_id)


def _map_metadata_for(course_dir: str):
    meta_path = os.path.join(course_dir, "metadata.json")
    if not os.path.exists(meta_path):
        return None
    import json

    with open(meta_path, encoding="utf-8") as f:
        return json.load(f)


def download_kml(client: HttpClient, data_dir: str, force: bool = False):
    """Download KML for every course with a Google My Maps map.

    Returns (ok_count, failure list, maps_without_kml).
    """
    layout = config.data_layout(data_dir)
    schema_path = layout["schema"]
    if not os.path.exists(schema_path):
        raise FileNotFoundError("course-index.json missing; run crawl-index first")

    import json

    with open(schema_path, encoding="utf-8") as f:
        schema = json.load(f)

    state_path = layout["state"]
    state = {}
    if os.path.exists(state_path):
        with open(state_path, encoding="utf-8") as f:
            state = json.load(f)
    state.setdefault("schema_version", config.SCHEMA_VERSION)
    state.setdefault("courses", {})

    ok = 0
    failures = []
    for course in schema["courses"]:
        post_id = course["source_post_id"]
        ddir = config.course_dir(data_dir, post_id)
        meta = _map_metadata_for(ddir)
        if not meta or not meta.get("google_my_maps"):
            continue
        map_id = meta["google_my_maps"]["map_id"]
        map_dir = os.path.join(ddir, "map")
        kml_path = os.path.join(map_dir, "map.kml")
        kml_meta_path = os.path.join(map_dir, "metadata.json")

        entry = state["courses"].setdefault(str(post_id), {})
        if os.path.exists(kml_path) and not force and entry.get("kml") == "ok":
            logger.info("skip existing KML post_id=%s (use --force)", post_id)
            ok += 1
            continue

        url = _kml_url(map_id)
        logger.info("downloading KML post_id=%s map_id=%s", post_id, map_id)
        status, headers, body = client.get_bytes(url)
        valid = status == 200 and len(body) > 0 and _looks_like_kml(body)
        if not valid:
            failures.append({
                "post_id": post_id, "url": url, "status": status,
                "step": "kml", "reason": "invalid KML",
            })
            entry["kml"] = "failed"
            # preserve response body for debugging, but never clobber valid KML
            if os.path.exists(kml_path):
                logger.warning("KML invalid post_id=%s, keeping previous map.kml", post_id)
            else:
                atomic_write_bytes(os.path.join(map_dir, "map.kml.failed"), body)
                logger.error("KML invalid post_id=%s (status=%s), body saved to map.kml.failed",
                             post_id, status)
            continue

        atomic_write_bytes(kml_path, body)
        atomic_write_json(kml_meta_path, {
            "schema_version": config.SCHEMA_VERSION,
            "map_id": map_id,
            "source_url": url,
            "downloaded_at": local_now(),
            "content_type": headers.get("Content-Type"),
            "size": len(body),
            "sha256": sha256_bytes(body),
        })
        entry["kml"] = "ok"
        ok += 1
        logger.info("KML ok post_id=%s (%d bytes)", post_id, len(body))

    state["last_run"] = local_now()
    atomic_write_json(state_path, state)
    logger.info("KML complete: %d ok, %d failed", ok, len(failures))
    return ok, failures