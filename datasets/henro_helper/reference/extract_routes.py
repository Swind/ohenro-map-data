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
PP_PATH = os.path.join(SCRIPT_DIR, "blutter-out", "pp.txt")
OUT_DIR = os.path.join(SCRIPT_DIR, "..", "output")

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
    ("ishizuchi.dart", "ishizuchi", "trail", False),
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


# ---- POI markers (points / labels / notes) ----
# POI records are constructed one-by-one via `Allocate<Class>Stub -> <Class>`.
# Each record's location is a pooled `Obj!LatLng@<id>` object loaded with
# `rX = Instance_LatLng`; the coordinate is resolved from pp.txt.  Multilingual
# string fields are inline and captured per record by field offset.
POI_CLASSES = [
    # (file, record class, layer, kind)
    ("Temples.dart", "TheTemples", "temples", "temple"),
    ("Toilets.dart", "ToiletCoords", "toilets", "toilet"),
    ("Busstop.dart", "BusList", "bus_stops", "bus_stop"),
    ("Labels.dart", "TheLabels", "labels", "label"),
    ("Pointsofinterest.dart", "ThePoints", "points_of_interest", "poi"),
    ("Trainstation.dart", "TrainList", "train_stations", "train_station"),
    ("Bekkaku.dart", "TheBekkaku", "bekkaku", "bekkaku"),
    ("Importantnotes.dart", "ImportantList", "important_notes", "important_note"),
    ("Onsens.dart", "OnsenList", "onsens", "onsen"),
    ("Onsens.dart", "ShowerCoords", "showers", "shower"),
    ("Restareas.dart", "RestCoords", "rest_areas", "rest_area"),
    ("Restareas.dart", "RestToiletCoords", "rest_toilets", "rest_toilet"),
    ("Restareas.dart", "RestNoCoords", "rest_no_coords", "rest_area"),
    ("Restareas.dart", "RestYesList", "rest_areas_yes", "rest_area"),
    ("Restareas.dart", "TsuyadoList", "tsuyados", "tsuyado"),
    ("Roadsidestation.dart", "RoadsideCoords", "roadside_stations", "roadside_station"),
    ("Roadsidestation.dart", "RoadsideYesCoords", "roadside_yes_coords", "roadside_station"),
    ("Roadsidestation.dart", "RoadsideYesList", "roadside_yes_list", "roadside_station"),
    ("Roadsidestation.dart", "RoadsideNoCoords", "roadside_no_coords", "roadside_station"),
    ("Convenience.dart", "ConvenienceCoords", "convenience_stores", "convenience_store"),
    ("Convenience.dart", "ConvenienceSeatsCoords", "convenience_seats", "convenience_store"),
    ("Campgrounds.dart", "CampList", "campgrounds", "campground"),
    ("Campgrounds.dart", "UnofficialList", "campgrounds_unofficial", "campground"),
    ("Accommodations.dart", "OtherList", "accommodations_other", "accommodation"),
    ("Accommodations.dart", "HostelList", "accommodations_hostel", "accommodation"),
    ("Accommodations.dart", "HenroList", "accommodations_henro", "accommodation"),
    ("Accommodations.dart", "ShukuboList", "accommodations_shukubo", "accommodation"),
    ("OkunoinBangai.dart", "TheBangai", "bangai", "bangai"),
    ("OkunoinBangai.dart", "TheOkunoin", "okunoin", "okunoin"),
    ("ishizuchi.dart", "IshizuchiList", "ishizuchi_pois", "ishizuchi"),
]

# Per-record-class layout overrides (the ishizuchi itinerary record keeps its
# LatLng in field_27 and swaps the en/ja name slots).
POI_COORD_FIELD = {"IshizuchiList": "field_27"}
POI_NAME_FIELDS = {"IshizuchiList": ("field_7", "field_b")}  # (en, ja)

LATLNG_POOL_RE = re.compile(r"\[pp\+0x[0-9a-f]+\] Obj!LatLng@([0-9a-f]+) : \{")
LATLNG_OFF_RE = re.compile(r"off_([0-9a-f]+): double\((-?\d+(?:\.\d+)?)\)")
LATLNG_LOAD_RE = re.compile(r"^    // 0x[0-9a-f]+: r(\d+) = Instance_LatLng$")
LATLNG_REF_RE = re.compile(r"Obj!LatLng@([0-9a-f]+)")
POI_ALLOC_RE = re.compile(r"; Allocate[A-Za-z0-9]+Stub -> ([A-Za-z0-9]+) \(size=0x[0-9a-f]+\)")
POI_STORE_RE = re.compile(r"StoreField: r(\d+)->field_([0-9a-f]+) = r(\d+)")
ARRSTORE_RE = re.compile(r"ArrayStore: r(\d+)\[(\d+)\] = r(\d+)")

# English/Japanese short labels live in field_b / field_f; the record lists
# (RestYesList/TsuyadoList) additionally carry a short type label in field_2b
# / field_2f.  Long multilingual notes occupy field_2b+.
NOTE_WORDS = {"NOTES", "NOTE", "IMPORTANT", "WARNING", "REMARKS", "REMARQUES",
              "NOTA", "NOTAS", "HINWEIS", "HINWEISE", "AVERTISSEMENT",
              "AVVERTENZA", "ADVERTENCIA", "WARNUNG"}


def load_latlng_pool(path):
    """Map Obj!LatLng@<id> -> (lat, lon).  LatLng fields: off_8 = latitude, off_10 = longitude."""
    pool = {}
    cur = None
    for line in open(path, encoding="utf-8"):
        m = LATLNG_POOL_RE.search(line)
        if m:
            cur = m.group(1)
            pool[cur] = {}
            continue
        if cur is None:
            continue
        m = LATLNG_OFF_RE.match(line.strip())
        if m:
            off, val = m.groups()
            pool[cur][int(off, 16)] = float(val)
            if len(pool[cur]) == 2:
                cur = None
    out = {}
    for ref, d in pool.items():
        lat, lon = d.get(0x8), d.get(0x10)
        if lat is not None and lon is not None:
            out[ref] = (lat, lon)
    return out


def parse_poi_class(filename, class_name):
    """Return per-record field dicts for one POI record class.

    Values are tuples ("str", text) / ("latlng", pool_ref); field_17_array
    collects ArrayStore writes (e.g. the Traditional-Chinese label list).
    Construction of other record classes inside the same file is skipped.
    """
    path = os.path.join(ASM_DIR, filename)
    regs = {}
    records = []
    cur = None
    pending_latlng = None
    for line in open(path, encoding="utf-8"):
        m = POI_ALLOC_RE.search(line)
        if m:
            if m.group(1) == class_name:
                if cur is not None:
                    records.append(cur)
                # obj_reg = the record's own object register, learned from the
                # first StoreField so stores into nested helper objects (which
                # reuse other registers) are not mis-attributed.
                cur = {"fields": {}, "obj_reg": None}
            else:
                cur = None
            regs = {}
            pending_latlng = None
            continue
        if cur is None:
            continue
        m = LATLNG_LOAD_RE.match(line)
        if m:
            pending_latlng = m.group(1)
            continue
        m = LATLNG_REF_RE.search(line)
        if m and pending_latlng is not None:
            regs[pending_latlng] = ("latlng", m.group(1))
            pending_latlng = None
            continue
        m = STR_RE.match(line)
        if m:
            regs[m.group(1)] = ("str", m.group(2))
            continue
        m = POI_STORE_RE.search(line)
        if m:
            obj, off, val = m.groups()
            if cur["obj_reg"] is None:
                cur["obj_reg"] = obj
            if obj != cur["obj_reg"]:
                continue
            v = regs.get(val)
            if v is not None:
                cur["fields"]["field_%s" % off] = v
            continue
        m = ARRSTORE_RE.search(line)
        if m:
            obj, _, val = m.groups()
            if obj == cur["obj_reg"]:
                v = regs.get(val)
                if v is not None:
                    cur["fields"].setdefault("field_17_array", []).append(v)
    if cur is not None:
        records.append(cur)
    return records


def _is_note(text):
    text = text.strip()
    if not text:
        return True
    if text.lower().startswith(("http://", "https://")) or text.startswith(("maps.app.goo.gl", "www.")):
        return True
    first = text.split()[0].rstrip(":：")
    if first in NOTE_WORDS or text[0] in "備비注警重參":
        return True
    return False


def _field_str(fields, off):
    v = fields.get(off)
    return v[1] if v and v[0] == "str" else None


def poi_names(fields, cls):
    """Best English / Japanese short label, skipping note/URL text."""
    en_off, ja_off = POI_NAME_FIELDS.get(cls, ("field_b", "field_f"))
    en, ja = _field_str(fields, en_off), _field_str(fields, ja_off)
    if en is None or _is_note(en):
        en = None
    if ja is None or _is_note(ja):
        ja = None
    if en is None:
        v = _field_str(fields, "field_2b")
        if v and not _is_note(v):
            en = v
    if ja is None:
        v = _field_str(fields, "field_2f")
        if v and not _is_note(v):
            ja = v
    return en, ja


def poi_extra(fields, kind):
    """Per-kind structured extras (temple / bekkaku / okunoin numbers, names)."""
    extra = {}
    en, ja = _field_str(fields, "field_b"), _field_str(fields, "field_f")
    if kind == "temple":
        m = re.search(r"TEMPLE\s+(\d+)", en or "", re.IGNORECASE)
        if m:
            extra["temple_number"] = int(m.group(1))
    elif kind == "bekkaku":
        m = re.search(r"BEKKAKU\s+(\d+)", en or "", re.IGNORECASE)
        if m:
            extra["bekkaku_number"] = int(m.group(1))
    if kind in ("temple", "bekkaku"):
        v = _field_str(fields, "field_2b")
        if v and v.startswith("NAME:"):
            extra["temple_name_en"] = v[5:].strip()
        v = _field_str(fields, "field_2f")
        if v and v.startswith("寺名："):
            extra["temple_name_ja"] = v[3:].strip()
    if kind == "okunoin":
        v = _field_str(fields, "field_2f") or _field_str(fields, "field_2b") or ""
        m = re.search(r"(\d+)番", v)
        if m:
            extra["temple_number"] = int(m.group(1))
    return extra


def poi_record_to_feature(layer, kind, cls, i, fields, latlng_pool):
    coord_field = POI_COORD_FIELD.get(cls, "field_7")
    latlng = fields.get(coord_field)
    if not (latlng and latlng[0] == "latlng"):
        return None
    coord = latlng_pool.get(latlng[1])
    if not coord:
        return None
    lat, lon = coord
    en, ja = poi_names(fields, cls)
    props = {
        "id": "%s-%04d" % (layer, i),
        "layer": layer,
        "kind": kind,
        "class": cls,
        "index": i,
        "name_en": en,
        "name_ja": ja,
        "num_points": 1,
    }
    props.update(poi_extra(fields, kind))
    for off in sorted(fields):
        if off == coord_field:
            continue
        v = fields[off]
        if off == "field_17_array":
            props[off] = [x[1] if x[0] == "str" else x[1] for x in v]
        elif v[0] == "str":
            props[off] = v[1]
        else:
            props[off] = latlng_pool.get(v[1], v[1])
    return {"type": "Feature", "properties": props,
            "geometry": {"type": "Point", "coordinates": [lon, lat]}}


def main():
    global ASM_DIR, PP_PATH, OUT_DIR
    parser = argparse.ArgumentParser(
        description="Extract Henro Helper routes + POI markers into GeoJSON.")
    parser.add_argument("--asm-dir", default=ASM_DIR,
                        help="blutter asm dir for henro_helper_real (default: %(default)s)")
    parser.add_argument("--pp-file", default=PP_PATH,
                        help="blutter pp.txt object-pool dump (default: %(default)s)")
    parser.add_argument("--out-dir", default=OUT_DIR,
                        help="output directory (default: %(default)s)")
    args = parser.parse_args()
    ASM_DIR = args.asm_dir
    PP_PATH = args.pp_file
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

    latlng_pool = load_latlng_pool(PP_PATH)
    print(f"\nLatLng pool: {len(latlng_pool)} objects")
    poi_features = []
    poi_report = []
    for filename, cls, layer, kind in POI_CLASSES:
        records = parse_poi_class(filename, cls)
        features = []
        skipped = 0
        for i, rec in enumerate(records):
            ft = poi_record_to_feature(layer, kind, cls, i, rec["fields"], latlng_pool)
            if ft is None:
                skipped += 1
                continue
            features.append(ft)
        if features:
            fc = {"type": "FeatureCollection", "name": layer, "features": features}
            with open(os.path.join(OUT_DIR, f"{layer}.geojson"), "w", encoding="utf-8") as f:
                json.dump(fc, f, ensure_ascii=False)
        poi_report.append(f"{layer:24s} kind={kind:16s} records={len(records):4d} features={len(features):4d} skipped={skipped:2d}")
        poi_features.extend(features)

    poi_combined = {"type": "FeatureCollection", "name": "henro-helper-pois",
                    "features": poi_features}
    with open(os.path.join(OUT_DIR, "henro-helper-pois.geojson"), "w", encoding="utf-8") as f:
        json.dump(poi_combined, f, ensure_ascii=False)

    print("\n".join(poi_report))
    print(f"\nPOI TOTAL features={len(poi_features)}")
    for fname in sorted(os.listdir(OUT_DIR)):
        size = os.path.getsize(os.path.join(OUT_DIR, fname))
        print(f"  {fname:45s} {size/1024:10.1f} KiB")


if __name__ == "__main__":
    sys.exit(main())