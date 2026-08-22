"""Export normalized Mizutani features as route and POI GeoJSON layers."""

from __future__ import annotations

import json

from mizutani_henro_map.storage import atomic_write_json


def _collection(features: list[dict]) -> dict:
    return {"type": "FeatureCollection", "features": features}


def export_map(input_path: str = "output/mizutani-henro-map.json", *,
               routes_path: str = "output/mizutani-henro-routes.geojson",
               pois_path: str = "output/mizutani-henro-pois.geojson",
               report_path: str = "output/mizutani-henro-report.json") -> dict:
    with open(input_path, encoding="utf-8") as stream:
        normalized = json.load(stream)
    routes, pois = [], []
    for feature in normalized["features"]:
        folder = "/".join(feature["folder_path"])
        if feature["geometry_type"] == "LineString":
            route_kind = {"88route": "source_88route", "20route": "source_20route", "sub route": "alternate"}.get(folder, "other")
            routes.append({"type": "Feature", "geometry": feature["geometry"], "properties": {
                "feature_id": feature["feature_id"], "name": feature["name"], "folder": folder,
                "route_kind": route_kind, "style_url": feature["style_url"], "color": feature["line_color"],
                "width": feature["line_width"], "description": feature["description"], "source": normalized["dataset_id"],
            }})
        elif feature["geometry_type"] == "Point":
            pois.append({"type": "Feature", "geometry": feature["geometry"], "properties": {
                "feature_id": feature["feature_id"], "name": feature["name"], "description": feature["description"],
                "url": feature["links"][0] if len(feature["links"]) == 1 else None, "folder": folder,
                "category": feature["category"], "icon": feature["icon"], "style_url": feature["style_url"],
                "icon_id": feature["icon_id"], "color": feature["color"], "source": normalized["dataset_id"],
            }})
        else:
            raise ValueError("unsupported normalized geometry %s" % feature["geometry_type"])
    report = {
        "schema_version": 1,
        "dataset_id": normalized["dataset_id"],
        "snapshot_sha256": normalized["source"]["snapshot_sha256"],
        "raw_placemarks": normalized["summary"]["placemark_count"],
        "normalized_features": len(normalized["features"]),
        "routes": len(routes),
        "pois": len(pois),
        "category_counts": normalized["summary"]["category_counts"],
        "unknown_route_folders": sorted({feature["properties"]["folder"] for feature in routes if feature["properties"]["route_kind"] == "other"}),
    }
    if len({feature["properties"]["feature_id"] for feature in routes + pois}) != len(routes) + len(pois):
        raise ValueError("duplicate feature IDs")
    if report["routes"] != normalized["summary"]["line_string_count"] or report["pois"] != normalized["summary"]["point_count"]:
        raise ValueError("GeoJSON accounting mismatch")
    atomic_write_json(routes_path, _collection(routes))
    atomic_write_json(pois_path, _collection(pois))
    atomic_write_json(report_path, report)
    return report
