"""Load only human-confirmed source style classifications."""

from __future__ import annotations

import json
import os

from mizutani_henro_map.parser import icon_details

_DEFAULT = {"category": "unclassified", "icon": "other"}
_CATEGORIES = {
    "temple", "lodging", "food", "shop_supply", "transport", "wayfinding",
    "warning_hazard", "water_toilet_rest", "experience_note", "other", "unclassified",
}


def load_categories(path: str | None = None) -> dict:
    if path is None:
        path = os.path.join(os.path.dirname(__file__), "style_categories.json")
    with open(path, encoding="utf-8") as stream:
        value = json.load(stream)
    if value.get("schema_version") != 1 or not isinstance(value.get("icons"), dict) or not isinstance(value.get("style_overrides"), dict):
        raise ValueError("invalid style_categories.json")
    return value


def classify(style_url: str | None, categories: dict) -> dict:
    """Use an exact style override, then its icon ID; never infer from text."""
    details = icon_details(style_url)
    value = categories["style_overrides"].get(style_url)
    if value is None and details["icon_id"]:
        value = categories["icons"].get(details["icon_id"])
    if value is None:
        return dict(_DEFAULT)
    if value.get("category") not in _CATEGORIES or not isinstance(value.get("icon"), str):
        raise ValueError("style category entries require category and icon")
    return {"category": value["category"], "icon": value["icon"]}
