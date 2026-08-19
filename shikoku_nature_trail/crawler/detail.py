"""Stage 3/4: download course detail HTML, then parse metadata + assets.

Plan §11/§12: always write page.html to disk first, then run the parser.
Resume: skip courses whose page.html exists unless --force.
"""

from __future__ import annotations

import logging
import os

from shikoku_nature_trail import config
from shikoku_nature_trail.http import HttpClient
from shikoku_nature_trail.parser.course_detail import parse_course_detail
from shikoku_nature_trail.storage import (
    atomic_write_bytes,
    atomic_write_json,
    local_now,
    sha256_bytes,
    sha256_file,
)

logger = logging.getLogger(__name__)


def _course_state(path: str, data_dir: str):
    import json

    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def crawl_details(client: HttpClient, data_dir: str, force: bool = False):
    """Download every course detail page and write metadata.json + assets.json.

    Returns (ok_count, failure list).
    """
    layout = config.data_layout(data_dir)
    schema_path = layout["schema"]
    if not os.path.exists(schema_path):
        raise FileNotFoundError("course-index.json missing; run crawl-index first")

    import json

    with open(schema_path, encoding="utf-8") as f:
        schema = json.load(f)
    courses = schema["courses"]

    state_path = layout["state"]
    state = _course_state(state_path, data_dir)
    state.setdefault("schema_version", config.SCHEMA_VERSION)
    state.setdefault("last_run", None)
    state.setdefault("courses", {})

    ok = 0
    failures = []
    for course in courses:
        post_id = course["source_post_id"]
        ddir = config.course_dir(data_dir, post_id)
        page_path = os.path.join(ddir, "page.html")
        meta_path = os.path.join(ddir, "metadata.json")
        assets_path = os.path.join(ddir, "assets.json")

        entry = state["courses"].setdefault(str(post_id), {})
        if os.path.exists(page_path) and not force and entry.get("detail") == "ok":
            logger.info("skip existing detail post_id=%s (use --force)", post_id)
            ok += 1
            continue

        logger.info("fetching detail post_id=%s", post_id)
        status, headers, body = client.get_bytes(course["detail_url"])
        if status != 200:
            failures.append({
                "post_id": post_id, "url": course["detail_url"],
                "status": status, "step": "detail",
            })
            entry["detail"] = "failed"
            logger.error("detail fetch failed post_id=%s HTTP %s", post_id, status)
            continue

        atomic_write_bytes(page_path, body)
        detail = parse_course_detail(body.decode("utf-8", errors="replace"),
                                     course["detail_url"])

        metadata = {
            "schema_version": config.SCHEMA_VERSION,
            "source_post_id": post_id,
            "source_url": course["detail_url"],
            "prefecture": course["prefecture"],
            "title": detail["title"],
            "google_my_maps": detail["google_my_maps"],
            "http": {
                "status": status,
                "downloaded_at": local_now(),
                "etag": headers.get("ETag"),
                "last_modified": headers.get("Last-Modified"),
                "content_type": headers.get("Content-Type"),
                "content_length": len(body),
            },
            "sha256": sha256_bytes(body),
        }
        atomic_write_json(meta_path, metadata)

        # assets manifest: images listed in detail, status pending until download
        assets = []
        for i, img in enumerate(detail["images"], start=1):
            assets.append({
                "source_url": img["url"],
                "type": "image",
                "local_file": "images/%03d" % i,  # extension resolved on download
                "original_filename": os.path.basename(img["url"].split("?")[0]),
                "status": "pending",
            })
        atomic_write_json(assets_path, {
            "schema_version": config.SCHEMA_VERSION,
            "post_id": post_id,
            "image_count": len(assets),
            "assets": assets,
        })

        entry["detail"] = "ok"
        ok += 1
        logger.info("detail ok post_id=%s maps=%s images=%d",
                    post_id,
                    bool(detail["google_my_maps"]),
                    len(detail["images"]))

    state["last_run"] = local_now()
    atomic_write_json(state_path, state)
    logger.info("details complete: %d ok, %d failed", ok, len(failures))
    return ok, failures