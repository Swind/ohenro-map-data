#!/usr/bin/env python3
"""Extract Henro Helper route geometry from blutter disassembly into GeoJSON.

Each route class in the app is a Dart static literal (List<List<List<double>>>):
  - 3-double points (literal3) = [lon, lat, elevation]
  - 2-double points (literal2) = [lon, lat]
Polylines are delimited by `_GrowableList._literal()` (no number) calls.
"""
import argparse
import json
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ASM_DIR = os.path.join(SCRIPT_DIR, "blutter-out", "asm", "henro_helper_real")
OUT_DIR = os.path.join(SCRIPT_DIR, "..", "..", "output", "henro-helper-routes")

FLOAT_RE = re.compile(r'^\s*// 0x[0-9a-f]+: r\d+ = (-?\d+\.\d+)')
LIT_RE = re.compile(r'^\s*// 0x[0-9a-f]+: r0 = _GrowableList\._literal(\d*)\(\)$')


def parse_layer(filename):
    """Return (polylines, skipped) where each polyline is a list of points.

    A point is `[lon, lat, elevation]` (literal3) or `[lon, lat]` (literal2).
    Some literal3/literal2 calls reuse previously-created point objects (the
    compiler hoisted shared values into fp slots); those carry no fresh
    coordinates and are skipped (their coordinates already appear in adjacent
    polylines). They are counted in `skipped`.
    """
    path = os.path.join(ASM_DIR, filename)
    polylines = []
    cur = []
    pending = []
    connectors = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            m = FLOAT_RE.match(line)
            if m:
                pending.append(float(m.group(1)))
                if len(pending) > 16:
                    pending = pending[-16:]
                continue
            m = LIT_RE.match(line)
            if m:
                nstr = m.group(1)
                if nstr == "":
                    # _GrowableList._literal(): a completed polyline is wrapped.
                    if cur:
                        polylines.append(cur)
                        cur = []
                    pending = []
                else:
                    n = int(nstr)
                    if n in (2, 3) and len(pending) >= n:
                        cur.append(pending[-n:])
                        pending = []
                    else:
                        # Reference construction: the compiler reuses previously
                        # created point objects (fp slots) to build a connector
                        # polyline (_literal2/3/7/...). This marks a boundary.
                        if cur:
                            polylines.append(cur)
                            cur = []
                        pending = []
                        connectors += 1
    if cur:
        polylines.append(cur)
    return polylines, connectors


def stats(polyline):
    if not polyline:
        return None
    elevs = [p[2] for p in polyline if len(p) >= 3]
    props = {}
    if elevs:
        props.update({
            "elevation_start": elevs[0],
            "elevation_end": elevs[-1],
            "elevation_min": min(elevs),
            "elevation_max": max(elevs),
            "elevation_mean": round(sum(elevs) / len(elevs), 2),
        })
    props["num_points"] = len(polyline)
    return props


LAYERS = [
    # (file, layer name, route_type, swap_lat_lon)
    ("BlackLines.dart", "black", "road", False),
    ("RedLines.dart", "red", "road", False),
    ("GreenLines.dart", "green", "road", False),
    ("BlueLines.dart", "blue", "trail", False),
    ("PurpleLines.dart", "purple", "trail", False),
    ("Ferries&RopewaysLines.dart", "special", "special", False),
    ("EightyEighttoOne.dart", "eighty88to1", "road", False),
    ("ConnectionPoints.dart", "connection", "connection", True),
    ("FiftySix.dart", "itinerary_56", "itinerary", False),
    ("FortyNine.dart", "itinerary_49", "itinerary", False),
    ("FortyTwo.dart", "itinerary_42", "itinerary", False),
]

# Per-day itinerary metadata lives in the <N>database.dart record lists; the
# record order matches the geometry order (feature i <-> record i).
ITINERARY_DAYS = {
    "itinerary_56": ("fiftysixdatabase.dart", "AllocateFiftySixListStub"),
    "itinerary_49": ("fortyninedatabase.dart", "AllocateFortyNineListStub"),
    "itinerary_42": ("fortytwodatabase.dart", "AllocateFortyTwoListStub"),
}

ALLOC_RE = re.compile(r"Allocate[A-Za-z0-9]+ListStub")
STR_RE = re.compile(r'^    // 0x[0-9a-f]+: r(\d+) = "([^"]*)"')
STORE_RE = re.compile(r"StoreField: r\d+->field_([0-9a-f]+) = r(\d+)")
TITLE_RE = re.compile(r"^DAY (\d+)([A-Z]?):\s*(.*)$")
TEMPLE_RE = re.compile(r"Temple\s+(\d+)", re.IGNORECASE)


def parse_itinerary_days(filename, alloc_marker):
    """Extract per-day records (title / distance / elevation / time) in order.

    The record classes (FiftySixList / FortyNineList / FortyTwoList) share the
    same field layout: field_7 = English title, field_33 = distance ("21.2km"),
    field_37 = elevation ("540m"), field_3b = time ("8.5h - 11.0h").
    """
    path = os.path.join(ASM_DIR, filename)
    regs = {}
    records = []
    cur = None
    for line in open(path, encoding="utf-8"):
        if alloc_marker in line:
            if cur:
                records.append(cur)
            cur = {}
            continue
        if cur is None:
            continue
        m = STR_RE.match(line)
        if m:
            regs[m.group(1)] = m.group(2)
            continue
        m = STORE_RE.search(line)
        if m:
            off = m.group(1)
            reg = m.group(2)
            if off in ("7", "33", "37", "3b") and reg in regs:
                cur[off] = regs[reg]
    if cur:
        records.append(cur)
    return records


def day_props(title):
    """Parse an itinerary title like 'DAY 1A:  Temple 1 to Temple 6'."""
    props = {}
    m = TITLE_RE.match(title or "")
    if m:
        props["day"] = int(m.group(1))
        if m.group(2):
            props["day_variant"] = m.group(2)
        props["day_label"] = f"DAY {m.group(1)}{m.group(2)}"
        props["title"] = title
        temples = [int(t) for t in TEMPLE_RE.findall(m.group(3))]
        if temples:
            props["from_temple"] = temples[0]
            if len(temples) > 1:
                props["to_temple"] = temples[1]
    else:
        props["title"] = title
    return props


def main():
    global ASM_DIR, OUT_DIR
    parser = argparse.ArgumentParser(
        description="Extract Henro Helper route geometry into GeoJSON.")
    parser.add_argument("--asm-dir", default=ASM_DIR,
                        help="blutter asm dir for henro_helper_real (default: %(default)s)")
    parser.add_argument("--out-dir", default=OUT_DIR,
                        help="output directory (default: %(default)s)")
    args = parser.parse_args()
    ASM_DIR = args.asm_dir
    OUT_DIR = args.out_dir

    os.makedirs(OUT_DIR, exist_ok=True)
    all_features = []
    report = []
    for filename, layer, rtype, swap in LAYERS:
        polylines, skipped = parse_layer(filename)
        if swap:
            polylines = [[p[::-1] for p in pl] for pl in polylines]
        day_records = None
        if layer in ITINERARY_DAYS:
            day_file, alloc_marker = ITINERARY_DAYS[layer]
            day_records = parse_itinerary_days(day_file, alloc_marker)
        features = []
        for i, pl in enumerate(polylines):
            props = {
                "id": f"{layer}-{i:04d}",
                "layer": layer,
                "route_type": rtype,
                "index": i,
            }
            if day_records is not None and i < len(day_records):
                rec = day_records[i]
                title = rec.get("7")
                props.update(day_props(title))
                props["distance"] = rec.get("33")
                props["elevation"] = rec.get("37")
                props["time"] = rec.get("3b")
            if layer == "connection":
                # connectionPoints is a flat list of junction points.
                for j, p in enumerate(pl):
                    fp = dict(props)
                    fp["id"] = f"{layer}-{i:04d}-{j:04d}"
                    fp["index"] = j
                    fp["num_points"] = 1
                    features.append({
                        "type": "Feature",
                        "properties": fp,
                        "geometry": {"type": "Point", "coordinates": p},
                    })
                continue
            props.update(stats(pl) or {})
            features.append({
                "type": "Feature",
                "properties": props,
                "geometry": {"type": "LineString", "coordinates": pl},
            })
        if features:
            fc = {"type": "FeatureCollection", "name": layer, "features": features}
            with open(os.path.join(OUT_DIR, f"{layer}.geojson"), "w", encoding="utf-8") as f:
                json.dump(fc, f, ensure_ascii=False)
        npts = sum(len(pl) for pl in polylines)
        report.append(f"{layer:15s} route_type={rtype:11s} polylines={len(polylines):5d} points={npts:7d} connectors={skipped:2d}")
        all_features.extend(features)

    combined = {"type": "FeatureCollection", "name": "henro-helper-routes",
                "features": all_features}
    with open(os.path.join(OUT_DIR, "henro-helper-routes.geojson"), "w", encoding="utf-8") as f:
        json.dump(combined, f, ensure_ascii=False)

    print("\n".join(report))
    total_pts = sum(f["properties"]["num_points"] for f in all_features)
    print(f"\nTOTAL features={len(all_features)} points={total_pts}")
    for fname in sorted(os.listdir(OUT_DIR)):
        size = os.path.getsize(os.path.join(OUT_DIR, fname))
        print(f"  {fname:45s} {size/1024:10.1f} KiB")


if __name__ == "__main__":
    sys.exit(main())