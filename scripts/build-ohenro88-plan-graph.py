#!/usr/bin/env python3
"""Build a browser PlanGraph from the OHenro 88 route GeoJSON.

Reads ``output/ohenro88-routes/ohenro88-routes.geojson`` (``kind=line``
LineString / MultiLineString features with ``[lon, lat, elev]`` coordinates)
and emits a PlanGraph in the SAME schema as ``sekaiisan_henro export-plan-graph``
(nodes + traversal_edges + synthetic_joins), so map-preview's ``planner.ts``
works unchanged.

The APK linework is independently digitised per route section: sections meet at
temples with small coordinate offsets (median ~2.6 m), and branches land on the
middle of other sections. Graph construction therefore uses a conservative
proximity model rather than exact-vertex topology:

* a node is created for every segment start/end and for every endpoint that
  lands on another segment's interior within ``--tolerance-m`` (a T-junction
  cut interpolated on the target);
* nodes whose coordinates are within ``--proximity-m`` are merged into a single
  routing node (this joins consecutive temple sections and branch endpoints to
  their T-cuts);
* segments are split at their own endpoints and at T-cuts into positive-length
  edges (weight = ``length_m`` via the shared equirectangular metric
  projection).

Overlapping linework (e.g. skip routes retracing main) stays as parallel edges;
the graph is a routing reference for day planning, never a navigation
guarantee. Output is deterministic (no timestamp, atomic write).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from collections import defaultdict

R = 6371008.8
LON0 = 133.75
LAT0 = 33.65
_COS = math.cos(math.radians(LAT0))
_RAD = math.pi / 180.0
_EPS = 1e-6

# Approximate degrees of lon/lat for one metre at the projection centre.
_DEG_LON_PER_M = 1.0 / (R * _COS * _RAD)
_DEG_LAT_PER_M = 1.0 / (R * _RAD)


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
    return "ON_" + _hash16(_canon({"lon": _quantize(lon), "lat": _quantize(lat)}))


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
            # Deterministic: the lexicographically smaller id is the root.
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
                segs.append((route_id, [[c[0], c[1]] for c in coords]))
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
    """Deduplicate parallel edges and collapse degree-2 chains.

    Overlapping routes create many parallel edges between the same merged node
    pairs (kept shortest) and long chains of degree-2 nodes (collapsed into a
    single edge that keeps the full geometry). Nodes in ``keep_nodes`` (route
    endpoints and junctions) never collapse, mirroring the 88sekaiisan junction
    graph. Deterministic.
    """
    # 1. dedupe parallel edges by unordered (from, to), keep the shortest.
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
            keep_nodes.add(node)  # both edges loop back to the same neighbour
            continue
        coords1 = list(e1["coordinates"])
        if e1["from"] != node:
            coords1 = coords1[::-1]  # orient to end at `node` (a -> node)
        coords2 = list(e2["coordinates"])
        if e2["to"] != node:
            coords2 = coords2[::-1]  # orient to start at `node` (node -> b)
        path = coords1[:-1] + coords2  # a ... node, node ... b
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
            "id": "OHE_" + _hash16(_canon({
                "from": a, "to": b,
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
        node_coords.setdefault(edge["from"], edge["coordinates"][0])
        node_coords.setdefault(edge["to"], edge["coordinates"][-1])
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
    """Bridge route-endpoint gaps conservatively.

    For each surviving route-endpoint node, find the SINGLE nearest point on
    any non-incident edge within ``join_m``. A projection that lands on a target
    endpoint connects the two nodes directly; an interior projection splits the
    target edge at that point and connects via the new node. This joins
    consecutive app sections across their real gaps (the linework itself has
    them) without fusing parallel geometry. Returns (final_edges, join_edges).
    """
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
    splits: dict = defaultdict(list)  # edge idx -> [{"measure","node_id","wgs84"}]
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
            # Lands on a target endpoint node: connect directly.
            target_e = edges[best["edge"]]
            tid = target_e["from"] if best["measure"] < length / 2 else target_e["to"]
            key = (nid, tid) if nid < tid else (tid, nid)
            if key in existing or tid == nid:
                continue
            existing.add(key)
            joins.append({
                "id": "OHJ_" + _hash16(_canon({"a": nid, "b": tid})),
                "from": nid, "to": tid,
                "distance_m": round(best["distance"], 6),
                "coordinates": [[lon, lat], node_coords[tid]],
            })
        else:
            # Interior: split the target edge at the projection point.
            snode = _node_id(lon_p, lat_p)
            splits[best["edge"]].append({
                "measure": best["measure"], "node_id": snode,
                "wgs84": [lon_p, lat_p],
            })
            joins.append({
                "id": "OHJ_" + _hash16(_canon({"a": nid, "b": snode})),
                "from": nid, "to": snode,
                "distance_m": round(best["distance"], 6),
                "coordinates": [[lon, lat], [lon_p, lat_p]],
            })

    # Apply splits: replace each split edge with sub-edges.
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
                "id": "OHE_" + _hash16(_canon({
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
    """Build a PlanGraph by merging nearby vertices into routing nodes.

    The APK linework is independently digitised: consecutive sections overlap
    or run close together (median ~0.5 m) but rarely share exact coordinates.
    ``proximity_m`` is the vertex-merge radius: every vertex whose neighbours
    lie within that radius collapse into one routing node, so overlapping
    routes become one topology. Each segment is then split into edges between
    consecutive distinct merged nodes, retaining every original vertex in the
    edge geometry.
    """
    prepared = _prepare(segs)

    # --- merge vertices within proximity_m into nodes (union-find) ---
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

    # Cluster representative = the first (sorted) coordinate; node id from it.
    root_coord: dict = {}
    for i in range(len(unique)):
        root = uf.find(str(i))
        root_coord.setdefault(root, unique[i])
    node_by_root: dict = {}
    for i in range(len(unique)):
        root = uf.find(str(i))
        if root not in node_by_root:
            node_by_root[root] = _node_id(root_coord[root][0], root_coord[root][1])
    # index of the root cluster for each exact unique coordinate
    coord_root = {}
    for i in range(len(unique)):
        coord_root[unique[i]] = uf.find(str(i))
    coord_node = {c: node_by_root[r] for c, r in coord_root.items()}

    # --- edges between consecutive distinct merged nodes per segment ---
    edges: list[dict] = []
    for seg in prepared:
        chain = []  # (node_id, coord) sequence with repeats collapsed
        for c in seg["coords"]:
            nid = coord_node[(c[0], c[1])]
            if not chain or chain[-1][0] != nid:
                chain.append((nid, tuple(c)))
        for i in range(len(chain) - 1):
            a_nid, a_coord = chain[i]
            b_nid, b_coord = chain[i + 1]
            if a_nid == b_nid:
                continue
            # Gather the original vertices between the two boundary points.
            start_idx = None
            for k, c in enumerate(seg["coords"]):
                if (c[0], c[1]) == a_coord:
                    start_idx = k
                    break
            end_idx = None
            for k in range(len(seg["coords"]) - 1, -1, -1):
                c = seg["coords"][k]
                if (c[0], c[1]) == b_coord:
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
                "id": "OHE_" + _hash16(_canon({
                    "from": a_nid, "to": b_nid,
                    "route": seg["route_id"],
                    "start": "%.6f,%.6f" % (a_coord[0], a_coord[1]),
                    "end": "%.6f,%.6f" % (b_coord[0], b_coord[1]),
                })),
                "from": a_nid, "to": b_nid,
                "length_m": round(length, 6),
                "coordinates": coords,
            })

    # --- node coordinate table ---
    node_coords: dict = {}
    for i in range(len(unique)):
        root = uf.find(str(i))
        nid = node_by_root[root]
        node_coords.setdefault(nid, list(root_coord[root]))
    for edge in edges:
        node_coords.setdefault(edge["from"], edge["coordinates"][0])
        node_coords.setdefault(edge["to"], edge["coordinates"][-1])

    # Route endpoints must survive chain collapse.
    keep_nodes = set()
    for seg in prepared:
        for c in (seg["coords"][0], seg["coords"][-1]):
            keep_nodes.add(coord_node[(c[0], c[1])])

    # --- simplify: dedupe parallel edges + collapse degree-2 chains ---
    edges, node_coords = _simplify(edges, keep_nodes, node_coords)

    # Keep only nodes actually referenced by a surviving edge (collapsed
    # degree-2 nodes are gone and not reported as fake isolated components).
    referenced = {nid for edge in edges for nid in (edge["from"], edge["to"])}
    node_coords = {nid: node_coords[nid] for nid in referenced}
    surviving_keep = keep_nodes & referenced

    # --- bridge real gaps between route endpoints (conservative joins) ---
    edges, joins = _proximity_joins(edges, node_coords, surviving_keep, tolerance_m)
    for join in joins:
        node_coords.setdefault(join["from"], join["coordinates"][0])
        node_coords.setdefault(join["to"], join["coordinates"][-1])
    for edge in edges:
        node_coords.setdefault(edge["from"], edge["coordinates"][0])
        node_coords.setdefault(edge["to"], edge["coordinates"][-1])

    # --- components over edges + joins ---
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

    return {
        "schema_version": 1,
        "kind": "plan_graph",
        "dataset_id": "ohenro88",
        "projection": {"kind": "equirectangular", "R": R, "lon0": LON0, "lat0": LAT0},
        "limitation": "equirectangular local projection: relative metric "
                      "distances are approximate (percent-level distortion away "
                      "from lat0=33.65); not a navigation-grade measurement.",
        "note": "browser-routing graph built from the OHenro 88 app route "
                "GeoJSON: vertices within %.0fm are merged into routing nodes, "
                "parallel edges deduplicated and degree-2 chains collapsed into "
                "single edges; route endpoints are then joined to their single "
                "nearest edge within %.0fm (interior joins split the edge) to "
                "bridge the gaps the linework itself has. Routing reference "
                "only, not a navigation guarantee." % (proximity_m, tolerance_m),
        "nodes": [{"id": nid, "lon": node_coords[nid][0],
                   "lat": node_coords[nid][1]}
                  for nid in sorted(node_coords)],
        "traversal_edges": sorted(edges, key=lambda e: e["id"]),
        "synthetic_joins": sorted(joins, key=lambda j: j["id"]),
        "accounting": {
            "segments": len(prepared),
            "nodes": len(node_coords),
            "edges": len(edges),
            "synthetic_joins": len(joins),
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
    parser.add_argument("--input", default="output/ohenro88-routes/ohenro88-routes.geojson")
    parser.add_argument("--output", default="output/ohenro88-routes/ohenro88-plan-graph.json")
    parser.add_argument("--proximity-m", type=float, default=15.0,
                        help="vertex-merge radius (metres); overlapping routes "
                             "closer than this become one routing topology")
    parser.add_argument("--join-m", type=float, default=90.0,
                        help="route-endpoint proximity join radius (metres); "
                             "bridges real gaps in the app linework")
    args = parser.parse_args(argv)

    with open(args.input, encoding="utf-8") as stream:
        data = json.load(stream)
    segs = _line_parts(data.get("features", []))
    graph = _build(segs, args.join_m, args.proximity_m)
    _write_atomic(args.output, graph)
    acct = graph["accounting"]
    print("build-ohenro88-plan-graph: segments=%d nodes=%d edges=%d "
          "joins=%d components=%d largest=%d output=%s" % (
              acct["segments"], acct["nodes"], acct["edges"],
              acct["synthetic_joins"], acct["components"],
              acct["largest_component_nodes"], args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())