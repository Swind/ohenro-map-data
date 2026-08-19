"""Shared configuration: prefecture sources, constants, and directory layout.

The plan (reference/shikoku-nature-trail-crawler-plan.md) requires URLs to be
centralized here rather than scattered as hardcoded strings.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE_DIR = os.path.join(ROOT, "source")
REPORTS_DIR = os.path.join(ROOT, "reports")

DEFAULT_DATA_DIR = os.path.join(SOURCE_DIR, "shikoku-nature-trail")

USER_AGENT = "ShikokuNatureTrailArchiver/0.1 (ohenro-map-data; python)"
DEFAULT_TIMEOUT = 30
DEFAULT_CONCURRENCY = 3
DEFAULT_DELAY = 0.3
MAX_ATTEMPTS = 4
BACKOFF_SECONDS = [1, 2, 4, 8]

RETRYABLE_STATUS = {429, 500, 502, 503, 504}

SCHEMA_VERSION = 1

SCHEMA_JSON_FILENAME = "course-index.json"
MANIFEST_FILENAME = "manifest.json"
STATE_FILENAME = "crawl-state.json"

KML_ENDPOINT = "https://www.google.com/maps/d/kml?mid={map_id}&forcekml=1"


@dataclass(frozen=True)
class PrefectureSource:
    id: str
    name_ja: str
    url: str


PREFECTURES = [
    PrefectureSource("tokushima", "徳島", "https://shikoku-nature-trail.com/courselist_tokushima"),
    PrefectureSource("kagawa", "香川", "https://shikoku-nature-trail.com/courselist_kagawa"),
    PrefectureSource("ehime", "愛媛", "https://shikoku-nature-trail.com/courselist_ehime"),
    PrefectureSource("kochi", "高知", "https://shikoku-nature-trail.com/courselist_kochi"),
]


def data_layout(data_dir: str) -> dict:
    """Return the fixed paths for the raw archive under data_dir."""
    return {
        "indexes": os.path.join(data_dir, "indexes"),
        "courses": os.path.join(data_dir, "courses"),
        "schema": os.path.join(data_dir, SCHEMA_JSON_FILENAME),
        "manifest": os.path.join(data_dir, MANIFEST_FILENAME),
        "state": os.path.join(data_dir, STATE_FILENAME),
    }


def course_dir(data_dir: str, post_id) -> str:
    return os.path.join(data_dir, "courses", str(post_id))


def index_path(data_dir: str, pref_id: str) -> str:
    return os.path.join(data_dir, "indexes", pref_id + ".html")


def report_paths() -> tuple[str, str]:
    return (
        os.path.join(REPORTS_DIR, "shikoku-nature-trail-crawl-report.json"),
        os.path.join(REPORTS_DIR, "shikoku-nature-trail-crawl-report.md"),
    )