"""Build the archive manifest (plan §23): the entry point for phase 2.

manifest.json summarizes every course: post_id, prefecture, paths to detail
HTML, metadata, KML, and image count.
"""

from __future__ import annotations

import json
import logging
import os

from shikoku_nature_trail import config
from shikoku_nature_trail.storage import atomic_write_json, local_now, sha256_file

logger = logging.getLogger(__name__)


def build_manifest(data_dir: str):
    layout = config.data_layout(data_dir)
    schema_path = layout["schema"]
    if not os.path.exists(schema_path):
        raise FileNotFoundError("course-index.json missing; run crawl-index first")

    with open(schema_path, encoding="utf-8") as f:
        schema = json.load(f)

    courses = []
    for course in schema["courses"]:
        post_id = course["source_post_id"]
        ddir = config.course_dir(data_dir, post_id)
        page_path = os.path.join(ddir, "page.html")
        meta_path = os.path.join(ddir, "metadata.json")
        assets_path = os.path.join(ddir, "assets.json")
        kml_path = os.path.join(ddir, "map", "map.kml")

        image_count = 0
        if os.path.exists(assets_path):
            with open(assets_path, encoding="utf-8") as f:
                manifest = json.load(f)
            image_count = len(manifest.get("assets", []))

        entry = {
            "post_id": post_id,
            "prefecture": course["prefecture"],
            "detail_html": os.path.relpath(page_path, data_dir) if os.path.exists(page_path) else None,
            "metadata": os.path.relpath(meta_path, data_dir) if os.path.exists(meta_path) else None,
            "assets": os.path.relpath(assets_path, data_dir) if os.path.exists(assets_path) else None,
            "kml": os.path.relpath(kml_path, data_dir) if os.path.exists(kml_path) else None,
            "image_count": image_count,
        }
        courses.append(entry)

    manifest = {
        "schema_version": config.SCHEMA_VERSION,
        "source": "shikoku-nature-trail.com",
        "generated_at": local_now(),
        "course_count": len(courses),
        "courses": courses,
    }
    atomic_write_json(layout["manifest"], manifest)
    logger.info("wrote %s (%d courses)", layout["manifest"], len(courses))
    return manifest