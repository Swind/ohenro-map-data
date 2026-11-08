"""Download course content images (plan §16/§17).

Files are numbered 001, 002... under images/ with extension resolved from
Content-Type (falling back to the original URL's extension). Skip already
downloaded files unless --force. Failed downloads keep their previous valid
file (atomic temp -> validate -> rename).
"""

from __future__ import annotations

import logging
import mimetypes
import os

from datasets.shikoku_nature_trail import config
from datasets.shikoku_nature_trail.http import HttpClient
from datasets.shikoku_nature_trail.storage import (
    atomic_write_bytes,
    atomic_write_json,
    local_now,
    sha256_bytes,
)

logger = logging.getLogger(__name__)

CONTENT_TYPE_EXT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/svg+xml": ".svg",
}

# Non-image or dangerous: do not save (theme icons etc. are excluded by parser).
ALLOWED = tuple(CONTENT_TYPE_EXT)


def _ext_for(content_type: str, url: str) -> str:
    if content_type:
        base = content_type.split(";")[0].strip().lower()
        if base in CONTENT_TYPE_EXT:
            return CONTENT_TYPE_EXT[base]
    # fall back to URL extension (minus query string)
    path = url.split("?")[0]
    ext = os.path.splitext(path)[1].lower()
    return ext if ext in (".jpg", ".jpeg", ".png", ".webp", ".gif") else ".jpg"


def image_type(body: bytes) -> str | None:
    """Recognize actual image bytes, not an HTTP error page with an image URL."""
    if body.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if body.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if body.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if body.startswith(b"RIFF") and body[8:12] == b"WEBP":
        return "image/webp"
    return None


def download_assets(client: HttpClient, data_dir: str, force: bool = False):
    """Download all pending images for all courses. Returns (ok, failures)."""
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
        assets_path = os.path.join(ddir, "assets.json")
        if not os.path.exists(assets_path):
            continue
        with open(assets_path, encoding="utf-8") as f:
            manifest = json.load(f)

        entry = state["courses"].setdefault(str(post_id), {})
        changed = False
        for asset in manifest["assets"]:
            if asset["status"] == "downloaded" and not force:
                continue
            url = asset["source_url"]
            logger.info("downloading image post_id=%s: %s", post_id, url)
            status, headers, body = client.get_bytes(url)
            detected_type = image_type(body)
            if status != 200 or detected_type is None:
                failures.append({
                    "post_id": post_id, "url": url,
                    "status": status, "step": "image",
                })
                asset["status"] = "failed"
                asset.setdefault("failures", []).append({
                    "status": status, "at": local_now(),
                })
                changed = True
                logger.warning("image failed post_id=%s HTTP %s", post_id, status)
                continue

            content_type = detected_type
            ext = _ext_for(content_type, url)
            rel = os.path.splitext(asset["local_file"])[0] + ext
            local_path = os.path.join(ddir, rel)
            atomic_write_bytes(local_path, body)

            asset["local_file"] = rel
            asset["content_type"] = content_type.split(";")[0].strip() or None
            asset["status"] = "downloaded"
            asset["size"] = len(body)
            asset["sha256"] = sha256_bytes(body)
            asset.pop("failures", None)
            changed = True
            ok += 1

        if changed:
            atomic_write_json(assets_path, manifest)
        entry["images"] = "ok" if all(
            a["status"] == "downloaded" for a in manifest["assets"]
        ) else "failed"

    state["last_run"] = local_now()
    atomic_write_json(state_path, state)
    logger.info("assets complete: %d downloaded, %d failed", ok, len(failures))
    return ok, failures