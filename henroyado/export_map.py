"""Export geocoded Henroyado records as compact, deduplicated GeoJSON."""

from __future__ import annotations

import json
import os
import tempfile


def _feature(record):
    location = record.get("location") or {}
    coordinates = location.get("coordinates") or {}
    if location.get("map_data_status") != "resolved":
        return None
    try:
        latitude = float(coordinates["latitude"])
        longitude = float(coordinates["longitude"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None
    place_id = location.get("google_maps_place_id")
    if not isinstance(place_id, str) or not place_id:
        return None
    identity = record.get("identity") or {}
    contact = record.get("contact") or {}
    rooms = record.get("rooms") or {}
    pricing = record.get("pricing") or {}
    check_in = record.get("check_in") or {}
    check_out = record.get("check_out") or {}
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
        "properties": {
            "provider": "henroyado",
            "source_id": place_id,
            "name": identity.get("name"),
            "lodging_type": None,
            "lodging_types": None,
            "business_status": record.get("business_status"),
            "address": location.get("address"),
            "phone": contact.get("phone"),
            "website": contact.get("website"),
            "room_count": rooms.get("room_count"),
            "check_in": check_in.get("time"),
            "check_out": check_out.get("time"),
            "price": pricing.get("raw_text"),
            "source_url": None,
            "coordinate_source": coordinates.get("source"),
        },
    }


def export_map(input_path, output_path):
    features = []
    seen_place_ids = set()
    records = skipped = duplicates = 0
    with open(input_path, encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            records += 1
            feature = _feature(json.loads(line))
            if feature is None:
                skipped += 1
                continue
            place_id = feature["properties"]["source_id"]
            if place_id in seen_place_ids:
                duplicates += 1
                continue
            seen_place_ids.add(place_id)
            features.append(feature)
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".tmp-", dir=os.path.dirname(os.path.abspath(output_path)))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"type": "FeatureCollection", "features": features}, handle, ensure_ascii=False)
            handle.write("\n")
        os.replace(temporary, output_path)
    except BaseException:
        os.unlink(temporary)
        raise
    return {"records": records, "features": len(features), "skipped": skipped, "duplicates": duplicates}
