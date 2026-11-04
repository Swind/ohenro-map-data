#!/usr/bin/env python3
"""Build Henro no Akari (Yonden, jp.co.yonden.henronoakari) web route reference.

The native app (遍路のあかり+) itself embeds no route geometry: its Dart AOT
(libapp.so) only carries URL fragments for Google Maps directions
(`google.com` + `/maps/dir` + `destination`, see analysis), and temples/spots
are fetched from the CMS at runtime. The walking pilgrim route is published in
the companion web app at https://app.henro-no-akari.com: the Leaflet map page
bundle embeds the full route as an inline GeoJSON object literal.

Input (immutable snapshot):
  - https://app.henro-no-akari.com/assets/MapPage.js
    cached at datasets/ohenro_no_akari/reference/data/MapPage.js (gitignored,
    re-fetchable). The route is a top-level `const <name>=[{type:"Feature",...}`
    array of LineString features (Leaflet styling props `_color/_opacity/_weight`).

Outputs (deterministic, no timestamps, atomic writes):
  - datasets/ohenro_no_akari/output/henro-no-akari-route.geojson
      FeatureCollection with per-feature stable ids and per-route stats.
  - datasets/ohenro_no_akari/output/manifest.json
      Source URL + bundle SHA-256 + feature/point/length/bounds accounting.

The bundle is minified JavaScript, so object keys may be unquoted; a small
tokenizer re-quotes keys before feeding the literal to json.
"""
import argparse
import hashlib
import json
import os
import re
import tempfile
import urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
BUNDLE_PATH = os.path.join(DATA_DIR, "MapPage.js")
OUT_DIR = os.path.join(SCRIPT_DIR, "..", "output")
BUNDLE_URL = "https://app.henro-no-akari.com/assets/MapPage.js"

ARRAY_RE = re.compile(r'=\s*(\[\{type:"Feature")')


def quote_js_object_literal(text):
    """Re-quote unquoted JS object keys so the literal is valid JSON.

    Only touches identifier keys followed by ':' outside string literals;
    bare identifiers (true/false/null) are passed through unchanged.
    """
    out = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == '"':
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == '"':
                    j += 1
                    break
                j += 1
            out.append(text[i:j])
            i = j
        elif c in "{}[],:":
            out.append(c)
            i += 1
        elif c.isdigit() or c in "+-.":
            if c == "." and (i == 0 or text[i - 1] in ":,["):
                out.append("0")
            j = i
            while j < n and (text[j].isdigit() or text[j] in ".+-eE"):
                j += 1
            out.append(text[i:j])
            i = j
        elif c.isalpha() or c in "_$":
            j = i
            while j < n and (text[j].isalnum() or text[j] in "_$"):
                j += 1
            ident = text[i:j]
            k = j
            while k < n and text[k] in " \t\n":
                k += 1
            if k < n and text[k] == ":":
                out.append('"' + ident + '"')
            else:
                out.append(ident)
            i = j
        else:
            out.append(c)
            i += 1
    return "".join(out)


def extract_route_array(bundle):
    """Return the raw route array text (balanced brackets) from the bundle."""
    m = ARRAY_RE.search(bundle)
    if not m:
        raise SystemExit("route array (=[{type:\"Feature\") not found in MapPage.js")
    start = m.start(1)
    depth = 0
    i = start
    while i < len(bundle):
        if bundle[i] == "[":
            depth += 1
        elif bundle[i] == "]":
            depth -= 1
            if depth == 0:
                return bundle[start:i + 1]
        i += 1
    raise SystemExit("unbalanced route array in MapPage.js")


def great_circle_length_m(points):
    import math
    r = 6371000.0
    total = 0.0
    for a, b in zip(points, points[1:]):
        lat1, lon1, lat2, lon2 = (
            math.radians(a[1]),
            math.radians(a[0]),
            math.radians(b[1]),
            math.radians(b[0]),
        )
        h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
        total += 2 * r * math.asin(math.sqrt(h))
    return total


def build_route(bundle_text):
    raw = extract_route_array(bundle_text)
    features = json.loads(quote_js_object_literal(raw))
    out_features = []
    min_lng = min_lat = float("inf")
    max_lng = max_lat = float("-inf")
    total_pts = 0
    total_len = 0.0
    for i, f in enumerate(features):
        coords = f["geometry"]["coordinates"]
        for p in coords:
            min_lng, min_lat = min(min_lng, p[0]), min(min_lat, p[1])
            max_lng, max_lat = max(max_lng, p[0]), max(max_lat, p[1])
        total_pts += len(coords)
        total_len += great_circle_length_m(coords)
        props = dict(f.get("properties", {}))
        props["id"] = f"henro-no-akari-{i:04d}"
        props["index"] = i
        props["num_points"] = len(coords)
        props["length_m"] = round(great_circle_length_m(coords), 2)
        out_features.append({
            "type": "Feature",
            "properties": props,
            "geometry": f["geometry"],
        })
    return {
        "type": "FeatureCollection",
        "name": "henro-no-akari-route",
        "features": out_features,
    }, {
        "schema_version": 1,
        "kind": "ohenro_no_akari_web_route_reference",
        "source_name": "遍路のあかり+ (jp.co.yonden.henronoakari) web app",
        "source_url": BUNDLE_URL,
        "projection": "EPSG:4326 (WGS84)",
        "note": (
            "Walking pilgrim route embedded in the Henro no Akari web app "
            "Leaflet map bundle. Road-level LineString segments with Leaflet "
            "styling props preserved. NOT official and NOT a navigation "
            "guarantee; use as an independent reference for cross-checking "
            "arukihenro_routes / datasets.sekaiisan_henro."
        ),
        "accounting": {
            "feature_count": len(out_features),
            "point_count": total_pts,
            "total_length_m": round(total_len, 2),
            "bounds": [min_lng, min_lat, max_lng, max_lat],
        },
    }


def atomic_write_json(path, data):
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".henro-no-akari-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", default=BUNDLE_PATH,
                        help="local MapPage.js snapshot (default: %(default)s)")
    parser.add_argument("--fetch", action="store_true",
                        help="download the bundle into data/ (default if missing)")
    parser.add_argument("--force", action="store_true",
                        help="re-download the bundle even if data/MapPage.js exists")
    parser.add_argument("--out-dir", default=OUT_DIR,
                        help="output directory (default: %(default)s)")
    args = parser.parse_args()

    bundle_path = args.bundle
    if args.force or (args.fetch and not os.path.exists(bundle_path)):
        os.makedirs(DATA_DIR, exist_ok=True)
        with urllib.request.urlopen(BUNDLE_URL, timeout=60) as resp, \
                open(bundle_path, "wb") as handle:
            data = resp.read()
            handle.write(data)
        print(f"fetched {BUNDLE_URL} -> {bundle_path} ({len(data)} bytes)")
    if not os.path.exists(bundle_path):
        raise SystemExit(f"bundle not found: {bundle_path} (use --fetch to download)")

    with open(bundle_path, "rb") as f:
        bundle_bytes = f.read()
    sha256 = hashlib.sha256(bundle_bytes).hexdigest()
    bundle_text = bundle_bytes.decode("utf-8")

    fc, manifest = build_route(bundle_text)
    manifest["source_sha256"] = sha256

    os.makedirs(args.out_dir, exist_ok=True)
    geojson_path = os.path.join(args.out_dir, "henro-no-akari-route.geojson")
    manifest_path = os.path.join(args.out_dir, "manifest.json")
    atomic_write_json(geojson_path, fc)
    atomic_write_json(manifest_path, manifest)

    acc = manifest["accounting"]
    print(f"features={acc['feature_count']} points={acc['point_count']} "
          f"length_km={acc['total_length_m']/1000:.1f}")
    print(f"bounds={acc['bounds']}")
    print(f"sha256={sha256}")
    print(f"  -> {geojson_path}")
    print(f"  -> {manifest_path}")


if __name__ == "__main__":
    main()