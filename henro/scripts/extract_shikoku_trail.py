#!/usr/bin/env python3
"""Extract Shikoku Nature Trail (四国自然歩道) routes from official KML files.

Each <Placemark> becomes one LineString feature with:
  route_id : SHIKOKU_TKS_01（無編號者為 SHIKOKU_TKS_ / SHIKOKU_EHM_ / ...）
  name     : 中文名（description，接続/連絡コース 為 null）
  pref     : tokushima / kagawa / ehime / kochi
  kind     : main / connector（接続コース）/ link（連絡コース）
  seg      : 同一 route_id 內的分段流水號（1-based）
  seg_count: 該 route_id 總分段數

Source: https://ranger-k.eco.coocan.jp/longtrail_webmap/shikoku_trail/route/webmap.html
（KML 的 geometry 與同目錄 GPX 完全一致，name/description 已拆好，故以 KML 為來源。）
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC_DIR = os.path.join(ROOT, "source", "shikoku_trail")
OUT_GEOJSON = os.path.join(ROOT, "output", "shikoku-trail.geojson")
OUT_REPORT = os.path.join(ROOT, "output", "shikoku-trail-report.json")

PREF_BY_CODE = {
    "36": "tokushima",
    "37": "kagawa",
    "38": "ehime",
    "39": "kochi",
}

KIND_BY_NAME = {
    "接続コース": "connector",
    "連絡コース": "link",
}


def parse_kml(path):
    src = open(path, encoding="utf-8").read()
    blocks = re.findall(r"<Placemark>(.*?)</Placemark>", src, re.S)
    routes = []
    for block in blocks:
        name = re.search(r"<name>([^<]*)</name>", block)
        desc = re.search(r"<description>([^<]*)</description>", block)
        coord = re.search(r"<coordinates>([^<]+)</coordinates>", block, re.S)
        if not name or not coord:
            continue
        coords = []
        for pt in coord.group(1).split():
            parts = pt.strip().split(",")
            if len(parts) < 2:
                continue
            try:
                coords.append([float(parts[0]), float(parts[1])])
            except ValueError:
                continue
        if len(coords) < 2:
            continue
        routes.append({
            "route_id": name.group(1),
            "name": desc.group(1).strip() if desc and desc.group(1).strip() else None,
            "coords": coords,
        })
    return routes


def make_route_id(rid, name):
    """合成唯一 route_id。

    KML 的無編號路線 name 只是前綴（如 SHIKOKU_KCH_），多條不同步道共用
    同一個前綴（高知 4 條、愛媛 1 條），App 無法分開選擇，故以「前綴+名稱」
    合成唯一 id。接続/連絡コース（無名稱）維持原值。
    """
    if rid in KIND_BY_NAME:
        return rid
    if re.search(r"_\d+$", rid):
        return rid
    if name:
        return rid + name
    return rid


def main():
    out_geojson = sys.argv[1] if len(sys.argv) > 1 else OUT_GEOJSON
    out_report = sys.argv[2] if len(sys.argv) > 2 else OUT_REPORT

    features = []
    stats = {
        "by_pref": {},
        "by_kind": {"main": 0, "connector": 0, "link": 0},
        "routes": 0,
        "segments": 0,
        "points": 0,
        "unparsed": 0,
    }

    for code, pref in sorted(PREF_BY_CODE.items()):
        kml = os.path.join(SRC_DIR, "%s_shikoku_%s.kml" % (code, pref))
        if not os.path.exists(kml):
            stats["unparsed"] += 1
            print("WARN: missing %s" % kml, file=sys.stderr)
            continue
        routes = parse_kml(kml)
        by_id = {}
        for r in routes:
            r["route_id"] = make_route_id(r["route_id"], r["name"])
            by_id.setdefault(r["route_id"], []).append(r)
        seg_index = {}
        for r in routes:
            rid = r["route_id"]
            seg_index[rid] = seg_index.get(rid, 0) + 1
            kind = KIND_BY_NAME.get(rid, "main")
            props = {
                "route_id": rid,
                "name": r["name"],
                "pref": pref,
                "kind": kind,
                "seg": seg_index[rid],
                "seg_count": len(by_id[rid]),
            }
            f = {
                "type": "Feature",
                "id": "%s-%s-%d" % (rid, pref, seg_index[rid]),
                "geometry": {"type": "LineString", "coordinates": r["coords"]},
                "properties": props,
            }
            features.append(f)
            stats["by_pref"][pref] = stats["by_pref"].get(pref, 0) + 1
            stats["by_kind"][kind] += 1
            stats["segments"] += 1
            stats["points"] += len(r["coords"])
        routes_main = {r["route_id"] for r in routes if r["route_id"] not in KIND_BY_NAME}
        stats["routes"] += len(routes_main)

    os.makedirs(os.path.dirname(out_geojson), exist_ok=True)
    with open(out_geojson, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f, ensure_ascii=False, indent=2)
    with open(out_report, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    print("wrote %d features -> %s" % (len(features), out_geojson))
    print("wrote report   -> %s" % out_report)
    print("  by_pref: %s" % json.dumps(stats["by_pref"], ensure_ascii=False))
    print("  by_kind: %s" % json.dumps(stats["by_kind"], ensure_ascii=False))
    print("  main routes: %d, segments: %d, points: %d" % (stats["routes"], stats["segments"], stats["points"]))


if __name__ == "__main__":
    main()
