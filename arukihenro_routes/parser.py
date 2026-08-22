"""Small HTML extractors for the stable WordPress page structure."""

from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import parse_qs, urljoin, urlparse


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
        self.map_urls: list[str] = []
        self.title_parts: list[str] = []
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "a" and values.get("href"):
            self.links.append(values["href"])
        elif tag == "iframe" and values.get("src"):
            self.map_urls.append(values["src"])
        elif tag == "h1" and "entry-title" in (values.get("class") or "").split():
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "h1":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)


def parse_index(html: str, page_url: str) -> list[str]:
    """Return unique walking-route links in their source order."""
    parser = _PageParser()
    parser.feed(html)
    routes = []
    for href in parser.links:
        url = urljoin(page_url, href)
        if "/blog/arukihenro/junnro/michi" in url and url not in routes:
            routes.append(url)
    return routes


def parse_route(html: str, page_url: str) -> dict:
    """Extract display title and My Maps embeds without interpreting page prose."""
    parser = _PageParser()
    parser.feed(html)
    maps = []
    for src in parser.map_urls:
        url = urljoin(page_url, src)
        mid = parse_qs(urlparse(url).query).get("mid", [None])[0]
        if mid and mid not in {item["map_id"] for item in maps}:
            maps.append({"embed_url": url, "map_id": mid, "kml_url": "https://www.google.com/maps/d/kml?mid=%s&forcekml=1" % mid})
    return {"title": "".join(parser.title_parts).strip() or None, "maps": maps}
