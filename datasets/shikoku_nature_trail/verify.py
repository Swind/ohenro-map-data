"""Verify source accounting, provenance, image bytes and route geometry offline."""

from collections import Counter
from pathlib import Path

from bs4 import BeautifulSoup

from datasets._pipeline import digest, read_json
from datasets.shikoku_nature_trail import config
from datasets.shikoku_nature_trail.crawler.assets import image_type
from datasets.shikoku_nature_trail.export_map import _geometry_parts
from datasets.shikoku_nature_trail.parser.course_detail import parse_course_detail
from datasets.shikoku_nature_trail.parser.course_list import parse_course_list
from datasets.shikoku_nature_trail.parser.kml import parse_kml


def _inside(directory, relative):
    path = (directory / relative).resolve()
    if not path.is_relative_to(directory.resolve()):
        raise ValueError("archive path escapes course directory: %s" % relative)
    return path


def verify(data_dir):
    """Return the legacy report shape, treating missing source data as errors."""
    root = Path(data_dir)
    errors = []
    counts = Counter()
    try:
        index = read_json(root / "course-index.json")
        courses = index["courses"]
        if not courses or index["course_count"] != len(courses):
            raise ValueError("empty index or course_count mismatch")
        ids = [str(c["source_post_id"]) for c in courses]
        if any(not post.isdigit() for post in ids) or len(ids) != len(set(ids)):
            raise ValueError("invalid or duplicate course IDs")
        counts["course_count"] = len(courses)
        if set(index["indexes"]) != {pref.id for pref in config.PREFECTURES}:
            raise ValueError("missing prefecture indexes")
        for pref in config.PREFECTURES:
            path = root / "indexes" / (pref.id + ".html")
            html = path.read_text(encoding="utf-8")
            parsed = parse_course_list(html, pref.url)
            rows = BeautifulSoup(html, "html.parser").select(".courselist a.row_line")
            expected = [c for c in courses if c["prefecture"] == pref.id]
            record = index["indexes"][pref.id]
            if (not parsed or len(rows) != len(parsed) or len(parsed) != len(expected)
                    or record["course_count"] != len(parsed) or record["sha256"] != digest(path)):
                raise ValueError("incomplete course list: %s" % pref.id)
            for actual, saved in zip(parsed, expected):
                if any(saved.get(key) != value for key, value in actual.items()) or not actual.get("name_ja"):
                    raise ValueError("course list accounting mismatch: %s" % pref.id)
    except (OSError, ValueError, KeyError, TypeError) as error:
        return {"ok": False, "errors": [str(error)], "warnings": [],
                **{key: counts[key] for key in ("course_count", "courses_with_map", "kml_ok",
                   "images_pending", "images_downloaded", "image_checksum_fail", "html_checksum_fail")}}

    for course in courses:
        post = course["source_post_id"]
        directory = root / "courses" / str(post)
        try:
            page = directory / "page.html"
            meta = read_json(directory / "metadata.json")
            detail = parse_course_detail(page.read_text(encoding="utf-8"), course["detail_url"])
            if meta["sha256"] != digest(page):
                counts["html_checksum_fail"] += 1
                raise ValueError("detail HTML checksum mismatch")
            if (meta["source_post_id"] != post or meta["source_url"] != course["detail_url"]
                    or not detail["title"] or meta["google_my_maps"] != detail["google_my_maps"]):
                raise ValueError("invalid detail provenance or content")
            if not detail["google_my_maps"]:
                raise ValueError("missing route map")
            counts["courses_with_map"] += 1
            kml_path = directory / "map/map.kml"
            kmeta = read_json(directory / "map/metadata.json")
            map_id = detail["google_my_maps"]["map_id"]
            if (kmeta["sha256"] != digest(kml_path) or kmeta["map_id"] != map_id
                    or kmeta["source_url"] != config.KML_ENDPOINT.format(map_id=map_id)):
                raise ValueError("KML checksum/provenance mismatch")
            kml = parse_kml(kml_path.read_bytes())
            lines = 0
            for mark in kml["placemarks"]:
                parts = _geometry_parts(mark["geometry"], "post %s" % post)
                for kind, geometry in parts:
                    positions = ([geometry["coordinates"]] if kind == "Point" else geometry["coordinates"])
                    if any(not (131 < p[0] < 136 and 31.5 < p[1] < 35.5) for p in positions):
                        raise ValueError("KML coordinate outside Shikoku")
                    lines += kind == "LineString"
            if not lines:
                raise ValueError("KML has no route geometry")
            counts["kml_ok"] += 1
            manifest = read_json(directory / "assets.json")
            assets = manifest["assets"]
            expected_urls = [image["url"] for image in detail["images"]]
            if (manifest["image_count"] != len(assets)
                    or [a["source_url"] for a in assets] != expected_urls):
                raise ValueError("image manifest/source accounting mismatch")
            for asset in assets:
                if asset["status"] != "downloaded":
                    counts["images_pending"] += 1
                    raise ValueError("image not downloaded: %s" % asset["source_url"])
                path = _inside(directory, asset["local_file"])
                if asset["sha256"] != digest(path):
                    counts["image_checksum_fail"] += 1
                    raise ValueError("image checksum mismatch: %s" % asset["local_file"])
                if image_type(path.read_bytes()) is None or path.stat().st_size != asset["size"]:
                    raise ValueError("invalid image bytes/size: %s" % asset["local_file"])
                counts["images_downloaded"] += 1
        except (OSError, ValueError, KeyError, TypeError) as error:
            errors.append("post %s: %s" % (post, error))
    return {"ok": not errors, "errors": errors, "warnings": [],
            **{key: counts[key] for key in ("course_count", "courses_with_map", "kml_ok",
               "images_pending", "images_downloaded", "image_checksum_fail", "html_checksum_fail")}}
