"""Cached Google Maps place enrichment adapter for min88 V1 dicts."""

import hashlib
import json
import os
import re
import time
import urllib.parse
import urllib.request

from henroyado.geocode import PLACE_RE, embed_url, parse_place
from min88_lodging.model.v1 import (JAPANESE_PREFECTURE_RE, SHIKOKU_POLYGON,
                                    SHIKOKU_PREFECTURES)


USER_AGENT = "ohenro-map-data/min88-lodging"
GOOGLE_MAPS_HOSTS = {"www.google.com", "maps.google.com", "www.google.co.jp", "maps.google.co.jp"}
PLACE_PROVENANCE_KEYS = (
    "google_maps_place_id", "google_maps_cid", "google_maps_place_name",
    "google_maps_place_address", "google_maps_geocode_url",
)


def search_url(name, address):
    query = " ".join(value for value in (name, address) if value)
    return "https://www.google.com/maps?q=" + urllib.parse.quote_plus(query)


def parse_place_result(content, final_url=None):
    """Return (place, ambiguous), accepting records and explicit !8m2 markers only."""
    matches = list(PLACE_RE.finditer(content or ""))
    identities = {(match.group("place_id"), match.group("latitude"), match.group("longitude"))
                  for match in matches}
    if len(identities) > 1:
        return None, True
    return parse_place(content or "", final_url), False


def _require_google_maps_url(url):
    hostname = urllib.parse.urlsplit(url).hostname
    if hostname not in GOOGLE_MAPS_HOSTS:
        raise ValueError("Google Maps URL host is not allowed: %s" % (hostname or "<missing>"))


def fetch_place(request_url, cache_dir, timeout=30, force=False, opener=urllib.request.urlopen):
    _require_google_maps_url(request_url)
    url = embed_url(request_url)
    _require_google_maps_url(url)
    path = os.path.join(cache_dir, hashlib.sha256(url.encode("utf-8")).hexdigest() + ".html")
    final_url_path = path + ".url"
    if os.path.exists(path) and os.path.exists(final_url_path) and not force:
        with open(final_url_path, encoding="utf-8") as handle:
            final_url = handle.read().strip()
        _require_google_maps_url(final_url)
        with open(path, encoding="utf-8") as handle:
            content = handle.read()
        place, ambiguous = parse_place_result(content, final_url)
        return place, ambiguous, url, True
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with opener(request, timeout=timeout) as response:
        final_url = response.geturl()
        _require_google_maps_url(final_url)
        content = response.read().decode("utf-8", errors="replace")
    os.makedirs(cache_dir, exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        handle.write(content)
    os.replace(temporary, path)
    if final_url:
        temporary = final_url_path + ".tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            handle.write(final_url)
        os.replace(temporary, final_url_path)
    place, ambiguous = parse_place_result(content, final_url)
    return place, ambiguous, url, False


def _warn(record, code, message, raw_value):
    record.setdefault("_warnings", []).append({"field": "location.coordinates", "code": code,
                                                "message": message, "raw_value": raw_value})


def _in_polygon(latitude, longitude):
    inside = False
    previous = SHIKOKU_POLYGON[-1]
    for current in SHIKOKU_POLYGON:
        x1, y1 = previous
        x2, y2 = current
        if ((y1 > latitude) != (y2 > latitude) and
                longitude < (x2 - x1) * (latitude - y1) / (y2 - y1) + x1):
            inside = not inside
        previous = current
    return inside


def is_shikoku_place(place, source_address=None):
    """Prefer Google prefecture evidence; use source evidence and polygon as fallback."""
    google_prefecture = re.search(JAPANESE_PREFECTURE_RE, place.get("address") or "")
    if google_prefecture:
        return google_prefecture.group(0) in SHIKOKU_PREFECTURES
    source_prefecture = re.search(JAPANESE_PREFECTURE_RE, source_address or "")
    if source_prefecture and source_prefecture.group(0) not in SHIKOKU_PREFECTURES:
        return False
    return _in_polygon(place["latitude"], place["longitude"])


def enrich_record(record, cache_dir, timeout=30, force=False, fetcher=fetch_place):
    """Enrich one V1 dict in place, trying source embed then name/address search."""
    location = record["location"]
    location["coordinates"] = None
    for key in PLACE_PROVENANCE_KEYS:
        location.pop(key, None)
    requests = []
    if location.get("google_maps_place_embed_url"):
        requests.append(location["google_maps_place_embed_url"])
    name = (record.get("identity") or {}).get("name")
    address = location.get("address")
    if name and address:
        fallback = search_url(name, address)
        if fallback not in requests:
            requests.append(fallback)
    if not requests:
        location["map_data_status"] = "source_data_incomplete"
        return "no_request", True

    any_uncached = False
    failures = []
    for request_url in requests:
        try:
            place, ambiguous, actual_url, cached = fetcher(request_url, cache_dir, timeout=timeout, force=force)
            any_uncached |= not cached
        except Exception as exc:
            failures.append("fetch_failed")
            _warn(record, "GOOGLE_MAPS_FETCH_FAILED", str(exc), request_url)
            continue
        if ambiguous:
            failures.append("place_ambiguous")
            _warn(record, "GOOGLE_MAPS_PLACE_AMBIGUOUS", "Embed response contained multiple places.", request_url)
            continue
        if place is None:
            failures.append("place_not_found")
            continue
        if not is_shikoku_place(place, address):
            failures.append("place_outside_shikoku")
            _warn(record, "GOOGLE_MAPS_PLACE_OUTSIDE_SHIKOKU", "Google place is outside Shikoku.", place)
            continue
        location.update({
            "coordinates": {"latitude": place["latitude"], "longitude": place["longitude"],
                            "source": "google_maps_embed_place"},
            "map_data_status": "resolved", "google_maps_place_id": place.get("place_id"),
            "google_maps_cid": place.get("cid"), "google_maps_place_name": place.get("name"),
            "google_maps_place_address": place.get("address"), "google_maps_geocode_url": actual_url,
        })
        return "resolved", not any_uncached

    location["map_data_status"] = next(
        status for status in ("fetch_failed", "place_ambiguous", "place_outside_shikoku", "place_not_found")
        if status in failures
    )
    code = {"place_not_found": "GOOGLE_MAPS_PLACE_NOT_FOUND"}.get(location["map_data_status"])
    if code:
        _warn(record, code, "No single Google place was found.", requests[-1])
    return location["map_data_status"], not any_uncached


def enrich_file(input_path, output_path, cache_dir, timeout=30, delay=0.3, force=False,
                fetcher=fetch_place):
    stats = {"records": 0, "geocoded": 0, "no_request": 0, "not_found": 0, "errors": 0}
    records = []
    with open(input_path, encoding="utf-8") as handle:
        records = [json.loads(line) for line in handle if line.strip()]
    for record in records:
        stats["records"] += 1
        fetch_warnings = sum(warning.get("code") == "GOOGLE_MAPS_FETCH_FAILED"
                             for warning in record.get("_warnings", []))
        status, cached = enrich_record(record, cache_dir, timeout=timeout, force=force, fetcher=fetcher)
        if sum(warning.get("code") == "GOOGLE_MAPS_FETCH_FAILED"
               for warning in record.get("_warnings", [])) > fetch_warnings:
            stats["errors"] += 1
        if status == "resolved":
            stats["geocoded"] += 1
        elif status == "no_request":
            stats["no_request"] += 1
        elif status != "fetch_failed":
            stats["not_found"] += 1
        if not cached and delay:
            time.sleep(delay)
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    temporary = output_path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    os.replace(temporary, output_path)
    return stats
