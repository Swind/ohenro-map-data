"""Parse the Japanese min88 lodging list without semantic normalization."""

from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup, NavigableString, Tag

LIST_URL = "https://min88.jp/inn/list_ja/"
PREFECTURES = ("tokushima", "kochi", "ehime", "kagawa")
DETAIL_URL_RE = re.compile(r"^https://min88\.jp/inn/([0-9]+)/?$")
TEMPLE_ICON_RE = re.compile(r"(?:^|/)([0-9]{2})\.png(?:[?#].*)?$")
DISTANCE_RE = re.compile(r"(?:⬇|↓)?\s*[0-9]+(?:\.[0-9]+)?\s*(?:km|ｋｍ)", re.I)
CLOSURE_MARKER = "《休業･閉業》"


def normalize_text(value: str | None) -> str | None:
    text = re.sub(r"\s+", " ", value or "").strip()
    return text or None


def extract_source_id(url: str) -> str | None:
    match = DETAIL_URL_RE.fullmatch(url or "")
    return match.group(1) if match else None


def canonical_detail_url(source_id: str) -> str:
    return f"https://min88.jp/inn/{source_id}/"


def _temple_context(header: Tag) -> dict | None:
    image = header.select_one("img")
    image_url = (image.get("data-src") or image.get("src") or "") if image else ""
    match = TEMPLE_ICON_RE.search(image_url)
    text = header.select_one(".icon-with-text-text")
    name = normalize_text(text.select_one("p").get_text(" ", strip=True)) if text and text.select_one("p") else None
    locality = normalize_text(text.select_one("small").get_text(" ", strip=True)) if text and text.select_one("small") else None
    if not match and not name:
        return None
    return {
        "number": int(match.group(1)) if match else None,
        "name": name,
        "locality": locality,
    }


def _preceding_segment(anchor: Tag) -> str:
    parts = []
    for sibling in anchor.previous_siblings:
        if isinstance(sibling, Tag) and sibling.name in ("a", "br"):
            break
        if isinstance(sibling, NavigableString):
            parts.append(str(sibling))
        elif isinstance(sibling, Tag):
            parts.append(sibling.get_text(" ", strip=True))
    return " ".join(reversed(parts))


def _link_fields(anchor: Tag) -> tuple[str | None, str | None, str | None, bool, str | None]:
    online = "route-online-inn" in (anchor.get("class") or [])
    name_node = anchor.select_one(".route-inn-name") if online else None
    name = normalize_text((name_node or anchor).get_text(" ", strip=True))
    row = anchor.find_parent(class_="route-inn-row") if online else None
    segment = _preceding_segment(anchor)
    if row:
        distance_node = row.select_one(".route-distance")
        distance = normalize_text(distance_node.get_text(" ", strip=True)) if distance_node else None
    else:
        match = DISTANCE_RE.search(segment)
        distance = normalize_text(match.group(0)) if match else None
    closure = CLOSURE_MARKER if CLOSURE_MARKER in segment else None
    badge = anchor.select_one(".route-online-badge") if online else None
    label = normalize_text(badge.get_text(" ", strip=True)) if badge else None
    return name, distance, closure, online, label


def parse_index_document(html: str, list_url: str = LIST_URL) -> dict:
    """Return deduplicated records plus all accepted link occurrences."""
    soup = BeautifulSoup(html, "html.parser")
    content = soup.select_one("#article > .post_content")
    if content is None:
        raise ValueError("missing #article > .post_content")

    prefecture = None
    temple = None
    found = []
    temple_count = 0
    records = []
    occurrences = []
    seen = set()

    for node in content.find_all(True):
        node_id = node.get("id")
        if node_id in PREFECTURES:
            prefecture = node_id
            temple = None
            if node_id not in found:
                found.append(node_id)

        if prefecture and "icon-with-text" in (node.get("class") or []):
            parsed_temple = _temple_context(node)
            if parsed_temple:
                temple = parsed_temple
                temple_count += 1

        if node.name != "a" or prefecture is None:
            continue
        absolute_url = urljoin(list_url, node.get("href") or "")
        source_id = extract_source_id(absolute_url)
        name, distance, closure, online, label = _link_fields(node)
        if source_id is None or name is None:
            continue

        source_order = len(occurrences) + 1
        occurrences.append({
            "source_id": source_id,
            "source_url": canonical_detail_url(source_id),
            "name": name,
            "prefecture": prefecture,
            "source_order": source_order,
        })
        if source_id in seen:
            continue
        seen.add(source_id)
        records.append({
            "source_id": source_id,
            "source_url": canonical_detail_url(source_id),
            "name": name,
            "prefecture": prefecture,
            "list_order": source_order,
            "temple_context": dict(temple) if temple else None,
            "distance_text": distance,
            "closure_marker": closure,
            "online_booking": online,
            "online_booking_label": label,
        })

    missing = [item for item in PREFECTURES if item not in found]
    if missing:
        raise ValueError("missing prefecture sections: " + ", ".join(missing))
    if not records:
        raise ValueError("no valid lodging links")
    return {
        "records": records,
        "occurrences": occurrences,
        "prefectures_found": found,
        "temple_header_count": temple_count,
    }


def parse_index(html: str, list_url: str = LIST_URL) -> list[dict]:
    """Return source-ordered lodging records, deduplicated by post ID."""
    return parse_index_document(html, list_url)["records"]
