"""Normalizer: RawInn -> HenroyadoInnV1 (plan §33 Step 4, §5 schema).

Each field normalizes independently. Failures produce warnings, never drop the
record. Raw values stay available alongside normalized values.
"""

import re

from henroyado.model.v1 import PREFECTURE_JP, PREFECTURE_PAGE, PROVIDER, SCHEMA_VERSION
from henroyado.normalize.facility import facility_type
from henroyado.normalize.image import split_image_url
from henroyado.normalize.meal import parse_meal
from henroyado.normalize.payment import clean_payment_text, parse_payment
from henroyado.normalize.room import parse_room
from henroyado.normalize.route import parse_route
from henroyado.normalize.text import clean_punct, normalize_half_kana, normalize_digits
from henroyado.normalize.time import parse_time_range


BUSINESS_STATUS = {
    "休業": "temporarily_closed",
    "閉業": "permanently_closed",
}


def _warn(warnings, field, code, message, raw_value):
    warnings.append({
        "field": field,
        "code": code,
        "message": message,
        "raw_value": raw_value,
    })


def _flat_ws(text):
    if text is None:
        return None
    return re.sub(r"\s+", " ", text).strip() or None


def _source_block(retrieved_at):
    return {
        "provider": PROVIDER,
        "source_id": None,
        "source_url": None,
        "prefecture_page": PREFECTURE_PAGE,
        "retrieved_at": retrieved_at,
    }


def _location(raw, embed_url):
    pref = raw["source_context"].get("prefecture")
    search_url = raw.get("google_maps_search_url")
    return {
        "prefecture": PREFECTURE_JP.get(pref) if pref else None,
        "address": None,
        "coordinates": None,
        "map_data_status": "pending_geocode" if search_url else "source_data_incomplete",
        "google_maps_search_url": search_url,
        "google_maps_embed_url": embed_url,
    }


def _facilities(raw, warnings):
    out = []
    for f in raw.get("facilities", []):
        ftype = facility_type(f.get("icon"))
        if ftype is None:
            _warn(warnings, "facilities", "UNKNOWN_FACILITY",
                  "Unmapped facility icon.", f.get("icon"))
        out.append({
            "type": ftype,
            "available": f.get("available"),
            "label": f.get("remark"),
            "source_icon": f.get("icon"),
        })
    return out


def _payment(raw, warnings):
    methods, cards = parse_payment(raw.get("payment"))
    return {
        "methods": methods,
        "cards": cards,
        "raw_text": clean_payment_text(raw.get("payment")),
    }


def _henro(raw, warnings):
    from_temple, to_temple = parse_route(raw.get("route"))
    if raw.get("route") and from_temple is None:
        _warn(warnings, "henro.route", "UNRECOGNIZED_FORMAT",
              "Could not safely parse temple route.", raw.get("route"))
    return {
        "from_temple": from_temple,
        "to_temple": to_temple,
        "raw_route_text": _flat_ws(raw.get("route")),
    }


def normalize_inn(raw, retrieved_at=None):
    """Normalize a RawInn into the HenroyadoInnV1 dict."""
    warnings = []

    rooms_types, room_count = parse_room(raw.get("room"))

    breakfast, dinner = parse_meal(raw.get("meal"))
    if raw.get("meal") and not (breakfast["available"] or dinner["available"]) and "なし" not in (raw.get("meal") or ""):
        _warn(warnings, "meals", "UNRECOGNIZED_FORMAT",
              "Could not recognize meal availability.", raw.get("meal"))

    check_in_start, check_in_end, check_in_disp, check_in_notes = parse_time_range(raw.get("check_in"))
    check_out_start, check_out_end, check_out_disp, check_out_notes = parse_time_range(raw.get("check_out"))

    payment = _payment(raw, warnings)
    price_lines = [li for li in raw.get("pricing_items", []) if not li.startswith("支払い方法")]

    embed_url = raw.get("google_maps_embed_url")
    images = []
    for url in raw.get("images", []):
        canonical, original = split_image_url(url)
        images.append({"url": canonical, "original_url": original})

    sc = raw.get("source_context", {})
    v1 = {
        "schema_version": SCHEMA_VERSION,
        "source": _source_block(retrieved_at),
        "identity": {"name": raw.get("name"), "name_kana": None},
        "business_status": BUSINESS_STATUS.get(sc.get("row_status")),
        "description": raw.get("description"),
        "henro": _henro(raw, warnings),
        "notice": raw.get("notice"),
        "rooms": {
            "types": rooms_types,
            "room_count": room_count,
            "raw_text": raw.get("room"),
        },
        "meals": {
            "breakfast": breakfast,
            "dinner": dinner,
            "raw_text": clean_punct(raw.get("meal")),
        },
        "check_in": {
            "time": check_in_disp,
            "start": check_in_start,
            "end": check_in_end,
            "notes": check_in_notes,
            "raw_text": _flat_ws(raw.get("check_in")),
        },
        "check_out": {
            "time": check_out_disp,
            "start": check_out_start,
            "end": check_out_end,
            "notes": check_out_notes,
            "raw_text": _flat_ws(raw.get("check_out")),
        },
        "facilities": _facilities(raw, warnings),
        "pricing": {
            "prices": [],
            "raw_text": "\n".join(price_lines) if price_lines else None,
        },
        "payment": payment,
        "contact": {
            "phone": raw.get("phone"),
            "website": raw.get("website"),
            "email": raw.get("email"),
        },
        "location": _location(raw, embed_url),
        "images": images,
        "raw": {
            "name": sc.get("front_row_name"),
            "room": raw.get("room"),
            "meal": raw.get("meal"),
            "route": raw.get("route"),
            "payment": raw.get("payment"),
            "distance": sc.get("row_distance"),
            "status": sc.get("row_status"),
            "types": sc.get("row_types"),
            "type_icons": sc.get("row_type_icons"),
            "remark": sc.get("row_remark"),
            "data_types": sc.get("row_data_types"),
            "table_heading": sc.get("table_heading"),
            "table_kind": sc.get("table_kind"),
            "prefecture": sc.get("prefecture"),
            "extra_details": raw.get("extra_details", []),
        },
        "_warnings": warnings,
    }

    for detail in raw.get("extra_details", []):
        _warn(warnings, "details", "UNKNOWN_DETAIL_FIELD",
              "Unknown 宿詳細 field.", detail["label"])

    return v1
