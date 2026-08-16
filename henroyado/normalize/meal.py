"""Meal parsing (plan §10), with structured breakfast/dinner times.

Examples:
  "なし"                     -> breakfast/dinner both unavailable
  "朝食 (7:00) 、 夕食"       -> breakfast start 07:00, dinner
  "朝食 (6:30~9:00) 、 夕食"  -> breakfast start 06:30, end 09:00
  "朝食 (06:30~) 、 夕食"     -> breakfast start 06:30 (open-ended)
  "朝食 、 夕食"              -> both, no times
  "夕食"                     -> dinner only
"""

from henroyado.normalize.text import normalize_digits
from henroyado.normalize.time import find_time_range


def _empty():
    return {"available": False, "time": None, "start": None, "end": None}


def parse_meal(text):
    """Returns (breakfast, dinner) dicts with available / time / start / end."""
    breakfast = _empty()
    dinner = _empty()
    if not text:
        return breakfast, dinner
    t = normalize_digits(text)
    if "なし" in t:
        return breakfast, dinner

    if "朝食" in t:
        breakfast["available"] = True
        start, end, display = find_time_range(t[t.find("朝食"):])
        breakfast["time"] = display
        breakfast["start"] = start
        breakfast["end"] = end
    if "夕食" in t:
        dinner["available"] = True
        start, end, display = find_time_range(t[t.find("夕食"):])
        dinner["time"] = display
        dinner["start"] = start
        dinner["end"] = end
    return breakfast, dinner
