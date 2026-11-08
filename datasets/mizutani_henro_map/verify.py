"""Verify raw, normalized, and GeoJSON feature accounting."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from datasets.mizutani_henro_map import config
from datasets.mizutani_henro_map.export_map import export_map
from datasets.mizutani_henro_map.normalize import _snapshot, normalize
from datasets.mizutani_henro_map.parser import resolve_style, validate_source


def _read(path: str) -> dict:
    with open(path, encoding="utf-8") as stream:
        return json.load(stream)


def verify(data_dir: str = config.DEFAULT_DATA_DIR, *, snapshot: str | None = None,
           normalized_path: str = "datasets/mizutani_henro_map/output/mizutani-henro-map.json",
           routes_path: str = "datasets/mizutani_henro_map/output/mizutani-henro-routes.geojson",
           pois_path: str = "datasets/mizutani_henro_map/output/mizutani-henro-pois.geojson",
           report_path: str | None = None) -> dict:
    snapshot, _, raw = _snapshot(data_dir, snapshot)
    parsed = validate_source(raw)
    normalized = _read(normalized_path)
    routes = _read(routes_path).get("features", [])
    pois = _read(pois_path).get("features", [])
    raw_parts = [part for placemark in parsed["placemarks"] for geometry in placemark["geometries"]
                 for part in (geometry["geometries"] if geometry["type"] == "MultiGeometry" else [geometry])]
    raw_points = sum(part["type"] == "Point" for part in raw_parts)
    raw_lines = sum(part["type"] == "LineString" for part in raw_parts)
    normalized_ids = [feature["feature_id"] for feature in normalized["features"]]
    geojson_ids = [feature["properties"].get("feature_id") for feature in routes + pois]
    errors = []
    warnings = []
    if parsed["unsupported_geometry_types"]:
        errors.append("unsupported geometry: %s" % ", ".join(parsed["unsupported_geometry_types"]))
    if any(not placemark["geometries"] for placemark in parsed["placemarks"]):
        errors.append("raw Placemark without supported geometry")
    unresolved = {placemark["style_url"] for placemark in parsed["placemarks"] if placemark["style_url"] and not resolve_style(placemark["style_url"], parsed["styles"], parsed["style_maps"])}
    if unresolved:
        errors.append("unresolved style URLs: %s" % ", ".join(sorted(unresolved)))
    if normalized["source"].get("snapshot_sha256") != snapshot:
        errors.append("normalized snapshot SHA does not match selected raw snapshot")
    if raw_points != sum(feature["geometry_type"] == "Point" for feature in normalized["features"]):
        errors.append("raw/normalized Point count mismatch")
    if raw_lines != sum(feature["geometry_type"] == "LineString" for feature in normalized["features"]):
        errors.append("raw/normalized LineString count mismatch")
    if raw_points != len(pois) or raw_lines != len(routes):
        errors.append("raw/GeoJSON geometry count mismatch")
    if len(normalized_ids) != len(set(normalized_ids)) or len(geojson_ids) != len(set(geojson_ids)):
        errors.append("duplicate feature IDs")
    if set(normalized_ids) != set(geojson_ids):
        errors.append("normalized and GeoJSON feature IDs differ")
    for route in routes:
        props = route["properties"]
        if props.get("route_id") != props.get("feature_id") or props.get("segment_id") != props.get("feature_id"):
            errors.append("route feature %s missing route_id/segment_id equal to feature_id" % props.get("feature_id"))
            break
    with tempfile.TemporaryDirectory(prefix="mizutani-verify-") as directory:
        expected = Path(directory)
        rebuilt = normalize(data_dir, snapshot=snapshot, output=expected / "normalized.json")
        export_map(expected / "normalized.json", routes_path=expected / "routes.geojson",
                   pois_path=expected / "pois.geojson", report_path=expected / "report.json")
        if normalized != rebuilt:
            errors.append("normalized data differs from selected raw source and classification")
        for actual, name in ((routes_path, "routes.geojson"), (pois_path, "pois.geojson")):
            if _read(actual) != _read(expected / name):
                errors.append("%s schema, properties or geometry differ from normalized data" % name)
        if report_path is not None and _read(report_path) != _read(expected / "report.json"):
            errors.append("export report accounting differs from normalized data")
    unclassified = sum(feature["category"] == "unclassified" for feature in normalized["features"] if feature["geometry_type"] == "Point")
    if unclassified:
        warnings.append("%d Point features are unclassified" % unclassified)
    return {
        "ok": not errors,
        "snapshot_sha256": snapshot,
        "raw_placemarks": len(parsed["placemarks"]),
        "raw_points": raw_points,
        "raw_lines": raw_lines,
        "normalized_features": len(normalized["features"]),
        "geojson_routes": len(routes),
        "geojson_pois": len(pois),
        "errors": errors,
        "warnings": warnings,
    }
