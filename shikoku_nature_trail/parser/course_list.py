"""Parse the per-prefecture course list pages.

The live page uses a div-based "table" (`.courselist`) instead of a real
<table>. Each row is an `<a class="row_line">` whose children are `.cel`
cells. Column semantics come from the `.head` header row: we read the header
cells, map each header label to a column class (cel1..cel7), then assign row
cells by class. This is robust to column reordering.

Plan §10/§33: primary selector `.courselist`, fallback header-driven mapping,
WARN instead of silent ignore when a known column is missing.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

POST_ID_RE = re.compile(r"/archives/(\d+)")
CELL_CLASS_RE = re.compile(r"^cel\d+$")

# Header label -> canonical field key (used to build class->key mapping).
HEADER_LABELS = {
    "コース名": "name_ja",
    "特徴": "features",
    "場所": "location_raw",
    "距離": "distance_raw",
    "区間": "section_raw",
    "難易度": "difficulty_raw",
}

# Column class -> field key when header text is unavailable or empty (cel1).
CLASS_DEFAULTS = {
    "cel1": "course_number",
    "cel2": "name_ja",
    "cel3": "location_raw",
    "cel4": "distance_raw",
    "cel5": "section_raw",
    "cel6": "difficulty_raw",
    "cel7": "features",
}

DISTANCE_RE = re.compile(r"([\d.]+)\s*(?:km|ｋｍ)", re.IGNORECASE)


def extract_post_id(detail_url: str):
    m = POST_ID_RE.search(detail_url or "")
    return int(m.group(1)) if m else None


def _parse_difficulty(text):
    """'★★☆' -> 2, '★☆☆' -> 1, '★★★' -> 3. None if no stars."""
    stars = (text or "").count("★")
    return stars or None


def _parse_distance(text):
    m = DISTANCE_RE.search(text or "")
    return float(m.group(1)) if m else None


def _row_features(cell):
    """Features are genre icons (`img.alt` inside .g_img). Returns list of alts."""
    features = []
    for img in cell.select("img[alt]"):
        alt = img.get("alt", "").strip()
        if alt:
            features.append(alt)
    return features


def parse_course_list(html: str, list_url: str):
    """Parse a course list page into a list of course index dicts.

    Args:
        html: raw HTML of the list page.
        list_url: the list page URL (for resolving relative detail links).

    Returns:
        list[dict] with keys per plan §7.
    """
    soup = BeautifulSoup(html, "html.parser")
    container = soup.select_one(".courselist")
    if container is None:
        logger.warning("no .courselist container found in list page %s", list_url)
        return []

    head = container.select_one(".head")
    class_to_key = dict(CLASS_DEFAULTS)
    if head is not None:
        for cell in head.select(".cel"):
            classes = cell.get("class") or []
            col = next((c for c in classes if CELL_CLASS_RE.match(c)), None)
            label = cell.get_text(" ", strip=True)
            if col and label in HEADER_LABELS:
                class_to_key[col] = HEADER_LABELS[label]

    rows = container.select("a.row_line")
    courses = []
    for row in rows:
        href = row.get("href", "")
        detail_url = urljoin(list_url, href)
        post_id = extract_post_id(detail_url)
        if post_id is None:
            logger.warning("row without /archives/<id> link: %s", href)
            continue

        entry = {
            "source_post_id": post_id,
            "detail_url": detail_url,
        }
        for cell in row.select(".cel"):
            classes = cell.get("class") or []
            col = next((c for c in classes if CELL_CLASS_RE.match(c)), None)
            key = class_to_key.get(col)
            if key is None:
                continue
            if key == "features":
                value = _row_features(cell)
            else:
                value = cell.get_text(" ", strip=True) or None
            entry[key] = value

        entry.setdefault("name_ja", None)
        entry["difficulty"] = _parse_difficulty(entry.get("difficulty_raw"))
        entry["distance_km"] = _parse_distance(entry.get("distance_raw"))
        courses.append(entry)

    return courses