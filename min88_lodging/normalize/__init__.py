"""Raw min88 dict to conservative Min88LodgingV1 normalization."""

import re

from min88_lodging.model.v1 import (BUSINESS_STATUS, LIST_URL, LODGING_TYPE_MAP,
                                    PREFECTURE_JP, PROVIDER, SCHEMA_VERSION)
from min88_lodging.normalize.fields import (has_invalid_clock, keyed_state_issues,
                                             is_recognized_tri_state,
                                             normalize_images, parse_keyed_states,
                                             parse_parking, parse_prices, parse_rooms,
                                             parse_route, parse_time, parse_tri_state)


def _warning(field, code, message, raw_value):
    return {"field": field, "code": code, "message": message, "raw_value": raw_value}


def _modified_date(value):
    if not value:
        return None
    match = re.search(r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日", value)
    return "%s-%02d-%02d" % (match.group(1), int(match.group(2)), int(match.group(3))) if match else None


def normalize_lodging(raw, retrieved_at=None):
    """Normalize a raw parser dict; malformed optional fields never drop the record."""
    warnings = list(raw.get("parser_warnings") or [])
    context = raw.get("source_context") or {}
    basic = raw.get("basic_data") or {}
    marker = context.get("closure_marker")
    status = BUSINESS_STATUS.get(marker)
    if marker and status is None:
        status = "closed_or_suspended" if "休業" in marker and "閉業" in marker else None

    lodging_types = []
    for term in raw.get("lodging_types") or []:
        mapped = LODGING_TYPE_MAP.get(term)
        if mapped:
            for lodging_type in mapped if isinstance(mapped, list) else [mapped]:
                if lodging_type not in lodging_types:
                    lodging_types.append(lodging_type)
        else:
            warnings.append(_warning("lodging_types", "UNKNOWN_TAXONOMY",
                                     "Unknown min88 lodging taxonomy.", term))

    wifi = parse_tri_state(basic.get("wifi"))
    laundry_keys = {
        "洗濯機": "washing_machine", "乾燥機": "dryer",
        "洗濯+乾燥機": ("washing_machine", "dryer"),
        "洗濯機+乾燥機": ("washing_machine", "dryer"),
        "洗濯乾燥": ("washing_machine", "dryer"),
        "洗濯乾燥機": ("washing_machine", "dryer"),
    }
    payment_keys = {
        "現金": "cash", "カード": "credit_card", "クレジットカード": "credit_card", "電子マネー": "electronic_money",
        "電子決済": "electronic_money",
    }
    laundry = parse_keyed_states(basic.get("laundry"), laundry_keys, amount_available=True)
    payment_states = parse_keyed_states(basic.get("payment"), payment_keys)
    emoney_text = str(basic.get("emoney") or "").strip()
    emoney_methods = ([item.strip() for item in emoney_text.split(",") if item.strip()]
                       if emoney_text and not is_recognized_tri_state(emoney_text) else [])
    if emoney_methods:
        payment_states["electronic_money"] = "available"
    for field, value in (("facilities.wifi", basic.get("wifi")),
                         ("payment.electronic_money", basic.get("emoney"))):
        if value and field != "payment.electronic_money" and not is_recognized_tri_state(value):
            warnings.append(_warning(field, "UNRECOGNIZED_FORMAT",
                                     "Could not safely normalize tri-state value.", value))
    for field, keys in (("laundry", laundry_keys), ("payment", payment_keys)):
        value = basic.get(field)
        for issue in keyed_state_issues(value, keys, amount_available=field == "laundry"):
            warnings.append(_warning(field, "UNRECOGNIZED_FORMAT",
                                     "Could not safely normalize keyed label or value.", issue))
    facilities = [{"type": "wifi", "status": wifi, "raw_text": basic.get("wifi")},
                  {"type": "washing_machine", "status": laundry["washing_machine"], "raw_text": basic.get("laundry")},
                  {"type": "dryer", "status": laundry["dryer"], "raw_text": basic.get("laundry")}]
    supplemental = [item for item in raw.get("supplemental_facilities") or [] if str(item).strip() not in ("", "ー")]
    negative = re.compile(r"(?:なし|ありません|不可|禁止|利用できません|ご遠慮|未確認)")
    facilities.extend({"type": "supplemental", "status": "unknown" if negative.search(item) else "available",
                       "label": item, "raw_text": item} for item in supplemental)

    pref = context.get("prefecture")
    address = basic.get("address")
    map_url = raw.get("google_maps_place_embed_url")
    can_search = bool(map_url or ((raw.get("name") or context.get("list_name")) and address))
    alternates = [dict(item) for item in raw.get("alternate_languages") or []]
    route = parse_route(raw.get("route_lines"), context.get("temple_context"))
    for side in ("previous_temple", "next_temple"):
        temple = route.get(side)
        if temple and temple["distance_km"] is None:
            lines = raw.get("route_lines") or []
            if lines:
                source_distance = lines[0].get("lkm" if side == "previous_temple" else "rkm")
                if source_distance not in (None, ""):
                    warnings.append(_warning("henro." + side + ".distance_km", "UNRECOGNIZED_FORMAT",
                                             "Could not safely normalize route distance.", source_distance))
    pricing = parse_prices(basic.get("price"))
    for item in pricing["items"]:
        if item["status"] == "ambiguous":
            warnings.append(_warning("pricing.items", "UNRECOGNIZED_FORMAT",
                                     "Could not safely normalize price item.", item["raw_text"]))
    for field in ("checkin", "checkout"):
        if has_invalid_clock(basic.get(field)):
            warnings.append(_warning(field, "UNRECOGNIZED_FORMAT",
                                     "Invalid clock value was not normalized.", basic.get(field)))

    return {
        "schema_version": SCHEMA_VERSION,
        "source": {"provider": PROVIDER, "source_id": context.get("source_id"),
                   "source_url": context.get("source_url"), "list_url": LIST_URL,
                   "retrieved_at": retrieved_at, "source_modified_at": _modified_date(raw.get("modified_text"))},
        "identity": {"name": raw.get("name") or context.get("list_name"), "name_kana": None},
        "business_status": status,
        "description": {"title": raw.get("editorial_title"), "text": raw.get("editorial_description"),
                        "provenance": "min88_editorial"},
        "henro": route,
        "lodging_types": lodging_types,
        "rooms": parse_rooms(basic.get("rooms"), basic.get("price")),
        "pricing": pricing,
        "check_in": parse_time(basic.get("checkin")),
        "check_out": parse_time(basic.get("checkout"), deadline=True),
        "parking": parse_parking(basic.get("parking")),
        "facilities": facilities,
        "payment": {**payment_states, "electronic_money_methods": emoney_methods,
                     "raw_text": basic.get("payment"),
                    "electronic_money_raw_text": basic.get("emoney")},
        "contact": {"phone": _source_value(basic.get("tel")), "website": _source_value(basic.get("website")),
                    "email": _source_value(basic.get("email"))},
        "location": {"prefecture": PREFECTURE_JP.get(pref, pref), "address": address,
                     "coordinates": None,
                     "map_data_status": "pending_geocode" if can_search else "source_data_incomplete",
                     "google_maps_place_embed_url": map_url,
                     "google_street_view_embed_url": raw.get("google_street_view_embed_url"),
                     "google_maps_directions_url": raw.get("google_maps_directions_url")},
        "images": normalize_images(raw.get("featured_image_url"), raw.get("gallery_image_urls")),
        "alternate_languages": alternates,
        "raw": {"status": marker, "basic_data": basic,
                "extra_fields": raw.get("extra_fields") or [],
                "basic_data_ignored_lines": raw.get("basic_data_ignored_lines") or [],
                "categories": raw.get("categories") or [],
                "lodging_types": raw.get("lodging_types") or [],
                "supplemental_facilities": raw.get("supplemental_facilities") or [],
                "unknown_sections": raw.get("unknown_sections") or [],
                "source_context": context},
        "_warnings": warnings,
    }


normalize_record = normalize_lodging


def _source_value(value):
    return None if str(value or "").strip() in ("", "未確認", "なし", "設定なし", "設定無し", "対象外", "ー") else value

__all__ = ["normalize_lodging", "normalize_record"]
