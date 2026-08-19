"""Offline Phase 2 normalization of the raw Shikoku Nature Trail archive."""

from __future__ import annotations

import os

from shikoku_nature_trail.parser.course_detail import parse_course_detail
from shikoku_nature_trail.parser.kml import parse_kml
from shikoku_nature_trail.storage import atomic_write_json, read_json


def _asset_map(course_dir, assets):
    result = {}
    for asset in assets.get("assets", []):
        source_url = asset.get("source_url")
        local_file = asset.get("local_file")
        if source_url and local_file and asset.get("status") == "downloaded":
            result[source_url] = os.path.join(course_dir, local_file).replace(os.sep, "/")
    return result


def normalize_archive(data_dir, output):
    """Normalize an existing archive and atomically write schema version 1."""
    index_path = os.path.join(data_dir, "course-index.json")
    if not os.path.isfile(index_path):
        raise FileNotFoundError("required archive index not found: %s" % index_path)
    index = read_json(index_path)
    courses = []
    warnings = []

    for indexed in index.get("courses", []):
        post_id = indexed.get("source_post_id")
        relative_dir = "courses/%s" % post_id
        course_dir = os.path.join(data_dir, relative_dir)
        detail = {
            "title": None, "description": None, "photo_point": None,
            "tourism_spots": [], "google_my_maps": None, "images": [],
        }
        try:
            with open(os.path.join(course_dir, "page.html"), encoding="utf-8") as file:
                detail = parse_course_detail(file.read(), indexed.get("detail_url") or "")
        except Exception as error:
            warnings.append("course %s HTML: %s" % (post_id, error))

        assets = {"assets": []}
        try:
            assets = read_json(os.path.join(course_dir, "assets.json"))
        except Exception as error:
            warnings.append("course %s assets: %s" % (post_id, error))
        local_assets = _asset_map(relative_dir, assets)

        spots = []
        for spot in detail["tourism_spots"]:
            source_url = spot.pop("image_url")
            spots.append({**spot, "image": ({
                "source_url": source_url,
                "local_path": local_assets.get(source_url),
            } if source_url else None)})

        kml = {"name": None, "description": None, "placemarks": []}
        try:
            with open(os.path.join(course_dir, "map", "map.kml"), "rb") as file:
                kml = parse_kml(file.read())
        except Exception as error:
            warnings.append("course %s KML: %s" % (post_id, error))

        images = [{
            "source_url": image["url"],
            "local_path": local_assets.get(image["url"]),
        } for image in detail["images"]]
        courses.append({
            **indexed,
            "title": detail["title"],
            "description": detail["description"],
            "photo_point": detail["photo_point"],
            "tourism_spots": spots,
            "google_my_maps": detail["google_my_maps"],
            "images": images,
            "kml": kml,
        })

    summary = {
        "course_count": len(courses),
        "photo_point_count": sum(course["photo_point"] is not None for course in courses),
        "tourism_spot_count": sum(len(course["tourism_spots"]) for course in courses),
        "placemark_count": sum(len(course["kml"]["placemarks"]) for course in courses),
        "warning_count": len(warnings),
    }
    dataset = {
        "schema_version": 1,
        "source": "https://shikoku-nature-trail.com/",
        "summary": summary,
        "warnings": warnings,
        "courses": courses,
    }
    atomic_write_json(os.path.abspath(output), dataset)
    return summary
