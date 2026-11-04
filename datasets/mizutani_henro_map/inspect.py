"""Create a deterministic source-style inventory from an archived snapshot."""

from __future__ import annotations

import json
import os

from datasets.mizutani_henro_map import config
from datasets.mizutani_henro_map.categories import classify, load_categories
from datasets.mizutani_henro_map.parser import icon_details, parse_kml, resolve_style
from datasets.mizutani_henro_map.storage import atomic_write_json


def inspect(data_dir: str = config.DEFAULT_DATA_DIR, *, snapshot: str | None = None,
            output: str = "datasets/mizutani_henro_map/output/mizutani-henro-style-inventory.json") -> dict:
    layout = config.data_layout(data_dir)
    if snapshot is None:
        try:
            with open(layout["current"], encoding="utf-8") as stream:
                snapshot = json.load(stream)["sha256"]
        except FileNotFoundError as error:
            raise FileNotFoundError("current snapshot missing; run fetch first") from error
    path = os.path.join(layout["snapshots"], snapshot, "map.kml")
    with open(path, "rb") as stream:
        parsed = parse_kml(stream.read())
    categories = load_categories()

    inventory = {}
    geometry_counts = {"Point": 0, "LineString": 0}
    for placemark in parsed["placemarks"]:
        for geometry in placemark["geometries"]:
            geometries = geometry["geometries"] if geometry["type"] == "MultiGeometry" else [geometry]
            for part in geometries:
                kind = part["type"]
                if kind not in geometry_counts:
                    continue
                geometry_counts[kind] += 1
                key = (placemark["style_url"], kind)
                item = inventory.setdefault(key, {
                    "style_url": placemark["style_url"],
                    **icon_details(placemark["style_url"]),
                    "geometry_type": kind,
                    "count": 0,
                    "folders": {},
                    "examples": [],
                    "classification": classify(placemark["style_url"], categories)["category"],
                    "app_icon": classify(placemark["style_url"], categories)["icon"],
                    "resolved_style": resolve_style(placemark["style_url"], parsed["styles"], parsed["style_maps"]),
                })
                item["count"] += 1
                folder = "/".join(placemark["folder_path"])
                item["folders"][folder] = item["folders"].get(folder, 0) + 1
                if len(item["examples"]) < 5:
                    item["examples"].append({"name": placemark["name"], "description": placemark["description_html"]})
    styles = sorted(inventory.values(), key=lambda item: (item["style_url"] or "", item["geometry_type"]))
    result = {
        "schema_version": 1,
        "dataset_id": config.DATASET_ID,
        "snapshot_sha256": snapshot,
        "document_name": parsed["document_name"],
        "placemark_count": len(parsed["placemarks"]),
        "geometry_counts": geometry_counts,
        "unsupported_geometry_types": parsed["unsupported_geometry_types"],
        "unresolved_style_urls": sorted({
            placemark["style_url"] for placemark in parsed["placemarks"]
            if placemark["style_url"] and not resolve_style(placemark["style_url"], parsed["styles"], parsed["style_maps"])
        }),
        "styles": styles,
    }
    atomic_write_json(output, result)
    return result
