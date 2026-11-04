#!/usr/bin/env python3
"""Build OHenro 88 (com.sallyzzz.ohenroapp) route reference data.

Inputs (immutable, extracted from the APK into datasets/ohenro88/reference/data/):
  - trails_all.geojson : 108 temple points + 160 walking lines (3D [lon,lat,elev])
  - merged.json        : 110 merged display routes (88 main + 17 bekkaku extra + 5 extra)

Outputs (deterministic, no timestamps, atomic writes):
  - datasets/ohenro88/output/ohenro88-routes.geojson
      Every line + point feature from trails_all (plus the merged-only main
      routes and the 88-1 closure) with stable ids and per-route stats, for
      the map preview's per-route selector.
  - datasets/ohenro88/output/ohenro88-sections.json
      88 adjacent temple-section references (SEC_1_2 .. SEC_88_1), each with
      geometry, computed length_m, elevation profile and endpoints, so it can
      be cross-checked against the sekaiisan_henro build-sections output.
"""
import argparse
import json
import math
import os
import re
import tempfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
OUT_DIR = os.path.join(SCRIPT_DIR, "..", "output")

NAME_RE = re.compile(r"^Walking (?:bekkaku )?(?:extra )?\((\d+|\d+-)?[^-]*\)")
PAIR_RE = re.compile(r"^Walking (.*?)\s*\(([0-9]+|[A-Za-z]*\d+)-([0-9]+|[A-Za-z]*\d+)\)$")


def flatten_points(geometry):
    """Return all points of a LineString / MultiLineString in order."""
    if geometry["type"] == "MultiLineString":
        return [p for part in geometry["coordinates"] for p in part]
    return geometry["coordinates"]


def route_type_of(name):
    if "skip" in name:
        return "skip"
    if "bekkaku extra" in name or "bakkaku extra" in name:
        return "bekkaku_extra"
    if "bekkaku" in name or "bakkaku" in name:
        return "bekkaku"
    if "extra" in name:
        return "extra"
    return "main"


def route_id(name):
    """Stable route id derived from the app's route name."""
    m = PAIR_RE.match(name)
    if m:
        kind = route_type_of(name)
        frm, to = m.group(2), m.group(3)
        suffix = "" if kind == "main" else f"_{kind}"
        return f"OH88_{frm}_{to}{suffix}"
    slug = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")
    return f"OH88_{slug}"


def great_circle_length_m(points):
    r = 6371000.0
    total = 0.0
    for a, b in zip(points, points[1:]):
        lat1, lon1, lat2, lon2 = (
            math.radians(a[1]),
            math.radians(a[0]),
            math.radians(b[1]),
            math.radians(b[0]),
        )
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        total += 2 * r * math.asin(math.sqrt(h))
    return total


def elevation_stats(points):
    elevs = [p[2] for p in points if len(p) >= 3]
    if not elevs:
        return None
    gain = 0.0
    loss = 0.0
    for a, b in zip(elevs, elevs[1:]):
        d = b - a
        if d > 0:
            gain += d
        else:
            loss += -d
    return {
        "start_m": elevs[0],
        "end_m": elevs[-1],
        "min_m": min(elevs),
        "max_m": max(elevs),
        "mean_m": round(sum(elevs) / len(elevs), 2),
        "gain_m": round(gain, 2),
        "loss_m": round(loss, 2),
    }


def parse_declared_km(desc):
    if not desc:
        return None
    m = re.search(r"([\d.]+) km", desc)
    return float(m.group(1)) if m else None


def atomic_write_json(path, data):
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".ohenro88-", suffix=".tmp")
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


def build_features(trails, merged):
    """Build a single GeoJSON FeatureCollection of all lines + temple points."""
    features = []

    def push(f):
        features.append(f)

    # Temple points first (from trails_all).
    for f in trails["features"]:
        if f["geometry"]["type"] != "Point":
            continue
        props = f.get("properties", {})
        number = props.get("templeNumber")
        name = props.get("name")
        is_bekkaku = number is None
        push({
            "type": "Feature",
            "properties": {
                "route_id": route_id(f"Temple {name}"),
                "kind": "point",
                "name": name,
                "temple_number": number,
                "bekkaku": is_bekkaku,
            },
            "geometry": {
                "type": "Point",
                "coordinates": [f["geometry"]["coordinates"][0], f["geometry"]["coordinates"][1]],
            },
        })

    # Lines from trails_all (all variants).
    seen = set()
    for f in trails["features"]:
        if f["geometry"]["type"] == "Point":
            continue
        name = f.get("properties", {}).get("name")
        if not name:
            continue
        points = flatten_points(f["geometry"])
        rid = route_id(name)
        stats = elevation_stats(points)
        props = {
            "route_id": rid,
            "kind": "line",
            "name": name,
            "route_type": route_type_of(name),
            "length_m": round(great_circle_length_m(points), 2),
            "num_points": len(points),
        }
        if stats:
            props.update({f"elevation_{k}": v for k, v in stats.items()})
        if rid in seen:
            # Duplicate route name across files: merge only if the trail file's
            # variant is preferred (it is the raw geometry source).
            continue
        seen.add(rid)
        push({
            "type": "Feature",
            "properties": props,
            "geometry": f["geometry"],
        })

    # Merged-only routes: the 11 skip-alternate mains and the 88-1 closure that
    # trails_all does not carry under the main Walking (X-Y) name.
    for f in merged["features"]:
        name = f.get("properties", {}).get("name")
        if not name:
            continue
        rid = route_id(name)
        if rid in seen:
            continue
        points = flatten_points(f["geometry"])
        stats = elevation_stats(points)
        props = {
            "route_id": rid,
            "kind": "line",
            "name": name,
            "route_type": route_type_of(name),
            "length_m": round(great_circle_length_m(points), 2),
            "num_points": len(points),
        }
        if stats:
            props.update({f"elevation_{k}": v for k, v in stats.items()})
        seen.add(rid)
        push({
            "type": "Feature",
            "properties": props,
            "geometry": f["geometry"],
        })

    features.sort(key=lambda f: f["properties"].get("route_id", ""))
    return {"type": "FeatureCollection", "features": features}


def build_sections(trails, merged):
    """Build the 88 adjacent-section references (SEC_1_2 .. SEC_88_1)."""
    def find_in(fc, name):
        for f in fc["features"]:
            if f.get("properties", {}).get("name") == name:
                return f
        return None

    sections = []
    for i in range(1, 88):
        frm, to = i, i + 1
        name = f"Walking ({frm}-{to})"
        trail_f = find_in(trails, name)
        merged_f = find_in(merged, name)
        # Prefer the trails_all geometry (raw source); fall back to merged.json
        # for the 11 pairs that only exist as "skip" in trails_all.
        source = None
        if trail_f:
            source, geometry = "trails_all", trail_f["geometry"]
        elif merged_f:
            source, geometry = "merged", merged_f["geometry"]
        else:
            skip_f = find_in(trails, f"{name} skip")
            if skip_f:
                source, geometry = "trails_all_skip", skip_f["geometry"]
            else:
                continue
        points = flatten_points(geometry)
        stats = elevation_stats(points)
        declared = None
        for candidate in (trail_f, merged_f):
            if candidate:
                declared = parse_declared_km(candidate.get("properties", {}).get("desc"))
                if declared:
                    break
        num_parts = (
            len(geometry["coordinates"]) if geometry["type"] == "MultiLineString" else 1
        )
        section = {
            "id": f"SEC_{frm}_{to}",
            "from_temple": frm,
            "to_temple": to,
            "source_route": name,
            "geometry_source": source,
            "declared_length_km": declared,
            "length_m": round(great_circle_length_m(points), 2),
            "num_parts": num_parts,
            "fragmented": num_parts > 1,
            "num_points": len(points),
            "geometry": geometry,
        }
        if stats:
            section["elevation"] = stats
            section["endpoints"] = {
                "start": points[0],
                "end": points[-1],
            }
        sections.append(section)

    # Closure 88 -> 1 (only present in merged.json as a main route).
    name = "Walking (88-1)"
    closure_f = find_in(merged, name)
    if closure_f:
        points = flatten_points(closure_f["geometry"])
        stats = elevation_stats(points)
        num_parts = (
            len(closure_f["geometry"]["coordinates"])
            if closure_f["geometry"]["type"] == "MultiLineString"
            else 1
        )
        closure = {
            "id": "SEC_88_1",
            "from_temple": 88,
            "to_temple": 1,
            "source_route": name,
            "geometry_source": "merged",
            "declared_length_km": parse_declared_km(closure_f.get("properties", {}).get("desc")),
            "length_m": round(great_circle_length_m(points), 2),
            "num_parts": num_parts,
            "fragmented": num_parts > 1,
            "num_points": len(points),
            "geometry": closure_f["geometry"],
        }
        if stats:
            closure["elevation"] = stats
            closure["endpoints"] = {"start": points[0], "end": points[-1]}
    else:
        closure = {
            "id": "SEC_88_1",
            "from_temple": 88,
            "to_temple": 1,
            "source_route": name,
            "geometry_source": None,
            "declared_length_km": None,
            "length_m": None,
            "num_parts": 0,
            "fragmented": False,
            "num_points": 0,
            "geometry": None,
        }

    return {
        "schema_version": 1,
        "kind": "ohenro88_section_reference",
        "dataset": "com.sallyzzz.ohenroapp (OHenro 88) 1.1.0 APKPure XAPK",
        "projection": "EPSG:4326 (WGS84) + elevation_m (third coordinate)",
        "note": (
            "Independent per-adjacent-temple walking-route reference extracted "
            "from the OHenro 88 app. Length/elevation computed from the app's "
            "own 3D geometry; NOT official and NOT a navigation guarantee. "
            "Use for cross-checking build-sections / build-section-corridors."
        ),
        "sections": sections,
        "closure_88_1": closure,
        "accounting": {
            "section_count": len(sections),
            "main_route_count": len(sections),
            "line_feature_count": None,
            "declared_length_total_km": round(
                sum(s["declared_length_km"] for s in sections if s["declared_length_km"]) or 0.0,
                2,
            ),
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=DATA_DIR, help="input data dir (default: %(default)s)")
    parser.add_argument("--out-dir", default=OUT_DIR, help="output dir (default: %(default)s)")
    args = parser.parse_args()

    with open(os.path.join(args.data_dir, "trails_all.geojson"), encoding="utf-8") as f:
        trails = json.load(f)
    with open(os.path.join(args.data_dir, "merged.json"), encoding="utf-8") as f:
        merged = json.load(f)

    os.makedirs(args.out_dir, exist_ok=True)

    fc = build_features(trails, merged)
    lines = [f for f in fc["features"] if f["properties"]["kind"] == "line"]
    points = [f for f in fc["features"] if f["properties"]["kind"] == "point"]
    atomic_write_json(os.path.join(args.out_dir, "ohenro88-routes.geojson"), fc)

    sections = build_sections(trails, merged)
    sections["accounting"]["line_feature_count"] = len(lines)
    sections["accounting"]["point_feature_count"] = len(points)
    sections["accounting"]["declared_length_total_km"] = round(
        sum(s["declared_length_km"] for s in sections["sections"] if s["declared_length_km"]) or 0.0,
        2,
    )
    atomic_write_json(os.path.join(args.out_dir, "ohenro88-sections.json"), sections)

    print(f"lines={len(lines)} points={len(points)} sections={len(sections['sections'])}")
    print(f"  -> {os.path.join(args.out_dir, 'ohenro88-routes.geojson')}")
    print(f"  -> {os.path.join(args.out_dir, 'ohenro88-sections.json')}")


if __name__ == "__main__":
    main()