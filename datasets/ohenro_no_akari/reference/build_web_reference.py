#!/usr/bin/env python3
"""Statically extract the Henro no Akari web route from a local JavaScript bundle.

Use ``python3 -m datasets.ohenro_no_akari`` to discover and download the current
app module graph, retain immutable HTML/bundle provenance, and publish validated
outputs. This script is the offline extractor; it never downloads or executes JS.
Source styling, stable segment IDs, and the original output schema are retained.
"""
import argparse
import ast
import json
import math
from pathlib import Path
import re
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from datasets._pipeline import atomic_json, digest

APP_URL = "https://app.henro-no-akari.com/"
DATASET = Path(__file__).resolve().parents[1]
TOKEN_RE = re.compile(
    r'(?P<space>\s+)|(?P<comment>//[^\n]*|/\*[\s\S]*?\*/)|'
    r'(?P<string>"(?:\\[\s\S]|[^"\\])*"|\'(?:\\[\s\S]|[^\'\\])*\')|'
    r'(?P<template>`(?:\\[\s\S]|[^`\\])*`)|'
    r'(?P<identifier>[A-Za-z_$][\w$]*)|'
    r'(?P<number>-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)|'
    r'(?P<punct>[\s\S])'
)
REGEX_RE = re.compile(r"/(?:\\[^\n]|\[(?:\\[^\n]|[^\]\\\n])*\]|[^/\\\n])+/[a-z]*")
EXPRESSION_PREFIXES = {"", "=", "(", "[", "{", ":", ",", ";", "!", "?", "&", "|",
                       "+", "-", "*", "%", "/", "~", ">", "return", "throw", "case", "typeof", "void", "delete"}


def tokens(text):
    """Yield lexical tokens without interpreting strings, templates, or regexes."""
    position = 0
    previous = ""
    while position < len(text):
        if (text[position] == "/" and not text.startswith(("//", "/*"), position) and
                previous in EXPRESSION_PREFIXES):
            regex = REGEX_RE.match(text, position)
            if regex:
                yield "regex", regex.group(), position, regex.end()
                position = regex.end()
                previous = "regex"
                continue
        match = TOKEN_RE.match(text, position)
        position = match.end()
        kind = match.lastgroup
        if kind not in ("space", "comment"):
            previous = match.group()
            yield kind, previous, match.start(), position


def string_value(token):
    # literal_eval parses a string only; neither parser evaluates JavaScript.
    return json.loads(token) if token.startswith('"') else ast.literal_eval(token)


def module_imports(text):
    """Collect literal static and dynamic ES module dependencies without JS eval."""
    previous = []
    imports = set()
    for kind, value, _, _ in tokens(text):
        if kind == "string" and (previous[-1:] in (["from"], ["import"]) or
                                 previous[-2:] == ["import", "("]):
            imports.add(string_value(value))
        previous = (previous + [value])[-2:]
    return sorted(imports)


def quote_js_object_literal(text):
    """Turn static JS object keys, strings, and leading-dot numbers into JSON."""
    source_tokens = list(tokens(text))
    out = []
    for i, (kind, value, _, _) in enumerate(source_tokens):
        if kind == "string":
            out.append(json.dumps(string_value(value), ensure_ascii=False))
        elif kind == "identifier" and i + 1 < len(source_tokens) and source_tokens[i + 1][1] == ":":
            out.append(json.dumps(value))
        elif kind == "number" and value.startswith((".", "-.")):
            out.append(value.replace(".", "0.", 1))
        elif kind == "template":
            raise ValueError("Template expression in route data is not static JSON")
        else:
            out.append(value)
    return "".join(out)


def route_arrays(bundle):
    """Find every array containing direct GeoJSON Features, balancing strings safely.

    Mark all Feature arrays, not just valid LineStrings: a malformed second array
    must not silently disappear while a plausible first array is published.
    """
    stack = []
    previous = []
    arrays = []
    for kind, value, start, end in tokens(bundle):
        if value in ("[", "{") and kind == "punct":
            stack.append({"kind": value, "start": start, "feature": False})
        elif value in ("]", "}") and kind == "punct":
            expected = "[" if value == "]" else "{"
            if stack and stack[-1]["kind"] == expected:
                opened = stack.pop()
                if opened["kind"] == "[" and opened["feature"]:
                    arrays.append(bundle[opened["start"]:end])
        elif (kind == "string" and value in ('"Feature"', "'Feature'") and
              len(previous) == 2 and previous[-1] == ":" and previous[-2] in ("type", '"type"', "'type'") and
              len(stack) >= 2 and stack[-1]["kind"] == "{" and stack[-2]["kind"] == "["):
            stack[-2]["feature"] = True
        previous = (previous + [value])[-2:]
    if any(item["feature"] for item in stack):
        raise ValueError("Unbalanced route array in JavaScript bundle")
    return arrays


def extract_route_array(bundle):
    arrays = route_arrays(bundle)
    if len(arrays) != 1:
        raise ValueError(f"Expected exactly one complete route array, found {len(arrays)}")
    return arrays[0]


def great_circle_length_m(points):
    total = 0.0
    for a, b in zip(points, points[1:]):
        lat1, lon1, lat2, lon2 = map(math.radians, (a[1], a[0], b[1], b[0]))
        h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
        total += 2 * 6371000.0 * math.asin(min(1.0, math.sqrt(h)))
    return total


def accounting(features):
    if not isinstance(features, list) or not features:
        raise ValueError("Empty or invalid route features")
    west = south = float("inf")
    east = north = float("-inf")
    points = 0
    length = 0.0
    for feature in features:
        if (not isinstance(feature, dict) or feature.get("type") != "Feature" or
                not isinstance(feature.get("properties"), dict) or
                not isinstance(feature.get("geometry"), dict) or
                feature["geometry"].get("type") != "LineString"):
            raise ValueError("Expected only complete GeoJSON LineString Features")
        coords = feature["geometry"].get("coordinates")
        if not isinstance(coords, list) or len(coords) < 2:
            raise ValueError("Degenerate route segment")
        for coordinate in coords:
            if (not isinstance(coordinate, list) or len(coordinate) not in (2, 3) or
                    not all(type(v) in (int, float) and math.isfinite(v) for v in coordinate) or
                    not (131 < coordinate[0] < 136 and 31.5 < coordinate[1] < 35.5)):
                raise ValueError("Invalid Shikoku route coordinate")
            west, south = min(west, coordinate[0]), min(south, coordinate[1])
            east, north = max(east, coordinate[0]), max(north, coordinate[1])
        segment_length = great_circle_length_m(coords)
        if segment_length <= 0:
            raise ValueError("Zero-length route segment")
        points += len(coords)
        length += segment_length
    return {"feature_count": len(features), "point_count": points,
            "total_length_m": round(length, 2), "bounds": [west, south, east, north]}


def build_route(bundle_text, source_url=APP_URL):
    features = json.loads(quote_js_object_literal(extract_route_array(bundle_text)))
    counts = accounting(features)
    out_features = []
    for i, feature in enumerate(features):
        coords = feature["geometry"]["coordinates"]
        properties = dict(feature["properties"])
        properties.update(id=f"henro-no-akari-{i:04d}", index=i,
                          num_points=len(coords), length_m=round(great_circle_length_m(coords), 2))
        out_features.append({"type": "Feature", "properties": properties, "geometry": feature["geometry"]})
    return {"type": "FeatureCollection", "name": "henro-no-akari-route", "features": out_features}, {
        "schema_version": 1,
        "kind": "ohenro_no_akari_web_route_reference",
        "source_name": "遍路のあかり+ (jp.co.yonden.henronoakari) web app",
        "source_url": source_url,
        "projection": "EPSG:4326 (WGS84)",
        "note": (
            "Walking pilgrim route embedded in the Henro no Akari web app Leaflet map bundle. "
            "Road-level LineString segments with Leaflet styling props preserved. "
            "NOT official and NOT a navigation guarantee; use as an independent reference "
            "for cross-checking arukihenro_routes / datasets.sekaiisan_henro."
        ),
        "accounting": counts,
    }


def validate_route(collection, manifest):
    if collection.get("type") != "FeatureCollection" or collection.get("name") != "henro-no-akari-route":
        raise ValueError("Invalid route collection")
    features = collection["features"]
    counts = accounting(features)
    if manifest.get("accounting") != counts:
        raise ValueError("Route manifest accounting differs from geometry")
    for i, feature in enumerate(features):
        props = feature["properties"]
        coords = feature["geometry"]["coordinates"]
        if (props.get("id") != f"henro-no-akari-{i:04d}" or props.get("index") != i or
                props.get("num_points") != len(coords) or
                props.get("length_m") != round(great_circle_length_m(coords), 2)):
            raise ValueError("Route segment identity or accounting mismatch")
    if (manifest.get("schema_version") != 1 or manifest.get("kind") != "ohenro_no_akari_web_route_reference" or
            not isinstance(manifest.get("source_url"), str)):
        raise ValueError("Invalid route manifest schema")
    return counts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=Path(__file__).parent / "data/MapPage.js")
    parser.add_argument("--source-url", default=APP_URL, help="original URL of the local bundle")
    parser.add_argument("--out-dir", type=Path, default=DATASET / "output")
    args = parser.parse_args(argv)
    collection, manifest = build_route(args.bundle.read_text(encoding="utf-8"), args.source_url)
    manifest["source_sha256"] = digest(args.bundle)
    validate_route(collection, manifest)
    atomic_json(args.out_dir / "henro-no-akari-route.geojson", collection)
    atomic_json(args.out_dir / "manifest.json", manifest)
    print(json.dumps(manifest["accounting"], ensure_ascii=False))


if __name__ == "__main__":
    main()
