"""Google Maps place enrichment through the public embed response."""

import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import time
import urllib.parse
import urllib.request

from datasets._pipeline import atomic_json, read_json
from datasets.henroyado.fetcher.fetcher import USER_AGENT
from datasets.henroyado.normalize.map import parse_coordinates


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


def fetch_place(search_url, cache_dir, timeout=30, force=False, name=None):
    """Cache by source name and request URL; changed listings are fetched anew."""
    url = embed_url(search_url)
    cache = Path(cache_dir)
    legacy = cache / (hashlib.sha256(url.encode("utf-8")).hexdigest() + ".html")
    identity = url if name is None else json.dumps([url, name], ensure_ascii=False)
    path = cache / (hashlib.sha256(identity.encode("utf-8")).hexdigest() + ".html")
    binding = legacy.with_suffix(".identity.json")
    if name is not None and not path.exists() and legacy.exists() and not force:
        if not binding.exists() or read_json(binding) == {"name": name, "url": url}:
            atomic_json(binding, {"name": name, "url": url})
            shutil.copyfile(legacy, path)
    if path.exists() and not force:
        try:
            content = path.read_text(encoding="utf-8")
            validate_response(content)
            return parse_place(content), url, True
        except (ValueError, UnicodeError):
            pass

    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        content = response.read().decode("utf-8", errors="replace")
        final_url = response.geturl()
    validate_response(content, final_url)
    place = parse_place(content, final_url)
    cache.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)
    return place, url, False


def validate_response(content, final_url=None):
    """Do not persist consent, throttling, or other non-map responses."""
    host = urllib.parse.urlsplit(final_url or "").hostname or ""
    if (host.startswith(("consent.", "sorry.")) or
            not re.search(r"</html\s*>", content, re.IGNORECASE) or
            not any(marker in content for marker in ("_pageData", "APP_INITIALIZATION_STATE", "initEmbed"))):
        raise ValueError("Google returned an incomplete or non-map response")


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
                search_url, cache_dir, timeout=timeout, force=force,
                name=record["identity"]["name"],
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
        if place is None or not place.get("place_id"):
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

    if stats["errors"] and os.path.exists(output_path):
        return stats

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    temporary = os.fspath(output_path) + ".tmp"
    with open(temporary, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    os.replace(temporary, output_path)
    return stats
