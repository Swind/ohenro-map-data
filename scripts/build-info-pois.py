#!/usr/bin/env python3
"""Consolidate information-POI sources into one category-consistent GeoJSON.

Excludes lodging (dedicated henroyado/min88/OSM pipeline). Unified `category`
taxonomy (the app-filter level):

    temple / shrine / toilet / water / rest_area / food / shop / transport /
    onsen / sightseeing / wayfinding / warning_hazard / experience_note /
    route_endpoint / other

Every feature carries `source`, `source_category` (the original classification,
never discarded), a stable `poi_id`, `name` and the unified `category`. No
cross-source dedup (the app filters by source+category instead).

Sources:
  output/temples.geojson               -> temple (canonical 88)
  output/sekaiisan-henro-normalized.json -> temples + toilets (599+1 defect)
  output/mizutani-henro-pois.geojson   -> all non-lodging categories
  output/shikoku-nature-trail-pois.geojson -> tourism_spot / kml_poi
  output/arukihenro-routes.json        -> all non-lodging point categories
  output/shikoku-basemap.pmtiles       -> EVERY OSM pois Point (all kinds, each
                                          mapped to a unified category)

Outputs output/pois/pois.geojson and output/pois/pois-report.json
(byte-deterministic, no timestamps, atomic writes).
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import tempfile

import mercantile
import mapbox_vector_tile
from pmtiles.reader import MemorySource, Reader, Compression, all_tiles

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUT_DIR = os.path.join(ROOT, "output", "pois")

# Unified categories, in display order.
CATEGORIES = (
    "temple", "shrine", "toilet", "water", "rest_area", "food", "shop",
    "transport", "onsen", "sightseeing", "wayfinding", "warning_hazard",
    "health", "education", "lodging", "experience_note", "route_endpoint",
    "other",
)

# OSM basemap `pois` layer: map every kind to a unified category. Kinds not in
# the table fall through to `other` (source_category preserves the raw kind).
# Grouped as category -> kinds for maintainability.
OSM_KIND_CATEGORY: dict[str, set[str]] = {
    "temple": {
        "place_of_worship", "temple", "monastery", "church", "chapel", "mosque",
    },
    "shrine": {"wayside_shrine", "shrine", "city_gate"},
    "toilet": {"toilets", "rest_rooms"},
    "water": {"drinking_water", "water_point", "fountain", "spring", "water",
              "waterfall"},
    "rest_area": {"shelter", "bench", "picnic_table", "rest_area", "lean_to",
                  "alpine_hut", "wilderness_hut", "picnic_site", "pavilion",
                  "gazebo", "campfire"},
    "food": {"restaurant", "cafe", "fast_food", "pub", "bar", "ice_cream",
             "bakery", "food_court", "deli", "seafood", "noodle", "pastry",
             "coffee", "sake", "tea", "wine", "chocolate", "biergarten",
             "kiosk", "caterer", "hookah_lounge", "beverages"},
    "shop": {"supermarket", "convenience", "pharmacy", "clothes", "books",
             "gift", "electronics", "mobile_phone", "doityourself", "hardware",
             "stationery", "florist", "butcher", "greengrocer", "shoes",
             "jewelry", "optician", "cosmetics", "hairdresser", "laundry",
             "dry_cleaning", "video", "toys", "furniture", "variety_store",
             "second_hand", "tobacco", "newsagent", "alcohol", "bakery",
             "confectionery", "marketplace", "department_store", "mall",
             "shopping_mall", "boutique", "antiques", "craft", "tailor",
             "sewing", "carpet_layer", "bag", "appliance", "watches",
             "musical_instrument", "fuel", "car_repair", "car_parts", "car_wash",
             "tyres", "motorcycle", "bicycle", "bicycle_repair_station",
             "copyshop", "pawnbroker", "pet", "pet_grooming", "garden_centre",
             "houseware", "fabric", "pottery", "carpenter", "electrician",
             "plumber", "electronics_repair", "photo", "photo_studio",
             "kitchen", "hifi", "frozen_food", "health_food", "grocery",
             "wine_shop", "dairy", "cheese", "food_market", "general_store"},
    "transport": {"station", "bus_stop", "tram_stop", "ferry_terminal", "taxi",
                  "car_rental", "car", "bicycle_rental", "bus_station", "parking",
                  "charging_station", "motorcycle_parking", "parking_entrance",
                  "boat_rental", "halt", "train_station_entrance", "marina",
                  "slipway", "kick-scooter_rental", "car_sharing",
                  "car_pooling", "boat", "aerodrome", "helipad"},
    "onsen": {"public_bath", "hot_spring", "sauna", "spa", "spa_resort"},
    "lodging": {"hotel", "guest_house", "hostel", "motel", "camp_site", "chalet",
                "love_hotel", "resort", "dormitory", "caravan_site",
                "wilderness_hut", "alpine_hut", "bed"},
    "sightseeing": {"museum", "attraction", "viewpoint", "monument", "castle",
                    "ruins", "archaeological_site", "historic", "artwork",
                    "gallery", "theatre", "cinema", "theme_park", "zoo",
                    "aquarium", "beach", "park", "garden", "cave_entrance",
                    "peak", "cape", "bay", "beach_resort", "water_park",
                    "amusement_arcade", "tower", "windmill", "lighthouse",
                    "observatory", "fort", "memorial", "stone", "rock",
                    "sculpture", "exhibition_centre", "arts_centre",
                    "events_venue", "stadium", "playground", "recreation_ground",
                    "golf_course", "sports_centre", "pitch", "swimming_pool",
                    "swimming_area", "bowling_alley", "miniature_golf",
                    "surf_school", "dive_centre", "horse_riding", "outdoor",
                    "picnic_site", "viewpoint", "lookout", "panorama",
                    "picnic_table", "nature_reserve", "botanical_garden",
                    "fishing", "marina", "beach"},
    "wayfinding": {"information", "signpost", "guidepost", "milestone",
                   "emergency_access_point", "hiking_route", "map_board"},
    "warning_hazard": {"danger", "hazard", "flood", "landslide", "cliff",
                       "highwater_mark", "speed_camera", "avalanche", "fire"},
    "health": {"hospital", "doctors", "dentist", "clinic", "veterinary",
               "pharmacy", "nursing_home", "midwife", "physiotherapist",
               "podiatrist", "blood_bank", "health_post", "medical_supply"},
    "education": {"school", "university", "kindergarten", "college", "library",
                  "prep_school", "music_school", "driving_school",
                  "language_school", "dojo", "childcare", "research_institute",
                  "training"},
}

# Reverse lookup kind -> category (last match wins via dict build order).
OSM_KIND_TO_CATEGORY: dict[str, str] = {}
for _cat, _kinds in OSM_KIND_CATEGORY.items():
    for _k in _kinds:
        OSM_KIND_TO_CATEGORY[_k] = _cat

# OSM kinds observed in the basemap that are pure basemap infrastructure /
# rendering noise and land in `other` (extracted, but filtered out by default
# in the app). Kept here only for documentation/audit.
OSM_INFRASTRUCTURE = {
    "crossing", "tree", "traffic_signals", "level_crossing", "switch",
    "stop", "tram_crossing", "tram_level_crossing", "buffer_stop",
    "traffic_mirror", "give_way", "passing_place", "turning_circle",
    "waste_basket", "street_lamp", "signal", "bench", "windsock",
    "emergency_bay", "parking_position", "holding_position", "apron",
    "taxiway", "runway", "platform", "turning_loop", "mini_roundabout",
    "railway_crossing", "crossing;tram_crossing", "traffic_signals;crossing",
}

_WTR_REST = ("道の駅", "海の駅", "ヘンロ小屋", "休憩所")
_WTR_ONSEN = ("温泉", "銭湯", "立寄り湯", "立ち寄り湯", "入浴", "サウナ",
              "の湯", "湯元", "風呂", "共楽湯")
_WTR_WATER = ("湧き水", "湧水", "水道", "水飲み", "給水")


def mizutani_water_toilet_rest_category(name: str) -> str:
    """Split Mizutani's mixed water_toilet_rest bucket by name heuristics.

    Conservative, auditable in the report: 道の駅/海の駅/休憩所 -> rest_area,
    hot-spring/bath keywords -> onsen, spring/drinking-water keywords -> water,
    anything else stays rest_area.
    """
    n = name or ""
    if any(k in n for k in _WTR_REST):
        return "rest_area"
    if any(k in n for k in _WTR_ONSEN):
        return "onsen"
    if any(k in n for k in _WTR_WATER):
        return "water"
    return "rest_area"


MIZUTANI_CATEGORY = {
    "temple": "temple",
    "transport": "transport",
    "shop_supply": "shop",
    "food": "food",
    "experience_note": "experience_note",
    "wayfinding": "wayfinding",
    "warning_hazard": "warning_hazard",
    "other": "other",
}

ARUKIHENRO_CATEGORY = {
    "temple_related": "temple",
    "shrine": "shrine",
    "waymarker": "wayfinding",
    "route_feature": "wayfinding",
    "elevation_mileage": "wayfinding",
    "food_shop": "food",
    "onsen": "onsen",
    "viewpoint": "sightseeing",
    "sightseeing": "sightseeing",
    "rest_area": "rest_area",
    "route_endpoint": "route_endpoint",
    "other": "other",
}

EXCLUDED_SOURCE_CATEGORIES = {"lodging"}


def feature(poi_id: str, source: str, source_category: str, category: str,
            name: str, geometry: dict, extra: dict | None = None) -> dict:
    props = {
        "poi_id": poi_id,
        "source": source,
        "source_category": source_category,
        "category": category,
        "name": name,
    }
    if extra:
        props.update(extra)
    return {
        "type": "Feature",
        "id": poi_id,
        "properties": props,
        "geometry": geometry,
    }


def load_temples(features: list[dict]) -> tuple[list[dict], dict]:
    """Canonical 88 temples from temples.geojson."""
    out = []
    counts = {}
    for f in features:
        props = f.get("properties", {})
        geom = f.get("geometry")
        if not geom or geom.get("type") != "Point":
            continue
        pid = props.get("id") or "temple-%s" % props.get("number")
        out.append(feature(
            pid, "temples", "temple", "temple",
            props.get("name_ja") or "",
            geom,
            {k: props[k] for k in ("number", "name_en", "name_kana")
             if k in props},
        ))
    counts["temples"] = len(out)
    return out, counts


def load_sekaiisan(data: dict, toilets: bool = True) -> tuple[list[dict], dict]:
    """88 temples + toilets from the normalized 88sekaiisan document."""
    out = []
    counts = {}
    for t in data.get("temples", []):
        geom = t.get("geometry")
        if not geom:
            continue
        out.append(feature(
            t["id"], "sekaiisan", "temple", "temple",
            t.get("name_jp") or t.get("raw_name") or "",
            geom, {"number": t.get("number")},
        ))
    counts["sekaiisan_temples"] = len(out)
    if toilets:
        toilet_count = 0
        for t in data.get("toilets", []):
            geom = t.get("geometry")
            if not geom:
                continue
            out.append(feature(
                t["id"], "sekaiisan", "toilet", "toilet",
                t.get("facility_name") or t.get("raw_type") or "",
                geom,
                {k: t[k] for k in
                 ("raw_type", "prefecture", "address", "hours",
                  "available_days", "open", "close", "toilet_type", "washlet",
                  "notes") if k in t},
            ))
            toilet_count += 1
        counts["sekaiisan_toilets"] = toilet_count
    return out, counts


def load_mizutani(features: list[dict]) -> tuple[list[dict], dict]:
    out = []
    counts = {"water_toilet_rest_split": {}}
    for f in features:
        props = f.get("properties", {})
        geom = f.get("geometry")
        if not geom or geom.get("type") != "Point":
            continue
        coords = geom["coordinates"][:2]
        scat = props.get("category") or "other"
        if scat in EXCLUDED_SOURCE_CATEGORIES:
            continue
        if scat == "water_toilet_rest":
            category = mizutani_water_toilet_rest_category(props.get("name"))
            counts["water_toilet_rest_split"][category] = (
                counts["water_toilet_rest_split"].get(category, 0) + 1
            )
            scat_keep = scat
        else:
            category = MIZUTANI_CATEGORY.get(scat, "other")
            scat_keep = scat
        out.append(feature(
            props["feature_id"], "mizutani", scat_keep, category,
            props.get("name") or "",
            {"type": "Point", "coordinates": coords},
            {k: props[k] for k in
             ("description", "url", "icon", "icon_id", "color", "folder")
             if k in props and props[k] is not None},
        ))
    counts["total"] = len(out)
    return out, counts


def load_nature_trail(features: list[dict]) -> tuple[list[dict], dict]:
    out = []
    counts = {}
    for f in features:
        props = f.get("properties", {})
        geom = f.get("geometry")
        if not geom or geom.get("type") != "Point":
            continue
        kind = props.get("kind") or "kml_poi"
        out.append(feature(
            props["poi_id"], "nature_trail", kind, "sightseeing",
            props.get("name") or "",
            geom,
            {k: props[k] for k in ("route_id", "content_id")
             if k in props and props[k] is not None},
        ))
    counts["total"] = len(out)
    return out, counts


def load_arukihenro(data: dict) -> tuple[list[dict], dict]:
    out = []
    counts = {}
    for route in data.get("routes", []):
        route_id = route.get("id") or "route"
        for map_ in route.get("maps", []):
            map_id = map_.get("map_id") or "map"
            for idx, p in enumerate(map_.get("points", []), start=1):
                coords = p.get("coordinates")
                if not coords or len(coords) < 2:
                    continue
                scat = p.get("category") or "other"
                if scat in EXCLUDED_SOURCE_CATEGORIES:
                    continue
                category = ARUKIHENRO_CATEGORY.get(scat, "other")
                pid = "arukihenro-%s-%s-%d" % (route_id, map_id, idx)
                extra = {}
                if p.get("photos"):
                    extra["photos"] = p["photos"]
                if p.get("folder"):
                    extra["folder"] = p["folder"]
                out.append(feature(
                    pid, "arukihenro", scat, category,
                    p.get("name") or "",
                    {"type": "Point", "coordinates": coords},
                    extra,
                ))
    counts["total"] = len(out)
    return out, counts


def _mvt_to_lonlat(z: int, x: int, y: int, px: float, py: float,
                   extent: int) -> tuple[float, float]:
    west, south, east, north = mercantile.bounds(x, y, z)
    lon = west + (px / extent) * (east - west)
    lat = north - (py / extent) * (north - south)
    return round(lon, 6), round(lat, 6)


def load_osm_basemap(basemap_path: str) -> tuple[list[dict], dict]:
    """Extract every Point POI from the basemap `pois` layer (max-zoom tiles).

    All kinds are extracted (nothing dropped); each kind maps to a unified
    category via OSM_KIND_TO_CATEGORY, falling back to `other` when unmapped.
    """
    data_bytes = open(basemap_path, "rb").read()
    src = MemorySource(data_bytes)
    reader = Reader(src)
    header = reader.header()
    max_zoom = header["max_zoom"]
    out = []
    counts = {}
    unmapped = {}
    index = 0
    for (z, x, y), raw in all_tiles(src):
        if z != max_zoom:
            continue
        if header["tile_compression"] == Compression.GZIP:
            raw = gzip.decompress(raw)
        try:
            decoded = mapbox_vector_tile.decode(raw)
        except Exception:
            continue
        pois = decoded.get("pois")
        if not pois or not pois.get("features"):
            continue
        extent = pois.get("extent") or 4096
        for f in pois["features"]:
            kind = f["properties"].get("kind") or "other"
            geometry = f.get("geometry")
            if not geometry or geometry.get("type") != "Point":
                continue
            px, py = geometry["coordinates"][0], geometry["coordinates"][1]
            lon, lat = _mvt_to_lonlat(z, x, y, px, py, extent)
            name = f["properties"].get("name") or f["properties"].get(
                "name:ja") or ""
            pid = "osm-%s-%d-%d-%d-%d" % (kind, z, x, y, index)
            index += 1
            category = OSM_KIND_TO_CATEGORY.get(kind, "other")
            if category == "other" and kind not in OSM_KIND_TO_CATEGORY:
                unmapped[kind] = unmapped.get(kind, 0) + 1
            counts[category] = counts.get(category, 0) + 1
            extra = {}
            if f["properties"].get("name:ja"):
                extra["name_ja"] = f["properties"]["name:ja"]
            if f["properties"].get("kind_detail"):
                extra["kind_detail"] = f["properties"]["kind_detail"]
            out.append(feature(
                pid, "osm", kind, category, name,
                {"type": "Point", "coordinates": [lon, lat]},
                extra,
            ))
    counts["total"] = len(out)
    counts["unmapped_kinds"] = unmapped
    return out, counts


def atomic_write_json(path: str, data) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".pois-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--basemap",
                        default=os.path.join(ROOT, "output", "shikoku-basemap.pmtiles"))
    parser.add_argument("--skip-osm", action="store_true",
                        help="skip the OSM basemap POI extraction")
    args = parser.parse_args(argv)

    features: list[dict] = []
    report = {"categories": {}}

    def absorb(label, loader):
        items, counts = loader
        features.extend(items)
        report[label] = counts

    absorb("temples", load_temples(
        json.load(open(os.path.join(ROOT, "output", "temples.geojson"),
                       encoding="utf-8"))["features"]))
    absorb("sekaiisan", load_sekaiisan(
        json.load(open(os.path.join(ROOT, "output",
                                    "sekaiisan-henro-normalized.json"),
                       encoding="utf-8"))))
    absorb("mizutani", load_mizutani(
        json.load(open(os.path.join(ROOT, "output",
                                    "mizutani-henro-pois.geojson"),
                       encoding="utf-8"))["features"]))
    absorb("nature_trail", load_nature_trail(
        json.load(open(os.path.join(ROOT, "output",
                                    "shikoku-nature-trail-pois.geojson"),
                       encoding="utf-8"))["features"]))
    absorb("arukihenro", load_arukihenro(
        json.load(open(os.path.join(ROOT, "output", "arukihenro-routes.json"),
                       encoding="utf-8"))))
    if not args.skip_osm:
        absorb("osm", load_osm_basemap(args.basemap))

    features.sort(key=lambda f: f["id"])
    for cat in CATEGORIES:
        report["categories"][cat] = sum(
            1 for f in features if f["properties"]["category"] == cat
        )
    other = sum(report["categories"].values())
    report["categories"]["total"] = len(features)
    report["feature_count"] = len(features)

    out_geojson = os.path.join(args.output_dir, "pois.geojson")
    out_report = os.path.join(args.output_dir, "pois-report.json")
    atomic_write_json(out_geojson, {
        "type": "FeatureCollection",
        "name": "info-pois",
        "features": features,
    })
    atomic_write_json(out_report, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("wrote", out_geojson, "and", out_report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())