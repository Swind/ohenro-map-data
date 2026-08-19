"""Google Maps place enrichment through the public embed response."""

import hashlib
import json
import os
import re
import time
import urllib.parse
import urllib.request

from henroyado.fetcher.fetcher import USER_AGENT
from henroyado.normalize.map import parse_coordinates


PLACE_RE = re.compile(
    r'\[\["(?P<place_id>0x[0-9a-f]+:0x[0-9a-f]+)",'
    r'(?P<address>"(?:\\.|[^"\\])*")'
    r',\[(?P<latitude>-?\d+(?:\.\d+)?),(?P<longitude>-?\d+(?:\.\d+)?)\],'
    r'"(?P<cid>\d+)"\],(?P<name>"(?:\\.|[^"\\])*")'
)


def is_in_shikoku(place):
    return (32.0 <= place["latitude"] <= 35.0 and
            131.0 <= place["longitude"] <= 135.5)


def embed_url(search_url):
    """Return the search URL configured for a Japanese embed response."""
    parsed = urllib.parse.urlsplit(search_url)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query = [(key, value) for key, value in query if key not in ("output", "hl")]
    query.extend((("output", "embed"), ("hl", "ja")))
    return urllib.parse.urlunsplit((
        "https", parsed.netloc, parsed.path, urllib.parse.urlencode(query), ""
    ))


def parse_place(content, final_url=None):
    """Extract one Google place record, never a map viewport coordinate."""
    match = PLACE_RE.search(content)
    if match:
        return {
            "latitude": float(match.group("latitude")),
            "longitude": float(match.group("longitude")),
            "place_id": match.group("place_id"),
            "cid": match.group("cid"),
            "name": json.loads(match.group("name")),
            "address": json.loads(match.group("address")),
        }

    coordinates = parse_coordinates(final_url)
    if coordinates:
        return {
            "latitude": coordinates["latitude"],
            "longitude": coordinates["longitude"],
            "place_id": None,
            "cid": None,
            "name": None,
            "address": None,
        }
    return None


def fetch_place(search_url, cache_dir, timeout=30, force=False):
    """Fetch/cache an embed response and return its parsed place record."""
    url = embed_url(search_url)
    key = hashlib.sha256(url.encode("utf-8")).hexdigest()
    path = os.path.join(cache_dir, key + ".html")
    if os.path.exists(path) and not force:
        with open(path, encoding="utf-8") as f:
            return parse_place(f.read()), url, True

    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        content = response.read().decode("utf-8", errors="replace")
        final_url = response.geturl()
    os.makedirs(cache_dir, exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as f:
        f.write(content)
    os.replace(temporary, path)
    return parse_place(content, final_url), url, False


def enrich_file(input_path, output_path, cache_dir, timeout=30, delay=0.3,
                force=False):
    """Enrich V1 JSONL locations and return processing counters."""
    stats = {"records": 0, "geocoded": 0, "no_url": 0, "not_found": 0, "errors": 0}
    records = []
    with open(input_path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))

    for record in records:
        stats["records"] += 1
        location = record["location"]
        search_url = location.get("google_maps_search_url")
        if not search_url:
            stats["no_url"] += 1
            continue
        try:
            place, request_url, cached = fetch_place(
                search_url, cache_dir, timeout=timeout, force=force
            )
            if not cached and delay:
                time.sleep(delay)
        except Exception as exc:
            stats["errors"] += 1
            location["map_data_status"] = "fetch_failed"
            record["_warnings"].append({
                "field": "location.coordinates",
                "code": "GOOGLE_MAPS_FETCH_FAILED",
                "message": str(exc),
                "raw_value": search_url,
            })
            continue
        if place is None:
            stats["not_found"] += 1
            location["map_data_status"] = "place_not_found"
            record["_warnings"].append({
                "field": "location.coordinates",
                "code": "GOOGLE_MAPS_PLACE_NOT_FOUND",
                "message": "Embed response did not contain a Google place record.",
                "raw_value": search_url,
            })
            continue
        if not is_in_shikoku(place):
            stats["not_found"] += 1
            location["map_data_status"] = "place_outside_shikoku"
            record["_warnings"].append({
                "field": "location.coordinates",
                "code": "GOOGLE_MAPS_PLACE_OUTSIDE_SHIKOKU",
                "message": "Google place result is outside Shikoku.",
                "raw_value": place,
            })
            continue

        location.update({
            "address": place["address"],
            "map_data_status": "resolved",
            "coordinates": {
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "source": "google_maps_embed_place",
            },
            "google_maps_place_id": place["place_id"],
            "google_maps_cid": place["cid"],
            "google_maps_place_name": place["name"],
            "google_maps_geocode_url": request_url,
        })
        stats["geocoded"] += 1

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    temporary = output_path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    os.replace(temporary, output_path)
    return stats
