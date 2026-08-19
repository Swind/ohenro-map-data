"""Export geocoded Min88LodgingV1 records as compact GeoJSON."""

from __future__ import annotations

from min88_lodging.crawler.storage import atomic_write_json
from min88_lodging.pipeline import read_jsonl


def _feature(record):
    source = record.get("source") or {}
    identity = record.get("identity") or {}
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

    lodging_types = record.get("lodging_types") or []
    rooms = record.get("rooms") or {}
    pricing = record.get("pricing") or {}
    contact = record.get("contact") or {}
    check_in = record.get("check_in") or {}
    check_out = record.get("check_out") or {}
    source_id = str(source.get("source_id") or "")
    return {
        "type": "Feature",
        "id": "min88-" + source_id,
        "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
        "properties": {
            "provider": "min88",
            "source_id": source_id,
            "name": identity.get("name"),
            "lodging_type": lodging_types[0] if lodging_types else None,
            "lodging_types": ", ".join(lodging_types) or None,
            "business_status": record.get("business_status"),
            "address": location.get("address"),
            "phone": contact.get("phone"),
            "website": contact.get("website"),
            "room_count": rooms.get("room_count"),
            "check_in": check_in.get("time"),
            "check_out": check_out.get("time"),
            "price": pricing.get("raw_text"),
            "source_url": source.get("source_url"),
            "coordinate_source": coordinates.get("source"),
        },
    }


def export_map(input_path, output_path):
    features = []
    skipped = 0
    for record in read_jsonl(input_path):
        feature = _feature(record)
        if feature is None:
            skipped += 1
        else:
            features.append(feature)
    atomic_write_json(output_path, {"type": "FeatureCollection", "features": features})
    return {"records": len(features) + skipped, "features": len(features), "skipped": skipped}


__all__ = ["export_map"]
