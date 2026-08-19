"""Parse a course detail page.

Phase 1 extracts only what's needed to download assets plus easy-to-spot
fields (plan §12/§13): title, Google My Maps map id / embed URL, and content
image URLs. Full description / 撮影ポイント / 観光 SPOT parsing is deferred to
phase 2 — the raw HTML is already archived.

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


def parse_course_detail(html: str, source_url: str):
    """Return {title, google_my_maps, images} for a course detail page."""
    soup = BeautifulSoup(html, "html.parser")

    title = None
    h1 = soup.find("h1")
    if h1 is not None:
        title = h1.get_text(" ", strip=True) or None

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
        "google_my_maps": map_info,
        "images": images,
    }