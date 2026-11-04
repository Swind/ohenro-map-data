"""Compare two immutable snapshots without relying on source ordering."""

from __future__ import annotations

import json
import os
import tempfile

from datasets.mizutani_henro_map import config
from datasets.mizutani_henro_map.normalize import normalize
from datasets.mizutani_henro_map.storage import atomic_write_json


def _metadata(data_dir: str, snapshot: str) -> dict:
    path = os.path.join(config.data_layout(data_dir)["snapshots"], snapshot, "metadata.json")
    with open(path, encoding="utf-8") as stream:
        return json.load(stream)


def _dataset(data_dir: str, snapshot: str) -> dict:
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "normalized.json")
        normalize(data_dir, snapshot=snapshot, output=path)
        with open(path, encoding="utf-8") as stream:
            return json.load(stream)


def _bounds(features: list[dict]) -> list[float] | None:
    coordinates = [feature["geometry"]["coordinates"] for feature in features]
    points = [point for geometry in coordinates for point in (geometry if isinstance(geometry[0], list) else [geometry])]
    if not points:
        return None
    return [min(point[0] for point in points), min(point[1] for point in points),
            max(point[0] for point in points), max(point[1] for point in points)]


def _counts(features: list[dict], field: str) -> dict[str, int]:
    result = {}
    for feature in features:
        value = field(feature) if callable(field) else feature[field]
        result[value] = result.get(value, 0) + 1
    return dict(sorted(result.items()))


def _unclassified(features: list[dict]) -> list[dict]:
    result = {}
    for feature in features:
        if feature["geometry_type"] != "Point" or feature["category"] != "unclassified":
            continue
        item = result.setdefault(feature["style_url"], {"style_url": feature["style_url"], "count": 0, "examples": []})
        item["count"] += 1
        if len(item["examples"]) < 5:
            item["examples"].append({"name": feature["name"], "description": feature["description"]})
    return [result[key] for key in sorted(result, key=lambda value: value or "")]


def generate_update_report(data_dir: str, old_snapshot: str, new_snapshot: str,
                           output: str = "datasets/mizutani_henro_map/output/mizutani-henro-update-report.json") -> dict:
    old, new = _dataset(data_dir, old_snapshot), _dataset(data_dir, new_snapshot)
    old_features = {feature["feature_id"]: feature for feature in old["features"]}
    new_features = {feature["feature_id"]: feature for feature in new["features"]}
    shared = old_features.keys() & new_features.keys()
    changed = []
    for feature_id in sorted(shared):
        old_value = dict(old_features[feature_id])
        new_value = dict(new_features[feature_id])
        old_value.pop("source_order")
        new_value.pop("source_order")
        if old_value != new_value:
            changed.append(feature_id)
    old_bounds, new_bounds = _bounds(old["features"]), _bounds(new["features"])
    report = {
        "schema_version": 1,
        "dataset_id": config.DATASET_ID,
        "old": {"sha256": old_snapshot, "retrieved_at": _metadata(data_dir, old_snapshot)["retrieved_at"]},
        "new": {"sha256": new_snapshot, "retrieved_at": _metadata(data_dir, new_snapshot)["retrieved_at"]},
        "counts": {
            "old": {"points": old["summary"]["point_count"], "line_strings": old["summary"]["line_string_count"], "features": old["summary"]["feature_count"]},
            "new": {"points": new["summary"]["point_count"], "line_strings": new["summary"]["line_string_count"], "features": new["summary"]["feature_count"]},
            "folders": {"old": _counts(old["features"], lambda feature: "/".join(feature["folder_path"])), "new": _counts(new["features"], lambda feature: "/".join(feature["folder_path"]))},
            "categories": {"old": old["summary"]["category_counts"], "new": new["summary"]["category_counts"]},
        },
        "styles": {
            "added": sorted({feature["style_url"] for feature in new["features"]} - {feature["style_url"] for feature in old["features"]}, key=lambda value: value or ""),
            "removed": sorted({feature["style_url"] for feature in old["features"]} - {feature["style_url"] for feature in new["features"]}, key=lambda value: value or ""),
        },
        "features": {"added": sorted(new_features.keys() - old_features.keys()), "removed": sorted(old_features.keys() - new_features.keys()), "changed": changed},
        "bounds": {"old": old_bounds, "new": new_bounds, "changed": old_bounds != new_bounds},
        "new_unclassified_styles": _unclassified(new["features"]),
    }
    atomic_write_json(output, report)
    return report
