#!/usr/bin/env python3
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
IN = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'datasets/seichijunrei/output/temples.json')
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, 'datasets/seichijunrei/output/temples.geojson')

with open(IN, encoding="utf-8") as f:
    temples = json.load(f)

features = []
for t in temples:
    features.append({
        "type": "Feature",
        "id": t["id"],
        "geometry": {
            "type": "Point",
            "coordinates": [t["location"]["longitude"], t["location"]["latitude"]],
        },
        "properties": {
            "id": t["id"],
            "type": "temple",
            "number": t["number"],
            "name_ja": t["name"]["ja"],
            "name_en": t["name"]["en"],
            "name_kana": t["name"]["kana"],
        },
    })

geojson = {
    "type": "FeatureCollection",
    "features": features,
}

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(geojson, f, ensure_ascii=False, indent=2)

print(f"generated {len(features)} features -> {OUT}")
