"""Offline normalization of the 歩き遍路 Google My Maps KML archive."""

from __future__ import annotations

import os
from collections import Counter

from arukihenro_routes.kml import parse_kml
from arukihenro_routes.storage import atomic_write_json, read_json
from arukihenro_routes.temple_range import parse_temple_range

SOURCE = "https://ohenro.jp/blog/arukihenro/"
SCHEMA_VERSION = 1


def _load_kml(data_dir: str, local_path: str, warnings: list[str], route_id: str, map_id: str) -> dict:
    empty = {"name": None, "description": None, "lines": [], "points": []}
    path = os.path.join(data_dir, local_path)
    try:
        with open(path, "rb") as stream:
            return parse_kml(stream.read())
    except Exception as error:
        warnings.append("route %s map %s KML: %s" % (route_id, map_id, error))
        return empty


def normalize_archive(data_dir: str, output: str) -> dict:
    """Normalize the archive into schema version 1 and atomically write it."""
    manifest_path = os.path.join(data_dir, "manifest.json")
    if not os.path.isfile(manifest_path):
        raise FileNotFoundError("required archive manifest not found: %s" % manifest_path)
    manifest = read_json(manifest_path)
    warnings: list[str] = []
    routes = []

    for route in manifest.get("routes", []):
        route_id = route.get("id")
        maps = []
        for map_data in route.get("maps", []):
            map_id = map_data.get("map_id")
            kml = _load_kml(data_dir, map_data.get("local_path", ""), warnings, route_id, map_id)
            from_temple, to_temple, temple_range = parse_temple_range(kml["name"])
            maps.append({
                "map_id": map_id,
                "map_name": kml["name"],
                "map_description": kml["description"],
                "from_temple": from_temple,
                "to_temple": to_temple,
                "temple_range": temple_range,
                "lines": kml["lines"],
                "points": kml["points"],
            })
        from_temple, to_temple, temple_range = parse_temple_range(route.get("title"))
        routes.append({
            "id": route_id,
            "region": route.get("region"),
            "title": route.get("title"),
            "url": route.get("url"),
            "from_temple": from_temple,
            "to_temple": to_temple,
            "temple_range": temple_range,
            "maps": maps,
        })

    line_count = sum(len(m["lines"]) for r in routes for m in r["maps"])
    point_count = sum(len(m["points"]) for r in routes for m in r["maps"])
    photo_count = sum(
        1 for r in routes for m in r["maps"] for p in m["points"] if p["photos"]
    )
    category_counts = Counter(
        p["category"] for r in routes for m in r["maps"] for p in m["points"]
    )

    summary = {
        "route_count": len(routes),
        "map_count": sum(len(r["maps"]) for r in routes),
        "line_count": line_count,
        "point_count": point_count,
        "photo_point_count": photo_count,
        "temple_range_count": sum(1 for r in routes if r["temple_range"]),
        "category_counts": dict(sorted(category_counts.items())),
        "warning_count": len(warnings),
    }
    dataset = {
        "schema_version": SCHEMA_VERSION,
        "source": SOURCE,
        "summary": summary,
        "warnings": warnings,
        "routes": routes,
    }
    atomic_write_json(os.path.abspath(output), dataset)
    return summary