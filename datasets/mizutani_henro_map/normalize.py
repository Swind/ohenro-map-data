"""Build a deterministic, safe-to-consume dataset from an archived KML."""

from __future__ import annotations

import hashlib
import html
from html.parser import HTMLParser
import json
import os
import re

from datasets.mizutani_henro_map import config
from datasets.mizutani_henro_map.categories import classify, load_categories
from datasets.mizutani_henro_map.parser import icon_details, parse_kml, resolve_style
from datasets.mizutani_henro_map.storage import atomic_write_json


class _DescriptionParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "br":
            self.parts.append("\n")
        elif tag.lower() == "a":
            href = dict(attrs).get("href")
            if href and href.lower().startswith(("http://", "https://")):
                self.links.append(html.unescape(href))

    def handle_data(self, data):
        self.parts.append(data)


def _description(value: str | None) -> tuple[str | None, list[str]]:
    if not value:
        return None, []
    parser = _DescriptionParser()
    parser.feed(value)
    parser.close()
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", html.unescape("".join(parser.parts)))
    text = "\n".join(line.strip() for line in text.splitlines() if line.strip()) or None
    return text, list(dict.fromkeys(parser.links))


def _parts(geometry: dict) -> list[dict]:
    return geometry["geometries"] if geometry["type"] == "MultiGeometry" else [geometry]


def _feature_id(geometry: dict, folder_path: list[str], style_url: str | None, seen: dict[str, int]) -> tuple[str, str]:
    canonical = json.dumps({"geometry": geometry, "folder_path": folder_path, "style_url": style_url}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    checksum = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    prefix = "P" if geometry["type"] == "Point" else "L"
    base = "MHM_%s_%s" % (prefix, checksum[:12])
    seen[base] = seen.get(base, 0) + 1
    return (base if seen[base] == 1 else "%s_%02d" % (base, seen[base])), checksum


def _snapshot(data_dir: str, snapshot: str | None) -> tuple[str, dict, bytes]:
    layout = config.data_layout(data_dir)
    if snapshot is None:
        try:
            with open(layout["current"], encoding="utf-8") as stream:
                snapshot = json.load(stream)["sha256"]
        except FileNotFoundError as error:
            raise FileNotFoundError("current snapshot missing; run fetch first") from error
    directory = os.path.join(layout["snapshots"], snapshot)
    with open(os.path.join(directory, "metadata.json"), encoding="utf-8") as stream:
        metadata = json.load(stream)
    with open(os.path.join(directory, "map.kml"), "rb") as stream:
        return snapshot, metadata, stream.read()


def normalize(data_dir: str = config.DEFAULT_DATA_DIR, *, snapshot: str | None = None,
              output: str = "datasets/mizutani_henro_map/output/mizutani-henro-map.json") -> dict:
    snapshot, metadata, raw = _snapshot(data_dir, snapshot)
    parsed = parse_kml(raw)
    if parsed["unsupported_geometry_types"]:
        raise ValueError("unsupported KML geometry: %s" % ", ".join(parsed["unsupported_geometry_types"]))
    categories = load_categories()
    seen: dict[str, int] = {}
    features = []
    for placemark in parsed["placemarks"]:
        if placemark["unsupported_geometry_types"] or not placemark["geometries"]:
            raise ValueError("Placemark %d has unsupported or missing geometry" % placemark["source_order"])
        description, links = _description(placemark["description_html"])
        details = icon_details(placemark["style_url"])
        classification = classify(placemark["style_url"], categories)
        style = resolve_style(placemark["style_url"], parsed["styles"], parsed["style_maps"])
        for geometry in placemark["geometries"]:
            for part in _parts(geometry):
                feature_id, canonical_hash = _feature_id(part, placemark["folder_path"], placemark["style_url"], seen)
                features.append({
                    "feature_id": feature_id,
                    "canonical_hash": canonical_hash,
                    "source_order": placemark["source_order"],
                    "geometry_type": part["type"],
                    "name": placemark["name"],
                    "description": description,
                    "description_html": placemark["description_html"],
                    "links": links,
                    "folder_path": placemark["folder_path"],
                    "style_url": placemark["style_url"],
                    **details,
                    **classification,
                    "line_color": style["line_color"]["rgb"] if style and style["line_color"] else None,
                    "line_width": style["line_width"] if style else None,
                    "geometry": {"type": part["type"], "coordinates": part["coordinates"]},
                })
    features.sort(key=lambda feature: (feature["source_order"], feature["feature_id"]))
    summary = {
        "placemark_count": len(parsed["placemarks"]),
        "feature_count": len(features),
        "point_count": sum(feature["geometry_type"] == "Point" for feature in features),
        "line_string_count": sum(feature["geometry_type"] == "LineString" for feature in features),
        "category_counts": {
            category: sum(feature["category"] == category for feature in features if feature["geometry_type"] == "Point")
            for category in sorted({feature["category"] for feature in features if feature["geometry_type"] == "Point"})
        },
    }
    result = {
        "schema_version": 1,
        "dataset_id": config.DATASET_ID,
        "source": {
            "snapshot_sha256": snapshot,
            "map_id": metadata["map_id"],
            "title": metadata["title"],
            "author": metadata["author"],
            "map_url": metadata["source_map_url"],
            "article_url": metadata["source_article_url"],
        },
        "styles": sorted(parsed["styles"].values(), key=lambda style: style["id"]),
        "features": features,
        "summary": summary,
    }
    atomic_write_json(output, result)
    return result
