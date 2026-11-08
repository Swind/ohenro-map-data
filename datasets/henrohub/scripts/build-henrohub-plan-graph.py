#!/usr/bin/env python3
"""Build a browser PlanGraph from the Henro Hub (henro.app) route network.

Reads ``datasets/henrohub/output/henrohub-routes.geojson`` (``kind=line``
LineString / MultiLineString features with 3D ``[lon, lat, elev]``
coordinates) and emits a PlanGraph in the SAME schema as
``sekaiisan_henro export-plan-graph`` (schema_version 2, topology/geometry
split: nodes + traversal_edges + synthetic_joins with weights but no
per-vertex geometry; polyline vertices in ``edge_geometry``), so map-preview's
``planner.ts`` works unchanged.

Only the main and alternative route roles participate
(``canonical_shikoku88`` = main, ``unique_alternative``); connector and
fallback segments are network-bridging glue / continuity fallbacks, not
walkable routing candidates. Unlike the OHenro 88 extractor, the geometry is
kept fully 3D (elevation) so a planned route already carries heights.

The network is digitised independently per segment: consecutive segments meet
at temples with small coordinate offsets, and segments from different authors
(shikoku88-* / hrn_* / hh26_*) can overlap without sharing exact vertices.
Graph construction therefore uses the same conservative proximity model as the
OHenro 88 builder:

* a node is created for every segment start/end and for every endpoint that
  lands on another segment's interior within ``--tolerance-m``;
* nodes whose coordinates are within ``--proximity-m`` merge into a single
  routing node;
* segments split at their own endpoints and at T-cuts into positive-length
  edges (weight = ``length_m`` via the shared equirectangular metric
  projection);
* route-endpoint gaps are bridged conservatively by joining each endpoint to
  its single nearest edge within ``--join-m`` (interior joins split the edge).

This is Henro Hub's own digitised linework (see
datasets/henrohub/docs/henro-hub-comparison.md), a routing reference for day planning, never
a navigation guarantee. Output is deterministic (no timestamp, atomic write).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from collections import defaultdict
from bisect import bisect_right
from pathlib import Path
import sys

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from datasets.henrohub.validation import validate_graph, validate_routes

R = 6371008.8
LON0 = 133.75
LAT0 = 33.65
_COS = math.cos(math.radians(LAT0))
_RAD = math.pi / 180.0
_EPS = 1e-6

_DEG_LON_PER_M = 1.0 / (R * _COS * _RAD)
_DEG_LAT_PER_M = 1.0 / (R * _RAD)

# Route roles treated as walkable routing candidates.
_ROUTED_ROLES = {"canonical_shikoku88", "unique_alternative"}


def project(lon: float, lat: float) -> tuple[float, float]:
    return (R * (lon - LON0) * _RAD * _COS, R * (lat - LAT0) * _RAD)


def unproject(x: float, y: float) -> tuple[float, float]:
    return (LON0 + x / (R * _COS) / _RAD, LAT0 + y / R / _RAD)


def _canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash16(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _quantize(value: float) -> float:
    return round(value, 9)


def _node_id(lon: float, lat: float) -> str:
    return "HHN_" + _hash16(_canon({"lon": _quantize(lon), "lat": _quantize(lat)}))


class _UnionFind:
    def __init__(self):
        self._parent: dict = {}

    def add(self, item: str) -> None:
        self._parent.setdefault(item, item)

    def find(self, item: str) -> str:
        while self._parent[item] != item:
            self._parent[item] = self._parent[self._parent[item]]
            item = self._parent[item]
        return item

    def union(self, a: str, b: str) -> None:
        self.add(a)
        self.add(b)
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            if ra < rb:
                self._parent[rb] = ra
            else:
                self._parent[ra] = rb


def _line_parts(features: list[dict]) -> list[tuple[str, list]]:
    segs = []
    for feature in features:
        props = feature.get("properties") or {}
        if props.get("kind") != "line":
            continue
        if props.get("route_role") not in _ROUTED_ROLES:
            continue
        geometry = feature.get("geometry") or {}
        route_id = str(props.get("route_id") or "")
        if geometry.get("type") == "LineString":
            parts = [geometry.get("coordinates") or []]
        elif geometry.get("type") == "MultiLineString":
            parts = geometry.get("coordinates") or []
        else:
            continue
        for coords in parts:
            if len(coords) >= 2:
                # Keep the full 3D coordinate (lon, lat, elev).
                segs.append((route_id, [list(c) for c in coords]))
    return segs


def _prepare(segs):
    prepared = []
    for route_id, coords in segs:
        metric = [project(c[0], c[1]) for c in coords]
        cum = [0.0]
        for i in range(1, len(metric)):
            cum.append(cum[-1] + math.hypot(metric[i][0] - metric[i - 1][0],
                                            metric[i][1] - metric[i - 1][1]))
        lons = [c[0] for c in coords]
        lats = [c[1] for c in coords]
        prepared.append({
            "route_id": route_id, "coords": coords, "metric": metric,
            "cum": cum, "length": cum[-1],
            "bbox": (min(lons), max(lons), min(lats), max(lats)),
        })
    return prepared


def _project_on_line(seg: dict, x: float, y: float) -> dict:
    metric = seg["metric"]
    cum = seg["cum"]
    best = None
    for i in range(len(metric) - 1):
        ax, ay = metric[i]
        bx, by = metric[i + 1]
        abx = bx - ax
        aby = by - ay
        denom = abx * abx + aby * aby
        t = ((x - ax) * abx + (y - ay) * aby) / denom if denom > 0 else 0.0
        t = max(0.0, min(1.0, t))
        qx = ax + t * abx
        qy = ay + t * aby
        d = math.hypot(x - qx, y - qy)
        measure = cum[i] + t * (cum[i + 1] - cum[i])
        if best is None or d < best["distance"]:
            best = {"distance": d, "measure": measure, "x": qx, "y": qy}
    return best


def _simplify(edges: list[dict], keep_nodes: set,
              node_coords: dict) -> tuple[list[dict], dict]:
    best: dict = {}
    for edge in edges:
        key = (edge["from"], edge["to"]) if edge["from"] < edge["to"] \
            else (edge["to"], edge["from"])
        cur = best.get(key)
        if cur is None or edge["length_m"] < cur["length_m"]:
            best[key] = edge
    edges = [dict(e) for e in best.values()]

    adj: dict = defaultdict(set)
    for i, edge in enumerate(edges):
        adj[edge["from"]].add(i)
        adj[edge["to"]].add(i)
    removed = [False] * len(edges)
    merged: set = set()

    def incident(node: str) -> list[int]:
        return [i for i in adj[node] if not removed[i]]

    def degree(node: str) -> int:
        return len(incident(node))

    for nid in list(adj):
        if degree(nid) >= 3:
            keep_nodes.add(nid)

    from collections import deque
    queue = deque(sorted(n for n in adj
                         if n not in keep_nodes and degree(n) == 2))
    new_edges: list[dict] = []
    while queue:
        node = queue.popleft()
        if node in keep_nodes or node in merged:
            continue
        inc = incident(node)
        if len(inc) != 2:
            continue
        e1, e2 = edges[inc[0]], edges[inc[1]]
        a = e1["to"] if e1["from"] == node else e1["from"]
        b = e2["to"] if e2["from"] == node else e2["from"]
        if a == b:
            keep_nodes.add(node)
            continue
        coords1 = list(e1["coordinates"])
        if e1["from"] == node:
            coords1 = coords1[::-1]
        coords2 = list(e2["coordinates"])
        if e2["to"] == node:
            coords2 = coords2[::-1]
        path = coords1[:-1] + coords2
        cleaned = []
        for c in path:
            if cleaned and cleaned[-1] == c:
                continue
            cleaned.append(c)
        metric = [project(c[0], c[1]) for c in cleaned]
        length = sum(math.hypot(metric[j][0] - metric[j - 1][0],
                                metric[j][1] - metric[j - 1][1])
                     for j in range(1, len(metric)))
        removed[inc[0]] = True
        removed[inc[1]] = True
        merged.add(node)
        new_edge = {
            "id": "HHE_" + _hash16(_canon({
                "from": a, "to": b,
                "edges": sorted((e1["id"], e2["id"])),
                "first": ["%.6f" % cleaned[0][0], "%.6f" % cleaned[0][1]],
                "last": ["%.6f" % cleaned[-1][0], "%.6f" % cleaned[-1][1]],
            })),
            "from": a, "to": b,
            "length_m": round(length, 6),
            "coordinates": cleaned,
        }
        new_edges.append(new_edge)
        idx = len(edges)
        edges.append(new_edge)
        removed.append(False)
        adj[a].add(idx)
        adj[b].add(idx)
        for neighbour in (a, b):
            if (neighbour not in keep_nodes and neighbour not in merged
                    and degree(neighbour) == 2):
                queue.append(neighbour)

    final = []
    for i, edge in enumerate(edges):
        if i < len(removed) and removed[i]:
            continue
        final.append(edge)
    final = sorted(final, key=lambda e: e["id"])
    for edge in final:
        node_coords.setdefault(edge["from"], edge["coordinates"][0][:2])
        node_coords.setdefault(edge["to"], edge["coordinates"][-1][:2])
    return final, node_coords


def _edge_metric(edge: dict) -> dict:
    metric = [project(c[0], c[1]) for c in edge["coordinates"]]
    cum = [0.0]
    for i in range(1, len(metric)):
        cum.append(cum[-1] + math.hypot(metric[i][0] - metric[i - 1][0],
                                        metric[i][1] - metric[i - 1][1]))
    return {"metric": metric, "cum": cum, "length": cum[-1]}


def _proximity_joins(edges: list[dict], node_coords: dict,
                     endpoint_ids: set, join_m: float) -> tuple[list[dict], list[dict]]:
    segs = [_edge_metric(e) for e in edges]
    bboxes = []
    for e in edges:
        lons = [c[0] for c in e["coordinates"]]
        lats = [c[1] for c in e["coordinates"]]
        bboxes.append((min(lons), max(lons), min(lats), max(lats)))
    incident: dict = defaultdict(set)
    for i, e in enumerate(edges):
        incident[e["from"]].add(i)
        incident[e["to"]].add(i)
    existing: set = set()
    for e in edges:
        key = (e["from"], e["to"]) if e["from"] < e["to"] else (e["to"], e["from"])
        existing.add(key)

    dl = join_m * _DEG_LON_PER_M
    dla = join_m * _DEG_LAT_PER_M
    splits: dict = defaultdict(list)
    joins: list[dict] = []
    for nid in sorted(endpoint_ids):
        lon, lat = node_coords[nid]
        px, py = project(lon, lat)
        best = None
        for i in range(len(edges)):
            if i in incident[nid]:
                continue
            bx0, bx1, by0, by1 = bboxes[i]
            if bx0 > lon + dl or bx1 < lon - dl or by0 > lat + dla or by1 < lat - dla:
                continue
            hit = _project_on_line(segs[i], px, py)
            if best is None or hit["distance"] < best["distance"]:
                best = {"distance": hit["distance"], "measure": hit["measure"],
                        "x": hit["x"], "y": hit["y"], "edge": i}
        if best is None or best["distance"] > join_m:
            continue
        lon_p = round(unproject(best["x"], best["y"])[0], 9)
        lat_p = round(unproject(best["x"], best["y"])[1], 9)
        length = segs[best["edge"]]["length"]
        if best["measure"] < _EPS or best["measure"] > length - _EPS:
            target_e = edges[best["edge"]]
            tid = target_e["from"] if best["measure"] < length / 2 else target_e["to"]
            key = (nid, tid) if nid < tid else (tid, nid)
            if key in existing or tid == nid:
                continue
            existing.add(key)
            joins.append({
                "id": "HHJ_" + _hash16(_canon({"a": nid, "b": tid})),
                "from": nid, "to": tid,
                "distance_m": round(best["distance"], 6),
                "coordinates": [[lon, lat], node_coords[tid][:2]],
            })
        else:
            snode = _node_id(lon_p, lat_p)
            if snode == nid:
                continue
            source_coords = edges[best["edge"]]["coordinates"]
            source_metric = segs[best["edge"]]
            index = min(len(source_coords) - 2, bisect_right(source_metric["cum"], best["measure"]) - 1)
            span = source_metric["cum"][index + 1] - source_metric["cum"][index]
            fraction = (best["measure"] - source_metric["cum"][index]) / span if span else 0.0
            elevation = source_coords[index][2] + fraction * (source_coords[index + 1][2] - source_coords[index][2])
            splits[best["edge"]].append({
                "measure": best["measure"], "node_id": snode,
                "wgs84": [lon_p, lat_p, elevation],
            })
            joins.append({
                "id": "HHJ_" + _hash16(_canon({"a": nid, "b": snode})),
                "from": nid, "to": snode,
                "distance_m": round(best["distance"], 6),
                "coordinates": [[lon, lat], [lon_p, lat_p]],
            })

    final = []
    for i, edge in enumerate(edges):
        cuts = splits.get(i)
        if not cuts:
            final.append(edge)
            continue
        seg = segs[i]
        cut_list = [{"measure": 0.0, "node_id": edge["from"], "wgs84": edge["coordinates"][0]},
                    {"measure": seg["length"], "node_id": edge["to"], "wgs84": edge["coordinates"][-1]}]
        cut_list.extend(cuts)
        cut_list.sort(key=lambda c: (c["measure"], c["node_id"]))
        for j in range(len(cut_list) - 1):
            a, b = cut_list[j], cut_list[j + 1]
            if b["measure"] - a["measure"] < _EPS or a["node_id"] == b["node_id"]:
                continue
            coords = [list(a["wgs84"])]
            for k in range(1, len(edge["coordinates"]) - 1):
                m = seg["cum"][k]
                if a["measure"] < m < b["measure"]:
                    coords.append(list(edge["coordinates"][k]))
            coords.append(list(b["wgs84"]))
            cleaned = []
            for c in coords:
                if cleaned and cleaned[-1] == c:
                    continue
                cleaned.append(c)
            if len(cleaned) < 2:
                continue
            metric = [project(c[0], c[1]) for c in cleaned]
            length = sum(math.hypot(metric[jj][0] - metric[jj - 1][0],
                                    metric[jj][1] - metric[jj - 1][1])
                         for jj in range(1, len(metric)))
            if length < _EPS:
                continue
            final.append({
                "id": "HHE_" + _hash16(_canon({
                    "from": a["node_id"], "to": b["node_id"],
                    "parent": edge["id"],
                    "start": round(a["measure"], 6), "end": round(b["measure"], 6),
                })),
                "from": a["node_id"], "to": b["node_id"],
                "length_m": round(length, 6),
                "coordinates": cleaned,
            })
    return final, joins


def _build(segs: list[tuple[str, list]], tolerance_m: float,
           proximity_m: float) -> dict:
    prepared = _prepare(segs)

    unique = sorted({(c[0], c[1]) for seg in prepared for c in seg["coords"]})
    uf = _UnionFind()
    for i in range(len(unique)):
        uf.add(str(i))
    lons = [c[0] for c in unique]
    win = proximity_m * _DEG_LON_PER_M
    win_la = proximity_m * _DEG_LAT_PER_M
    from bisect import bisect_left, bisect_right
    for i in range(len(unique)):
        lon, lat = unique[i]
        lo = bisect_left(lons, lon - win)
        hi = bisect_right(lons, lon + win)
        for j in range(lo, hi):
            if j <= i:
                continue
            if abs(unique[j][1] - lat) > win_la:
                continue
            ax, ay = project(lon, lat)
            bx, by = project(unique[j][0], unique[j][1])
            if math.hypot(bx - ax, by - ay) <= proximity_m:
                uf.union(str(i), str(j))

    root_coord: dict = {}
    for i in range(len(unique)):
        root = uf.find(str(i))
        root_coord.setdefault(root, unique[i])
    node_by_root: dict = {}
    for i in range(len(unique)):
        root = uf.find(str(i))
        if root not in node_by_root:
            node_by_root[root] = _node_id(root_coord[root][0], root_coord[root][1])
    coord_root = {}
    for i in range(len(unique)):
        coord_root[unique[i]] = uf.find(str(i))
    coord_node = {c: node_by_root[r] for c, r in coord_root.items()}

    # Elevation lookup: cluster root -> first observed elevation.
    elev_root: dict = {}
    for seg in prepared:
        for c in seg["coords"]:
            root = coord_root[(c[0], c[1])]
            if root not in elev_root and len(c) >= 3:
                elev_root[root] = c[2]

    edges: list[dict] = []
    for seg in prepared:
        chain = []
        for c in seg["coords"]:
            nid = coord_node[(c[0], c[1])]
            if not chain or chain[-1][0] != nid:
                chain.append((nid, tuple(c)))
        for i in range(len(chain) - 1):
            a_nid, a_coord = chain[i]
            b_nid, b_coord = chain[i + 1]
            if a_nid == b_nid:
                continue
            start_idx = None
            for k, c in enumerate(seg["coords"]):
                if (c[0], c[1]) == a_coord[:2]:
                    start_idx = k
                    break
            end_idx = None
            for k in range(len(seg["coords"]) - 1, -1, -1):
                c = seg["coords"][k]
                if (c[0], c[1]) == b_coord[:2]:
                    end_idx = k
                    break
            coords = []
            if start_idx is not None and end_idx is not None and start_idx < end_idx:
                coords = [list(c) for c in seg["coords"][start_idx:end_idx + 1]]
            if len(coords) < 2:
                coords = [list(a_coord), list(b_coord)]
            metric = [project(c[0], c[1]) for c in coords]
            length = sum(math.hypot(metric[j][0] - metric[j - 1][0],
                                    metric[j][1] - metric[j - 1][1])
                         for j in range(1, len(metric)))
            if length < _EPS:
                continue
            edges.append({
                "id": "HHE_" + _hash16(_canon({
                    "from": a_nid, "to": b_nid,
                    "route": seg["route_id"],
                    "start": "%.6f,%.6f" % (a_coord[0], a_coord[1]),
                    "end": "%.6f,%.6f" % (b_coord[0], b_coord[1]),
                })),
                "from": a_nid, "to": b_nid,
                "length_m": round(length, 6),
                "coordinates": coords,
            })

    node_coords: dict = {}
    for i in range(len(unique)):
        root = uf.find(str(i))
        nid = node_by_root[root]
        node_coords.setdefault(nid, list(root_coord[root]))
    for edge in edges:
        node_coords.setdefault(edge["from"], edge["coordinates"][0][:2])
        node_coords.setdefault(edge["to"], edge["coordinates"][-1][:2])

    keep_nodes = set()
    for seg in prepared:
        for c in (seg["coords"][0], seg["coords"][-1]):
            keep_nodes.add(coord_node[(c[0], c[1])])

    edges, node_coords = _simplify(edges, keep_nodes, node_coords)

    referenced = {nid for edge in edges for nid in (edge["from"], edge["to"])}
    node_coords = {nid: node_coords[nid] for nid in referenced}
    surviving_keep = keep_nodes & referenced

    edges, joins = _proximity_joins(edges, node_coords, surviving_keep, tolerance_m)
    for join in joins:
        node_coords.setdefault(join["from"], join["coordinates"][0])
        node_coords.setdefault(join["to"], join["coordinates"][-1])
    for edge in edges:
        node_coords.setdefault(edge["from"], edge["coordinates"][0][:2])
        node_coords.setdefault(edge["to"], edge["coordinates"][-1][:2])

    parent = {nid: nid for nid in node_coords}

    def cfind(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def cunion(a, b):
        ra, rb = cfind(a), cfind(b)
        if ra != rb:
            if ra < rb:
                parent[rb] = ra
            else:
                parent[ra] = rb

    for edge in edges:
        cunion(edge["from"], edge["to"])
    for join in joins:
        cunion(join["from"], join["to"])
    roots = defaultdict(int)
    for nid in node_coords:
        roots[cfind(nid)] += 1

    edge_geometry: dict = {}
    edge_topo = []
    for edge in edges:
        edge_geometry[edge["id"]] = edge["coordinates"]
        edge_topo.append({k: v for k, v in edge.items() if k != "coordinates"})
    join_topo = []
    for join in joins:
        edge_geometry[join["id"]] = join["coordinates"]
        join_topo.append({k: v for k, v in join.items() if k != "coordinates"})

    return {
        "schema_version": 2,
        "kind": "plan_graph",
        "dataset_id": "henrohub",
        "projection": {"kind": "equirectangular", "R": R, "lon0": LON0, "lat0": LAT0},
        "limitation": "equirectangular local projection: relative metric "
                      "distances are approximate (percent-level distortion away "
                      "from lat0=33.65); not a navigation-grade measurement.",
        "note": "browser-routing graph built from the Henro Hub (henro.app) "
                "route network (main + alternative only; connector/fallback "
                "excluded as non-walking glue). Vertices within %.0fm merge "
                "into routing nodes, parallel edges deduplicated and degree-2 "
                "chains collapsed; route endpoints are joined to their single "
                "nearest edge within %.0fm to bridge the gaps the linework has. "
                "Geometry kept 3D (elevation). Topology/geometry split: edge "
                "vertices live in edge_geometry, materialised only when a "
                "chosen route is drawn. Routing reference only (Henro Hub's own "
                "digitisation), not a navigation guarantee." % (proximity_m, tolerance_m),
        "nodes": [{"id": nid, "lon": node_coords[nid][0],
                   "lat": node_coords[nid][1]}
                  for nid in sorted(node_coords)],
        "traversal_edges": sorted(edge_topo, key=lambda e: e["id"]),
        "synthetic_joins": sorted(join_topo, key=lambda j: j["id"]),
        "edge_geometry": dict(sorted(edge_geometry.items())),
        "accounting": {
            "segments": len(prepared),
            "nodes": len(node_coords),
            "edges": len(edges),
            "synthetic_joins": len(joins),
            "geometry_points": sum(len(c) for c in edge_geometry.values()),
            "components": len(roots),
            "largest_component_nodes": max(roots.values(), default=0),
        },
    }


def _write_atomic(path: str, data: dict) -> None:
    directory = os.path.dirname(os.path.abspath(path)) or "."
    fd, temp = tempfile.mkstemp(prefix=".plan-graph.", suffix=".tmp",
                                dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False,
                      separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="datasets/henrohub/output/henrohub-routes.geojson")
    parser.add_argument("--output", default="datasets/henrohub/output/henrohub-plan-graph.json")
    parser.add_argument("--proximity-m", type=float, default=3.0,
                        help="vertex-merge radius (metres); only near-identical "
                             "overlapping vertices merge")
    parser.add_argument("--join-m", type=float, default=30.0,
                        help="route-endpoint proximity join radius (metres); "
                             "bridges gaps in the henrohub linework")
    args = parser.parse_args(argv)

    with open(args.input, encoding="utf-8") as stream:
        data = json.load(stream)
    validate_routes(data)
    segs = _line_parts(data.get("features", []))
    graph = _build(segs, args.join_m, args.proximity_m)
    validate_graph(graph, data)
    _write_atomic(args.output, graph)
    acct = graph["accounting"]
    print("build-henrohub-plan-graph: segments=%d nodes=%d edges=%d "
          "joins=%d components=%d largest=%d output=%s" % (
              acct["segments"], acct["nodes"], acct["edges"],
              acct["synthetic_joins"], acct["components"],
              acct["largest_component_nodes"], args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())