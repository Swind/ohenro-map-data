"""Parse a course detail page.

Phase 1 fields (title, map and images) remain unchanged. Phase 2 additionally
extracts the archived introduction, photo point and nearby tourism spots.

Image selection: only images hosted under the WordPress uploads directory
(`/wp-content/uploads/`) are content images. Theme chrome (icons, logos,
dots, banners under `/wp-content/themes/`) is excluded, matching the plan's
"exclude theme/logo/decoration" requirement. A hero background-image URL on
`section.pageHero` is also captured.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

MAPS_EMBED_RE = re.compile(r"google\.com/maps/d/(?:u/\d+/)?(?:embed|viewer)")
UPLOADS_PREFIX = "/wp-content/uploads/"
THEMES_PREFIX = "/wp-content/themes/"
IGNORE_EXTENSIONS = {".svg", ".gif"}


def _map_id_from_src(src: str):
    parsed = urlparse(src)
    qs = parse_qs(parsed.query)
    values = qs.get("mid")
    return values[0] if values else None


def _is_content_image(src: str) -> bool:
    path = urlparse(src).path
    if THEMES_PREFIX in path:
        return False
    if UPLOADS_PREFIX not in path:
        return False
    ext = src.rsplit(".", 1)[-1].lower() if "." in src.rsplit("/", 1)[-1] else ""
    return ext not in IGNORE_EXTENSIONS


def _text(node):
    """Conservatively collapse HTML layout whitespace without changing text."""
    if node is None:
        return None
    return " ".join(node.get_text(" ", strip=True).split()) or None


def parse_course_detail(html: str, source_url: str):
    """Return normalized content and Phase 1 download fields for a detail page."""
    soup = BeautifulSoup(html, "html.parser")

    title = None
    h1 = soup.find("h1")
    if h1 is not None:
        title = _text(h1)

    about = soup.select_one(".sectionAbout .map-content .wrap")
    description = _text(about.find("p")) if about else None

    photo = soup.select_one(".photo-point")
    photo_point = None
    if photo is not None:
        photo_point = {
            "title": _text(photo.select_one(".sub-title")),
            "description": _text(photo.find("p")),
        }

    tourism_spots = []
    for item in soup.select(".sectionSpot .number-list > li"):
        image = item.find("img")
        image_url = urljoin(source_url, image.get("src")) if image and image.get("src") else None
        tourism_spots.append({
            "number": _text(item.select_one(".midashi")),
            "title": _text(item.select_one(".title")),
            "description": _text(item.find("p")),
            "image_url": image_url,
        })

    map_info = None
    for iframe in soup.find_all("iframe"):
        src = iframe.get("src") or ""
        if "google.com/maps/d/" in src and "mid=" in src:
            map_id = _map_id_from_src(src)
            if map_id:
                map_info = {"map_id": map_id, "embed_url": urljoin(source_url, src)}
                break
    if map_info is None:
        # fallback: any anchor linking to a maps/d viewer with a mid param
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "google.com/maps/d/" in href and "mid=" in href:
                map_id = _map_id_from_src(href)
                if map_id:
                    map_info = {"map_id": map_id, "embed_url": urljoin(source_url, href)}
                    break

    seen = set()
    images = []
    for img in soup.find_all("img"):
        src = img.get("src") or ""
        full = urljoin(source_url, src)
        if full in seen or not _is_content_image(full):
            continue
        seen.add(full)
        images.append({"url": full})

    # hero background-image on section.pageHero (inline style url(...))
    hero = soup.select_one("section.pageHero")
    if hero is not None:
        style = hero.get("style") or ""
        m = re.search(r"url\(\s*['\"]?([^'\")]+)['\"]?\s*\)", style)
        if m:
            full = urljoin(source_url, m.group(1).strip())
            if full not in seen and _is_content_image(full):
                seen.add(full)
                images.append({"url": full})

    return {
        "title": title,
        "description": description,
        "photo_point": photo_point,
        "tourism_spots": tourism_spots,
        "google_my_maps": map_info,
        "images": images,
    }
