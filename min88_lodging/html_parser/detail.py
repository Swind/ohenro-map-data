"""Offline extraction of min88 lodging detail HTML."""

import copy
import re
import unicodedata
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from min88_lodging.model.raw import RawMin88Lodging


KNOWN_BASIC_DATA_KEYS = {
    "address", "tel", "website", "email", "parking", "rooms", "price",
    "checkin", "checkout", "wifi", "laundry", "payment", "emoney",
}
LEGACY_BASIC_DATA_LABELS = {
    "住所": "address", "TEL": "tel", "駐車場": "parking", "部屋数": "rooms",
    "料金": "price", "HP": "website", "IN": "checkin", "OUT": "checkout",
    "WiFi": "wifi", "ランドリー": "laundry", "支払い方法": "payment",
}
SOURCE_ID_RE = re.compile(r"/inn/(?:[a-z]{2}/)?([0-9]+)/?$")
GOOGLE_MAPS_HOSTS = {"www.google.com", "maps.google.com", "www.google.co.jp", "maps.google.co.jp"}
FORBIDDEN_SECTION_RE = re.compile(r"review|レビュー|口コミ|advert|広告|affiliate|widget", re.I)
SECTION_TITLES = {
    "host": {"ホストよりご挨拶", "オーナーよりご挨拶", "Greetings from the owner"},
    "reviews": {"利用者の声", "ゲストレビュー", "User reviews"},
    "basic": {"基本情報"},
    "photo": {"写真ツアー"},
    "website": {"WEBSITE"},
    "map": {"MAP"},
    "supplemental": {"補足情報"},
    "gallery": {"投稿画像"},
}


def _text(element):
    if element is None:
        return None
    clone = copy.deepcopy(element)
    for br in clone.find_all("br"):
        br.replace_with("\n")
    value = clone.get_text().replace("\xa0", " ")
    value = re.sub(r"[ \t\r\f\v]+", " ", value)
    value = re.sub(r" *\n *", "\n", value)
    value = re.sub(r"\n{2,}", "\n", value).strip()
    return value or None


def _url(base, value):
    if not value or value.startswith("data:"):
        return None
    return urljoin(base, value)


def _warning(field, code, message, raw_value=None):
    return {"field": field, "code": code, "message": message, "raw_value": raw_value}


def _normalized_label(value):
    value = unicodedata.normalize("NFKC", value or "").casefold()
    return "".join(char for char in value if not char.isspace() and not unicodedata.category(char).startswith("P"))


NORMALIZED_SECTION_TITLES = {
    kind: {_normalized_label(title) for title in titles}
    for kind, titles in SECTION_TITLES.items()
}


def _section_kind(heading):
    for candidate in (_text(heading), heading.get("id")):
        normalized = _normalized_label(candidate)
        for kind, titles in NORMALIZED_SECTION_TITLES.items():
            if normalized in titles:
                return kind
    return None


def _section_siblings(heading):
    for sibling in heading.find_next_siblings():
        if sibling.name and re.fullmatch(r"h[1-6]", sibling.name):
            break
        yield sibling


def _source_id(url):
    if not url:
        return None
    match = SOURCE_ID_RE.search(urlparse(url).path)
    return match.group(1) if match else None


def _source_context(index_context):
    context = dict(index_context or {})
    if "name" in context and "list_name" not in context:
        context["list_name"] = context.pop("name")
    return context


def _basic_data(article, warnings):
    values = {}
    ignored = []
    extra = []
    textarea = article.select_one(".min88-basicdata-pack > textarea.min88-basicdata-kv")
    if textarea is None:
        content = article.select_one(".post_content")
        heading = next((item for item in content.find_all(re.compile(r"^h[1-6]$"))
                        if _section_kind(item) == "basic"), None) if content else None
        table = heading.find_next("table") if heading else None
        if table:
            for row in table.select("tr"):
                cells = row.find_all(["th", "td"], recursive=False)
                if len(cells) < 2:
                    continue
                key = LEGACY_BASIC_DATA_LABELS.get(_text(cells[0]))
                value = _text(cells[1])
                if key and value is not None:
                    values[key] = value
        if not values:
            warnings.append(_warning("basic_data", "MISSING_REQUIRED_FIELD", "Basic-data source is missing."))
        return values, ignored, extra

    for raw_line in textarea.get_text().splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#") or "=" not in line:
            ignored.append(line)
            continue
        key, value = (part.strip() for part in line.split("=", 1))
        if key not in KNOWN_BASIC_DATA_KEYS:
            extra.append({"key": key, "value": value, "reason": "unknown"})
            warnings.append(_warning("basic_data." + key, "UNKNOWN_BASIC_DATA_KEY", "Unknown basic-data key retained.", value))
        elif key in values:
            extra.append({"key": key, "value": value, "reason": "duplicate"})
            warnings.append(_warning("basic_data." + key, "DUPLICATE_BASIC_DATA_KEY", "Duplicate basic-data key retained; first value used.", value))
        else:
            values[key] = value
    return values, ignored, extra


def _gallery_images(article, base_url):
    images = []
    content = article.select_one(".post_content")
    if content:
        for heading in content.find_all(re.compile(r"^h[1-6]$"), recursive=False):
            if _section_kind(heading) not in {"gallery", "photo"}:
                continue
            for sibling in _section_siblings(heading):
                if "（まだありません）" in (sibling.get_text() or ""):
                    continue
                for image in sibling.select(".wp-block-image img, .wp-block-gallery img, img"):
                    url = _url(base_url, image.get("data-src") or image.get("src"))
                    if url and url not in images:
                        images.append(url)
    return images


def _maps(article, base_url):
    place = street = directions = None
    for iframe in article.select("iframe[data-src], iframe[src]"):
        url = _url(base_url, iframe.get("data-src") or iframe.get("src"))
        if not url or urlparse(url).hostname not in GOOGLE_MAPS_HOSTS or "/maps/" not in urlparse(url).path:
            continue
        if "!6m8" in url or "/streetview" in url or "map_action=pano" in url:
            street = street or url
        elif "/maps/embed" in url:
            place = place or url
    for anchor in article.select("a[href]"):
        url = _url(base_url, anchor.get("href"))
        if url and urlparse(url).hostname in GOOGLE_MAPS_HOSTS and "/maps/dir/" in urlparse(url).path:
            directions = url
            break
    return place, street, directions


def _content_sections(article, base_url, warnings):
    known_sections = []
    unknown_sections = []
    content = article.select_one(".post_content")
    if content is None:
        return known_sections, unknown_sections
    for heading in content.find_all(re.compile(r"^h[1-6]$"), recursive=False):
        title = _text(heading)
        kind = _section_kind(heading)
        identity = " ".join(filter(None, (heading.get("id"), " ".join(heading.get("class") or []), title)))
        if kind in {"reviews", "basic", "map", "supplemental", "gallery"} or FORBIDDEN_SECTION_RE.search(identity):
            continue
        siblings = []
        for sibling in _section_siblings(heading):
            sibling_identity = " ".join((sibling.get("id") or "", " ".join(sibling.get("class") or [])))
            if not FORBIDDEN_SECTION_RE.search(sibling_identity):
                siblings.append(sibling)
        text = "\n".join(filter(None, (_text(item) for item in siblings))) or None
        links = [_url(base_url, link.get("href")) for item in siblings
                 for link in item.find_all("a", href=True, recursive=True) + ([item] if item.name == "a" and item.get("href") else [])]
        images = [_url(base_url, image.get("data-src") or image.get("src")) for item in siblings
                  for image in item.find_all("img", recursive=True) + ([item] if item.name == "img" else [])]
        section = {"heading": title, "text": text,
                    "links": [url for url in links if url], "image_urls": [url for url in images if url]}
        if kind in {"host", "photo", "website"}:
            known_sections.append({"kind": kind, **section})
        else:
            unknown_sections.append(section)
            warnings.append(_warning("unknown_sections", "UNKNOWN_CONTENT_SECTION", "Unknown content section retained.", title))
    return known_sections, unknown_sections


def parse_detail_html(html, index_context):
    """Parse one archived detail page using its index record as context."""
    soup = BeautifulSoup(html, "html.parser")
    article = soup.select_one("#article")
    context = _source_context(index_context)
    source_url = context.get("source_url") or "https://min88.jp/"
    warnings = []

    canonical = soup.select_one('link[rel="canonical"][href]')
    canonical_url = _url(source_url, canonical.get("href")) if canonical else None
    canonical_source_id = _source_id(canonical_url)
    expected_id = str(context["source_id"]) if context.get("source_id") is not None else None
    if expected_id and canonical_source_id and expected_id != canonical_source_id:
        warnings.append(_warning("source_context.source_id", "SOURCE_ID_MISMATCH", "Canonical and index source IDs differ.", canonical_source_id))

    if article is None:
        warnings.append(_warning("article", "MISSING_REQUIRED_FIELD", "Detail article is missing."))
        article = BeautifulSoup("<div></div>", "html.parser").div

    name = _text(article.select_one("h1#post_title"))
    if name is None:
        warnings.append(_warning("name", "MISSING_REQUIRED_FIELD", "Detail title is missing."))
    list_name = context.get("list_name")
    if name and list_name and _normalized_label(name) != _normalized_label(list_name):
        warnings.append(_warning("name", "SOURCE_NAME_MISMATCH", "Detail and index names differ.", name))

    categories = [_text(a) for a in article.select("#post_meta_top a.cat-category")]
    lodging_types = [_text(a) for a in article.select("#post_meta_top a.cat-category2")]
    categories = [value for value in categories if value]
    lodging_types = [value for value in lodging_types if value]

    route_lines = []
    for line in article.select("#route-lines .route-line"):
        route_lines.append({key: line.get("data-" + key) for key in ("lnum", "lname", "lkm", "rnum", "rname", "rkm")})

    basic_data, ignored, extra = _basic_data(article, warnings)
    facilities = [_text(li) for li in article.select("h3#補足情報 + ul.wp-block-list > li")]
    facilities = [value for value in facilities if value]
    editorial_title = _text(article.select_one(".min88-inn-intro__title"))
    editorial_parts = [_text(el) for el in article.select(".min88-inn-intro__text")]
    editorial_description = "\n".join(value for value in editorial_parts if value) or None

    og_image = soup.select_one('meta[property="og:image"][content]')
    display_image = article.select_one("#post_image img.wp-post-image, #post_image img")
    display_featured = _url(source_url, display_image.get("data-src") or display_image.get("src")) if display_image else None
    featured = _url(source_url, og_image.get("content")) if og_image else None
    if featured is None:
        featured = display_featured

    place, street, directions = _maps(article, source_url)
    content_sections, unknown_sections = _content_sections(article, source_url, warnings)
    alternates = []
    for link in soup.select('head link[rel="alternate"][hreflang][href]'):
        url = _url(source_url, link.get("href"))
        alternates.append({"language": link.get("hreflang"), "source_id": _source_id(url), "url": url})

    return RawMin88Lodging(
        source_context=context,
        canonical_source_id=canonical_source_id,
        canonical_url=canonical_url,
        name=name,
        modified_text=_text(article.select_one(".post-modified-info")),
        categories=categories,
        lodging_types=lodging_types,
        route_lines=route_lines,
        basic_data=basic_data,
        basic_data_ignored_lines=ignored,
        extra_fields=extra,
        supplemental_facilities=facilities,
        editorial_title=editorial_title,
        editorial_description=editorial_description,
        featured_image_url=featured,
        featured_image_display_url=display_featured,
        gallery_image_urls=_gallery_images(article, source_url),
        google_maps_place_embed_url=place,
        google_street_view_embed_url=street,
        google_maps_directions_url=directions,
        alternate_languages=alternates,
        content_sections=content_sections,
        unknown_sections=unknown_sections,
        parser_warnings=warnings,
    )


parse_detail = parse_detail_html
extract_detail = parse_detail_html
