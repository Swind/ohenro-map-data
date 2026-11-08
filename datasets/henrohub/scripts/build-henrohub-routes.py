#!/usr/bin/env python3
"""Convert henrohub (henro.app) route network to a map-preview GeoJSON.

Reads the henrohub planner GeoJSON (route.planner.geojson) and emits a
deterministic, byte-stable FeatureCollection aligned with map-preview's
existing route-layer conventions: `kind=line`, stable `route_id`,
`route_role` (canonical_shikoku88 / unique_alternative / transition_connector / continuity_fallback), `route_class`
(colour), `route_sets`, a human-readable `name`, and the elevation summary
fields that henrohub already computes per feature.

The henrohub data is Henro Hub's own digitised network (NOT the repo's Henro
Helper extraction; see datasets/henrohub/docs/henro-hub-comparison.md). Licensing of the
downstream data is not covered by this repo; see the comparison report.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from collections import Counter

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from datasets.henrohub.validation import validate_routes

ROLE_ORDER = ["canonical_shikoku88", "unique_alternative",
              "transition_connector", "continuity_fallback"]

ROLE_LABEL = {
    "canonical_shikoku88": "main",
    "unique_alternative": "alternative",
    "transition_connector": "connector",
    "continuity_fallback": "fallback",
}

CLASS_LABEL = {
    "black": "black (mainline)",
    "red": "red (busy/high stress)",
    "green": "green (trail)",
    "blue": "blue (path)",
    "purple": "purple (scenic)",
    "special": "special (ferry/cable)",
}


def display_name(rid: str) -> str:
    """Derive a short readable name from henrohub route_feature_id.

    Examples:
      shikoku88-temple-01-to-temple-02__class_002 -> "1 → 2"
      hrn_<uuid> -> fall back to the id's tail.
    """
    m = re.search(r"temple-(\d+)-to-temple-(\d+)", rid)
    if m:
        return f"{int(m.group(1))} → {int(m.group(2))}"
    if rid.startswith("hrn_"):
        return rid[:8]
    return rid


def convert(src: str, dst: str) -> dict:
    with open(src, encoding="utf-8") as fh:
        data = json.load(fh)
    validate_routes(data, planner=True)

    features = []
    counts = Counter()
    for f in data.get("features", []):
        props = f.get("properties", {})
        rid = props.get("route_feature_id") or f.get("id")
        geom = f.get("geometry")
        role = props.get("route_role", "other")
        route_class = props.get("effective_route_class") or "other"
        counts[(role, route_class)] += 1
        features.append({
            "type": "Feature",
            "id": rid,
            "properties": {
                "kind": "line",
                "route_id": rid,
                "route_role": role,
                "route_class": route_class,
                "route_sets": props.get("route_set_ids") or [],
                "name": display_name(rid),
                "elevation_min_m": props.get("elevation_min_m"),
                "elevation_max_m": props.get("elevation_max_m"),
                "ascent_m": props.get("ascent_m"),
                "descent_m": props.get("descent_m"),
                "length_m": props.get("length_m"),
            },
            "geometry": geom,
        })

    out = {
        "type": "FeatureCollection",
        "name": "henrohub",
        "features": features,
    }
    validate_routes(out)
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    with open(dst, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, separators=(",", ":"))
    return {
        "input": src,
        "output": dst,
        "feature_count": len(features),
        "role_class_counts": {
            f"{r} / {c}": n for (r, c), n in sorted(counts.items())
        },
    }


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else (
        str(Path(__file__).resolve().parents[1] / "raw" / "planner.geojson"))
    dst = sys.argv[2] if len(sys.argv) > 2 else (
        str(Path(__file__).resolve().parents[1] / "output" / "henrohub-routes.geojson"))
    report = convert(src, dst)
    print(json.dumps(report, indent=2, ensure_ascii=False))
