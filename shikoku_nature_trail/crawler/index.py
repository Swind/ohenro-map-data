"""Stage 1/2: download the four prefecture course lists and build the index.

Saves indexes/{pref}.html (raw HTML first, parse second) plus the combined
course-index.json (plan §9/§10).
"""

from __future__ import annotations

import logging
import os

from shikoku_nature_trail import config
from shikoku_nature_trail.http import HttpClient
from shikoku_nature_trail.parser.course_list import parse_course_list
from shikoku_nature_trail.storage import (
    atomic_write_bytes,
    atomic_write_json,
    local_now,
    sha256_bytes,
    sha256_file,
)

logger = logging.getLogger(__name__)


def crawl_index(client: HttpClient, data_dir: str, force: bool = False):
    """Download four list pages, parse courses, write course-index.json."""
    layout = config.data_layout(data_dir)
    os.makedirs(layout["indexes"], exist_ok=True)

    all_courses = []
    index_records = {}
    failures = []

    for pref in config.PREFECTURES:
        dest = config.index_path(data_dir, pref.id)
        if os.path.exists(dest) and not force:
            logger.info("skip existing index %s (use --force to refetch)", dest)
            with open(dest, "rb") as f:
                raw = f.read()
        else:
            logger.info("fetching course list: %s (%s)", pref.id, pref.url)
            status, _headers, body = client.get_bytes(pref.url)
            if status != 200:
                failures.append({"url": pref.url, "status": status, "step": "index"})
                logger.error("failed to fetch list %s: HTTP %s", pref.id, status)
                continue
            raw = body
            atomic_write_bytes(dest, raw)

        courses = parse_course_list(raw.decode("utf-8", errors="replace"), pref.url)
        for c in courses:
            c["prefecture"] = pref.id
            c["pref_name_ja"] = pref.name_ja
            c["index_file"] = os.path.relpath(dest, data_dir)
        all_courses.extend(courses)
        index_records[pref.id] = {
            "url": pref.url,
            "file": os.path.relpath(dest, data_dir),
            "sha256": sha256_file(dest),
            "course_count": len(courses),
        }
        logger.info("discovered %d courses for %s", len(courses), pref.id)

    schema = {
        "schema_version": config.SCHEMA_VERSION,
        "source": "shikoku-nature-trail.com",
        "generated_at": local_now(),
        "indexes": index_records,
        "course_count": len(all_courses),
        "courses": all_courses,
    }
    atomic_write_json(layout["schema"], schema)
    logger.info("wrote %s (%d courses)", layout["schema"], len(all_courses))
    return {"course_count": len(all_courses), "indexes": index_records, "failures": failures}