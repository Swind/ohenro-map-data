"""Pure parsers for min88 basic-data values."""

import re

from henroyado.normalize.image import split_image_url
from henroyado.normalize.room import parse_room
from henroyado.normalize.text import normalize_digits
from henroyado.normalize.time import parse_time_range


TRI_STATE = {
    "可": "available", "あり": "available", "OK": "available", "◯": "available", "○": "available",
    "不可": "unavailable", "なし": "unavailable", "NG": "unavailable",
    "未確認": "unknown", "対象外": "not_applicable", "設定なし": "not_applicable",
    "設定無し": "not_applicable", "—": "not_provided", "–": "not_provided", "ー": "not_provided",
}
ROOM_TYPE_MAP = {"個室": "private", "ドミトリー": "dormitory", "ﾄﾞﾐﾄﾘｰ": "dormitory", "相部屋": "shared"}
MEAL_PLAN_MAP = {"素泊り": "room_only", "素泊まり": "room_only", "朝食付": "breakfast", "夕食付": "dinner", "2食付": "two_meals", "２食付": "two_meals"}


def parse_tri_state(value):
    """Return available/unavailable/unknown/not_provided without guessing."""
    if value is None or not str(value).strip():
        return "not_provided"
    value = str(value).strip()
    return next((state for prefix, state in TRI_STATE.items() if value.startswith(prefix)), "unknown")


def is_recognized_tri_state(value):
    value = str(value or "").strip()
    return any(value.startswith(prefix) for prefix in TRI_STATE)


def parse_keyed_states(text, keys, amount_available=False):
    """Parse ``label:value`` pipe items into stable keys and tri-state values."""
    result = {key: "not_provided" for targets in keys.values()
              for key in (targets if isinstance(targets, tuple) else (targets,))}
    if not text:
        return result
    for item in re.split(r"[|\r\n]+", str(text)):
        match = re.match(r"\s*([^:：]+)\s*[:：]\s*(.*?)\s*$", item)
        label = match.group(1).strip().lstrip("※").strip() if match else None
        if label in keys:
            state = parse_tri_state(match.group(2))
            if amount_available and state == "unknown" and _is_laundry_amount(match.group(2)):
                state = "available"
            targets = keys[label] if isinstance(keys[label], tuple) else (keys[label],)
            for key in targets:
                result[key] = state
    return result


def keyed_state_issues(text, keys, amount_available=False):
    issues = []
    for item in re.split(r"[|\r\n]+", str(text or "")):
        if not item.strip():
            continue
        match = re.match(r"\s*([^:：]+)\s*[:：]\s*(.*?)\s*$", item)
        label = match.group(1).strip().lstrip("※").strip() if match else None
        if not match:
            issues.append(item)
        elif label not in keys or not (is_recognized_tri_state(match.group(2)) or
                                      amount_available and _is_laundry_amount(match.group(2))):
            issues.append(item)
    return issues


def _is_laundry_amount(value):
    return bool(re.match(r"(?:無料|\d[\d,]*\s*円)", normalize_digits(str(value or "")).strip()))


def parse_time(text, deadline=False):
    start, end, display, notes = parse_time_range(text)
    normalized = normalize_digits(text or "").strip()
    start, start_day_offset = _normalize_clock(start)
    end, end_day_offset = _normalize_clock(end)
    if has_invalid_clock(text):
        start = end = display = None
        start_day_offset = end_day_offset = None
        notes = normalized or None
    if deadline and display and re.search(r"(?:前|まで)\s*$", normalized):
        end, start = start, None
        notes = "before" if normalized.endswith("前") else "by"
        start_day_offset, end_day_offset = end_day_offset, start_day_offset
    return {"time": display, "start": start, "end": end, "start_day_offset": start_day_offset,
            "end_day_offset": end_day_offset, "notes": notes, "raw_text": text}


def _normalize_clock(value):
    if value is None:
        return None, None
    hour, minute = map(int, value.split(":"))
    return "%02d:%02d" % (hour % 24, minute), hour // 24


def has_invalid_clock(text):
    for hour, minute in re.findall(r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)", normalize_digits(text or "")):
        if int(hour) > 29 or int(minute) > 59:
            return True
    return False


def parse_rooms(text, price_text=None):
    types, count = parse_room(text)
    normalized = normalize_digits(text or "")
    total = re.search(r"(?:合計|全)\s*(\d+)\s*(?:部屋|室)", normalized)
    if total:
        count = int(total.group(1))
    elif "うち" in normalized:
        primary = normalized.split("うち", 1)[0]
        _, count = parse_room(primary)
    combined = "|".join(value for value in (text, price_text) if value)
    mapped = []
    for source, target in ROOM_TYPE_MAP.items():
        if source in combined and target not in mapped:
            mapped.append(target)
    return {"types": mapped or types, "room_count": count, "raw_text": text}


def parse_parking(text):
    result = {"space_count": None, "fee_status": None, "reservation_required": None,
              "notes": None, "raw_text": text}
    if not text:
        return result
    value = normalize_digits(text)
    count = re.search(r"(\d+)\s*台", value)
    result["space_count"] = int(count.group(1)) if count else None
    if "無料" in value:
        result["fee_status"] = "free"
    elif "有料" in value:
        result["fee_status"] = "paid"
    if "予約不要" in value:
        result["reservation_required"] = False
    elif "要予約" in value or "予約必要" in value:
        result["reservation_required"] = True
    recognized = re.sub(r"\d+\s*台|無料|有料|[（(]?(?:予約不要|要予約|予約必要)[）)]?", "", value)
    recognized = re.sub(r"^[\s、,・/|]+|[\s、,・/|]+$", "", recognized)
    result["notes"] = recognized or None
    return result


def parse_prices(text):
    items = []
    notes = []
    if not text:
        return {"items": items, "notes": notes, "raw_text": text}
    for source_item in str(text).split("|"):
        value = normalize_digits(source_item).replace("，", ",").strip()
        label_match = re.match(r"([^:：]+)\s*[:：]\s*(.*)$", value)
        label = label_match.group(1).strip() if label_match else None
        body = label_match.group(2).strip() if label_match else value
        explicit = {"未確認": "unknown", "設定なし": "not_applicable", "設定無し": "not_applicable",
                    "なし": "unavailable", "無料": "free", "応相談": "negotiable"}
        status = next((state for prefix, state in explicit.items() if body.startswith(prefix)), None)
        if status:
            notes_text = body[next(len(prefix) for prefix in explicit if body.startswith(prefix)):].strip(" （()）") or None
            items.append({"label": label, "status": status, "amount_yen": 0 if status == "free" else None,
                          "min_amount_yen": 0 if status == "free" else None,
                          "max_amount_yen": 0 if status == "free" else None, "surcharge": False,
                          "room_type": None, "meal_plan": next((target for source, target in MEAL_PLAN_MAP.items() if source in value), None),
                          "notes": notes_text, "raw_text": source_item})
            continue
        matches = list(re.finditer(r"(?P<plus>\+)?\s*(?P<amount>\d[\d,]*)\s*円", value))
        if not matches:
            if value and not label_match:
                notes.append(value)
            elif body:
                items.append({"label": label, "status": "descriptive", "amount_yen": None,
                              "min_amount_yen": None, "max_amount_yen": None, "surcharge": False,
                              "room_type": None, "meal_plan": next((target for source, target in MEAL_PLAN_MAP.items() if source in value), None),
                              "notes": body, "raw_text": source_item})
            else:
                items.append({"label": label, "status": "ambiguous", "amount_yen": None,
                              "min_amount_yen": None, "max_amount_yen": None, "surcharge": False,
                              "room_type": None, "meal_plan": None, "notes": body or None,
                              "raw_text": source_item})
            continue
        previous_end = 0
        range_match = re.search(r"(\d[\d,]*)\s*円?\s*[〜～~]\s*(\d[\d,]*)\s*円", value)
        for index, match in enumerate(matches):
            if range_match and index:
                break
            prefix = value[previous_end:match.start()].lstrip("、, /・")
            room_type = next((target for source, target in ROOM_TYPE_MAP.items() if source in prefix), None)
            meal_plan = next((target for source, target in MEAL_PLAN_MAP.items() if source in value), None)
            label = re.sub(r"[:：、,\s]+$", "", prefix) or None
            amount = int((range_match.group(1) if range_match else match.group("amount")).replace(",", ""))
            maximum = int(range_match.group(2).replace(",", "")) if range_match else (None if re.search(r"円?\s*[〜～~]", value[match.end():]) else amount)
            items.append({
                "label": label,
                "status": "priced",
                "amount_yen": amount,
                "min_amount_yen": amount,
                "max_amount_yen": maximum,
                "surcharge": bool(match.group("plus")),
                "room_type": room_type,
                "meal_plan": meal_plan,
                "notes": value[range_match.end() if range_match else match.end():].strip(" 、,()（）") or None,
                "raw_text": source_item,
            })
            previous_end = match.end()
    return {"items": items, "notes": notes, "raw_text": text}


def parse_route(route_lines, fallback=None):
    line = (route_lines or [None])[0]
    if not line and fallback:
        return {
            "previous_temple": _temple(fallback.get("number"), fallback.get("name"), None,
                                         provenance="list_context"),
            "next_temple": None,
            "raw_route_data": route_lines or [],
        }
    line = line or {}
    return {
        "previous_temple": _temple(line.get("lnum") or line.get("left_number") or line.get("previous_number"),
                                     line.get("lname") or line.get("left_name") or line.get("previous_name"),
                                     line.get("lkm") or line.get("left_distance_km") or line.get("previous_distance_km")),
        "next_temple": _temple(line.get("rnum") or line.get("right_number") or line.get("next_number"),
                                 line.get("rname") or line.get("right_name") or line.get("next_name"),
                                 line.get("rkm") or line.get("right_distance_km") or line.get("next_distance_km")),
        "raw_route_data": route_lines or [],
    }


def _temple(number, name, distance, provenance="detail_route"):
    if number is None and name is None and distance is None:
        return None
    try:
        parsed_number = int(normalize_digits(str(number))) if number not in (None, "") else None
    except ValueError:
        parsed_number = None
    try:
        parsed_distance = float(normalize_digits(str(distance))) if distance not in (None, "") else None
    except ValueError:
        parsed_distance = None
    return {"number": parsed_number, "name": name, "distance_km": parsed_distance,
            "provenance": provenance}


def normalize_images(featured, gallery):
    images = []
    for role, urls in (("featured", [featured] if featured else []), ("gallery", gallery or [])):
        for original in urls:
            canonical, original = split_image_url(original)
            images.append({"url": canonical, "original_url": original, "role": role})
    return images
