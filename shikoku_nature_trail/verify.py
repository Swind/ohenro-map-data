"""Verify archive completeness (plan §28).

Checks: four index files exist; course count; every course has detail HTML;
every course with a map has valid KML; asset manifests exist; images present;
checksums match where recorded.
"""

from __future__ import annotations

import json
import logging
import os

from shikoku_nature_trail import config
from shikoku_nature_trail.storage import sha256_file

logger = logging.getLogger(__name__)


def _verify_kml(path: str) -> bool:
    if not os.path.exists(path):
        return False
    with open(path, "rb") as f:
        head = f.read(4096)
    return b"<kml" in head


def verify(data_dir: str):
    """Return a dict of verification results."""
    layout = config.data_layout(data_dir)
    schema_path = layout["schema"]
    if not os.path.exists(schema_path):
        return {"ok": False, "errors": ["course-index.json missing; run crawl-index"]}

    with open(schema_path, encoding="utf-8") as f:
        schema = json.load(f)
    courses = schema["courses"]

    errors = []
    warnings = []

    # 1. four indexes exist
    for pref in config.PREFECTURES:
        path = config.index_path(data_dir, pref.id)
        if not os.path.exists(path):
            errors.append("missing index: %s" % path)
        elif os.path.getsize(path) == 0:
            errors.append("empty index: %s" % path)

    # 2. course count
    if schema.get("course_count", len(courses)) != len(courses):
        errors.append("course_count mismatch in course-index.json")

    # 3. per-course checks
    courses_with_map = 0
    kml_ok = 0
    images_pending = 0
    images_downloaded = 0
    image_checksum_fail = 0
    html_checksum_fail = 0

    for course in courses:
        post_id = course["source_post_id"]
        ddir = config.course_dir(data_dir, post_id)
        page_path = os.path.join(ddir, "page.html")
        meta_path = os.path.join(ddir, "metadata.json")
        assets_path = os.path.join(ddir, "assets.json")

        if not os.path.exists(page_path):
            errors.append("post %s: missing detail HTML" % post_id)
        else:
            # checksum for detail HTML when recorded
            if os.path.exists(meta_path):
                with open(meta_path, encoding="utf-8") as f:
                    meta = json.load(f)
                if meta.get("sha256") and meta["sha256"] != sha256_file(page_path):
                    html_checksum_fail += 1
                    errors.append("post %s: detail HTML checksum mismatch" % post_id)

                maps = meta.get("google_my_maps")
                if maps:
                    courses_with_map += 1
                    kml_path = os.path.join(ddir, "map", "map.kml")
                    if _verify_kml(kml_path):
                        kml_ok += 1
                        # checksum for KML
                        kml_meta_path = os.path.join(ddir, "map", "metadata.json")
                        if os.path.exists(kml_meta_path):
                            with open(kml_meta_path, encoding="utf-8") as f:
                                kmeta = json.load(f)
                            if kmeta.get("sha256") and kmeta["sha256"] != sha256_file(kml_path):
                                errors.append("post %s: KML checksum mismatch" % post_id)
                    else:
                        errors.append("post %s: map present but no valid KML" % post_id)

        if not os.path.exists(assets_path):
            warnings.append("post %s: no assets.json (no images parsed?)" % post_id)
            continue
        with open(assets_path, encoding="utf-8") as f:
            manifest = json.load(f)
        for asset in manifest["assets"]:
            if asset["status"] == "pending":
                images_pending += 1
            elif asset["status"] == "downloaded":
                images_downloaded += 1
                local = os.path.join(ddir, asset["local_file"])
                if not os.path.exists(local):
                    errors.append("post %s: image missing %s" % (post_id, asset["local_file"]))
                elif asset.get("sha256") and asset["sha256"] != sha256_file(local):
                    image_checksum_fail += 1
                    errors.append("post %s: image checksum mismatch %s" % (post_id, asset["local_file"]))

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "course_count": len(courses),
        "courses_with_map": courses_with_map,
        "kml_ok": kml_ok,
        "images_pending": images_pending,
        "images_downloaded": images_downloaded,
        "image_checksum_fail": image_checksum_fail,
        "html_checksum_fail": html_checksum_fail,
    }