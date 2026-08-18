#!/usr/bin/env python3
import json
import math
import os
import sys

import osmium
from shapely.geometry import Polygon
from shapely.ops import unary_union

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PBF = os.path.join(ROOT, "source", "shikoku-latest.osm.pbf")
OUT_GEOJSON = os.path.join(ROOT, "output", "lodging.geojson")
OUT_REPORT = os.path.join(ROOT, "output", "lodging-report.json")

SUBTYPES = {"hotel", "hostel", "guest_house", "motel", "camp_site", "apartment", "chalet"}
ADDR_KEYS = ("prefecture", "city", "suburb", "neighbourhood", "street", "housenumber", "postcode", "full")


def _tags(taglist):
    tags = {}
    for t in taglist:
        if t.v:
            tags[t.k] = t.v
    return tags


def _clean(v):
    if v is None:
        return None
    v = v.strip()
    return v if v else None


def _first(tags, *keys):
    for k in keys:
        v = _clean(tags.get(k))
        if v:
            return v
    return None


def _int(tags, key):
    v = _clean(tags.get(key))
    if v is None:
        return None
    try:
        return int(v)
    except ValueError:
        return None


def _bool_or_raw(tags, key):
    v = _clean(tags.get(key))
    if v is None:
        return None
    low = v.lower()
    if low in ("yes", "true", "1"):
        return True
    if low in ("no", "false", "0"):
        return False
    return v


def _address(tags):
    addr = {}
    for k in ADDR_KEYS:
        v = _clean(tags.get("addr:" + k))
        if v:
            addr[k] = v
    return addr or None


def _subtype(tags, warnings):
    v = _clean(tags.get("tourism"))
    if v in SUBTYPES:
        return v
    if v:
        warnings.append("unknown tourism subtype: %r" % v)
    return v


def _representative_point(geom):
    if geom is None or geom.is_empty:
        return None
    p = geom.representative_point()
    return (p.x, p.y)


def _as_rings(way_coords_list):
    rings = []
    unclosed = []
    open_segs = []
    for coords in way_coords_list:
        if len(coords) >= 4 and coords[0] == coords[-1]:
            rings.append(coords)
        elif len(coords) >= 2:
            open_segs.append(coords)
    while open_segs:
        ring = list(open_segs.pop(0))
        changed = True
        while changed:
            changed = False
            for i in range(len(open_segs)):
                seg = open_segs[i]
                if seg[0] == ring[-1]:
                    ring.extend(seg[1:])
                    open_segs.pop(i)
                    changed = True
                    break
                if seg[-1] == ring[0]:
                    ring = seg[:-1] + ring
                    open_segs.pop(i)
                    changed = True
                    break
        if ring[0] == ring[-1]:
            rings.append(ring)
        else:
            unclosed.append(ring)
    return rings, unclosed


def _build_multipolygon(outer_rings, inner_rings):
    polys = []
    for ring in outer_rings:
        if len(ring) < 4:
            continue
        poly = Polygon(ring)
        if poly.is_empty:
            continue
        if not poly.is_valid:
            poly = poly.buffer(0)
        if not poly.is_empty:
            polys.append(poly)
    if not polys:
        return None
    inner = [Polygon(r) for r in inner_rings if len(r) >= 4]
    if inner:
        merged_inner = unary_union([p.buffer(0) if not p.is_valid else p for p in inner if not p.is_empty])
        if not merged_inner.is_empty:
            polys = [p.difference(merged_inner) for p in polys]
    polys = [p for p in polys if not p.is_empty]
    if not polys:
        return None
    geom = unary_union(polys)
    return geom if not geom.is_empty else None


class Pass1Handler(osmium.SimpleHandler):
    def __init__(self):
        osmium.SimpleHandler.__init__(self)
        self.nodes = []
        self.ways = []
        self.relations = []
        self.needed = set()

    def node(self, n):
        tags = _tags(n.tags)
        if tags.get("tourism") not in SUBTYPES:
            return
        if not n.location.valid:
            return
        self.nodes.append({
            "osm_id": n.id,
            "lon": n.location.lon,
            "lat": n.location.lat,
            "tags": tags,
            "version": n.version,
            "timestamp": str(n.timestamp),
            "changeset": n.changeset,
        })

    def way(self, w):
        tags = _tags(w.tags)
        if tags.get("tourism") not in SUBTYPES:
            return
        coords = [(nd.location.lon, nd.location.lat) for nd in w.nodes if nd.location.valid]
        self.ways.append({
            "osm_id": w.id,
            "coords": coords,
            "tags": tags,
            "version": w.version,
            "timestamp": str(w.timestamp),
            "changeset": w.changeset,
        })

    def relation(self, r):
        tags = _tags(r.tags)
        if tags.get("tourism") not in SUBTYPES:
            return
        members = []
        for m in r.members:
            members.append((m.type, m.ref, m.role))
            if m.type == "w":
                self.needed.add(m.ref)
        self.relations.append({
            "osm_id": r.id,
            "members": members,
            "tags": tags,
            "version": r.version,
            "timestamp": str(r.timestamp),
            "changeset": r.changeset,
        })


class Pass2Handler(osmium.SimpleHandler):
    def __init__(self, needed):
        osmium.SimpleHandler.__init__(self)
        self.needed = needed
        self.ways = {}

    def way(self, w):
        if w.id not in self.needed:
            return
        coords = [(nd.location.lon, nd.location.lat) for nd in w.nodes if nd.location.valid]
        self.ways[w.id] = coords


def _way_point(way, warnings):
    coords = way["coords"]
    if len(coords) < 2:
        warnings.append("way %d: fewer than 2 valid nodes" % way["osm_id"])
        return None, None
    closed = coords[0] == coords[-1]
    if closed and len(coords) >= 4:
        poly = Polygon(coords)
        if poly.is_empty:
            pass
        elif poly.is_valid:
            return _representative_point(poly), "representative_point"
        else:
            fixed = poly.buffer(0)
            if not fixed.is_empty:
                return _representative_point(fixed), "representative_point"
    n = len(coords)
    lon = sum(c[0] for c in coords) / n
    lat = sum(c[1] for c in coords) / n
    warnings.append("way %d: non-polygon geometry, used midpoint" % way["osm_id"])
    return (lon, lat), "polyline_midpoint"


def _relation_point(rel, member_ways, warnings):
    if rel["tags"].get("type") != "multipolygon":
        warnings.append("relation %d: unsupported type %r, skipped" % (rel["osm_id"], rel["tags"].get("type")))
        return None, None
    outers = []
    inners = []
    missing = 0
    for mtype, mref, role in rel["members"]:
        if mtype != "w":
            continue
        coords = member_ways.get(mref)
        if coords is None:
            missing += 1
            continue
        (inners if role == "inner" else outers).append(coords)
    if missing:
        warnings.append("relation %d: %d member way(s) missing geometry" % (rel["osm_id"], missing))
    outer_rings, unclosed_o = _as_rings(outers)
    inner_rings, unclosed_i = _as_rings(inners)
    for u in unclosed_o + unclosed_i:
        warnings.append("relation %d: unclosed ring (%d nodes)" % (rel["osm_id"], len(u)))
    geom = _build_multipolygon(outer_rings, inner_rings)
    if geom is None:
        warnings.append("relation %d: no usable geometry" % rel["osm_id"])
        return None, None
    return _representative_point(geom), "representative_point"


def _feature(osm_type, osm_id, tags, version, timestamp, changeset, lon, lat, point_method, warnings):
    props = {
        "id": "lodging-osm-%s-%d" % (osm_type, osm_id),
        "type": "lodging",
        "subtype": _subtype(tags, warnings),
        "name": _first(tags, "name"),
        "name_ja": _first(tags, "name:ja", "name"),
        "name_en": _first(tags, "name:en"),
        "address": _address(tags),
        "phone": _first(tags, "contact:phone", "phone"),
        "website": _first(tags, "contact:website", "website"),
        "email": _first(tags, "contact:email", "email"),
        "rooms": _int(tags, "rooms"),
        "beds": _int(tags, "beds"),
        "stars": _int(tags, "stars"),
        "internet_access": _clean(tags.get("internet_access")),
        "wifi": _clean(tags.get("wifi")),
        "washing_machine": _bool_or_raw(tags, "washing_machine"),
        "dryer": _bool_or_raw(tags, "dryer"),
        "wheelchair": _clean(tags.get("wheelchair")),
        "opening_hours": _clean(tags.get("opening_hours")),
        "check_date": _clean(tags.get("check_date")),
        "smoking": _clean(tags.get("smoking")),
        "pets": _clean(tags.get("pets")),
        "breakfast": _clean(tags.get("breakfast")),
        "restaurant": _clean(tags.get("restaurant")),
        "air_conditioning": _clean(tags.get("air_conditioning")),
        "reservation": _clean(tags.get("reservation")),
        "source": "osm",
        "osm_type": osm_type,
        "osm_id": osm_id,
        "point_method": point_method,
    }
    for k, v in (("osm_version", version), ("osm_timestamp", timestamp), ("changeset", changeset)):
        if v not in (None, 0, "", "1970-01-01T00:00:00Z"):
            props[k] = v
    props["raw_tags"] = tags
    return {
        "type": "Feature",
        "id": props["id"],
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": props,
    }


def _haversine(lon1, lat1, lon2, lat2):
    R = 6371000.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _find_duplicates(features):
    cands = []
    for f in features:
        p = f["properties"]
        lon, lat = f["geometry"]["coordinates"]
        cands.append({
            "id": f["id"],
            "name": (p.get("name") or "").strip().lower(),
            "phone": p.get("phone") or "",
            "website": p.get("website") or "",
            "lon": lon,
            "lat": lat,
        })
    dups = []
    seen = set()

    def add(a, b, signal):
        key = frozenset((a, b))
        if key in seen:
            return
        seen.add(key)
        dups.append({"a": a, "b": b, "signal": signal})

    by_name = {}
    for c in cands:
        if c["name"]:
            by_name.setdefault(c["name"], []).append(c)
    for group in by_name.values():
        if len(group) < 2:
            continue
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, b = group[i], group[j]
                d = _haversine(a["lon"], a["lat"], b["lon"], b["lat"])
                if d < 100:
                    add(a["id"], b["id"], "same name + near coords (%.0fm)" % d)

    by_phone = {}
    by_website = {}
    for c in cands:
        if c["phone"]:
            by_phone.setdefault(c["phone"], []).append(c)
        if c["website"]:
            by_website.setdefault(c["website"], []).append(c)
    for group in by_phone.values():
        if len(group) < 2:
            continue
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                add(group[i]["id"], group[j]["id"], "same phone")
    for group in by_website.values():
        if len(group) < 2:
            continue
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                add(group[i]["id"], group[j]["id"], "same website")
    return dups


def main():
    pbf = sys.argv[1] if len(sys.argv) > 1 else PBF
    out_geojson = sys.argv[2] if len(sys.argv) > 2 else OUT_GEOJSON
    out_report = sys.argv[3] if len(sys.argv) > 3 else OUT_REPORT

    print("pass 1: nodes / ways / relations ...")
    pass1 = Pass1Handler()
    pass1.apply_file(pbf, locations=True)
    print("  found %d nodes, %d ways, %d relations" % (len(pass1.nodes), len(pass1.ways), len(pass1.relations)))

    member_ways = {}
    if pass1.needed:
        print("pass 2: resolving %d relation member ways ..." % len(pass1.needed))
        pass2 = Pass2Handler(pass1.needed)
        pass2.apply_file(pbf, locations=True)
        member_ways = pass2.ways

    features = []
    warnings = []
    stats = {
        "total": 0,
        "by_subtype": {},
        "by_osm_type": {"node": 0, "way": 0, "relation": 0},
        "missing_name": 0,
        "missing_coordinate": 0,
        "missing_phone": 0,
        "missing_website": 0,
        "with_laundry_tags": 0,
        "with_internet_tags": 0,
        "unknown_subtypes": [],
    }

    def add(feature):
        p = feature["properties"]
        stats["total"] += 1
        stats["by_osm_type"][p["osm_type"]] += 1
        stats["by_subtype"][p["subtype"]] = stats["by_subtype"].get(p["subtype"], 0) + 1
        if not p["name"]:
            stats["missing_name"] += 1
        if not p["phone"]:
            stats["missing_phone"] += 1
        if not p["website"]:
            stats["missing_website"] += 1
        if p["washing_machine"] is not None or p["dryer"] is not None:
            stats["with_laundry_tags"] += 1
        if p["internet_access"] or p["wifi"]:
            stats["with_internet_tags"] += 1
        sub = p["subtype"]
        if sub and sub not in SUBTYPES and sub not in stats["unknown_subtypes"]:
            stats["unknown_subtypes"].append(sub)
        features.append(feature)

    for node in pass1.nodes:
        f = _feature("node", node["osm_id"], node["tags"], node["version"], node["timestamp"],
                     node["changeset"], node["lon"], node["lat"], "node", warnings)
        add(f)

    for way in pass1.ways:
        pt, method = _way_point(way, warnings)
        if pt is None:
            stats["missing_coordinate"] += 1
            continue
        f = _feature("way", way["osm_id"], way["tags"], way["version"], way["timestamp"],
                     way["changeset"], pt[0], pt[1], method, warnings)
        add(f)

    for rel in pass1.relations:
        pt, method = _relation_point(rel, member_ways, warnings)
        if pt is None:
            stats["missing_coordinate"] += 1
            continue
        f = _feature("relation", rel["osm_id"], rel["tags"], rel["version"], rel["timestamp"],
                     rel["changeset"], pt[0], pt[1], method, warnings)
        add(f)

    stats["duplicate_candidates"] = _find_duplicates(features)
    stats["warnings"] = warnings

    os.makedirs(os.path.dirname(out_geojson), exist_ok=True)
    with open(out_geojson, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f, ensure_ascii=False, indent=2)
    with open(out_report, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    print("wrote %d features -> %s" % (len(features), out_geojson))
    print("wrote report   -> %s" % out_report)
    print("  by_subtype: %s" % json.dumps(stats["by_subtype"], ensure_ascii=False))
    print("  by_osm_type: %s" % stats["by_osm_type"])
    print("  warnings: %d, duplicate candidates: %d" % (len(warnings), len(stats["duplicate_candidates"])))


if __name__ == "__main__":
    main()
