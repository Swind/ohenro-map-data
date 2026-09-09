"""Compact browser-routing graph export for the 88sekaiisan effective graph.

Consumes the Phase 3 ``anchored_route_graph`` (``build-anchors`` output) and
reduces it to exactly what the map-preview client-side planner needs. The
exported plan graph splits **topology from geometry**: routing runs only over
``traversal_edges`` (weight = ``length_m``) + ``synthetic_joins`` (weight =
``distance_m``), which carry node references but NO per-vertex coordinates;
the polyline geometry lives in a separate ``edge_geometry`` lookup
(``edge_id -> coordinates``) that is consulted only when a chosen route is
snapped or drawn. Source ``edges`` and provenance stay out.

The exact 88sekaiisan pipeline connects only bit-exact shared vertices and
zero-distance T-junctions, so independently digitised lines that overlap in
place (vertex of one route inside another, without an exact endpoint touch)
stay in separate components. ``build_plan_graph`` therefore adds a browser-only
bridging pass (``--bridge-m``): edges whose geometries come within that
tolerance are split at the contact and connected with synthetic joins, WITHOUT
touching the source ``edges`` or the anchored graph. This makes adjacent
overlapping official lines routable together while keeping the exact topology
as the authoritative source.

The interactive day-planning itself runs in the browser (map-preview/src/
planner.ts) over this exported graph; this module only builds that graph.
Byte-deterministic; written atomically via the shared ``normalize.write_atomic``.
"""

from __future__ import annotations

import hashlib
import json
import math
from bisect import bisect_left, bisect_right

from sekaiisan_henro import normalize, projection, sections

# Approximate degrees of lon/lat for one metre at the projection centre.
_DEG_LON_PER_M = 1.0 / (projection.R * math.cos(math.radians(projection.LAT0))
                        * math.pi / 180.0)
_DEG_LAT_PER_M = 1.0 / (projection.R * math.pi / 180.0)
_EPS = 1e-6


def _canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash16(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _node_id(lon: float, lat: float) -> str:
    return "SGP_" + _hash16(_canon({"lon": round(lon, 9), "lat": round(lat, 9)}))


def _line_metric(coords) -> dict:
    metric = [projection.project_point(c[0], c[1]) for c in coords]
    cum = [0.0]
    for i in range(1, len(metric)):
        cum.append(cum[-1] + math.hypot(metric[i][0] - metric[i - 1][0],
                                        metric[i][1] - metric[i - 1][1]))
    return {"metric": metric, "cum": cum, "length": cum[-1]}


def _pt_line_hit(line: dict, x: float, y: float) -> dict:
    """Nearest (distance, measure, x, y) of a metric point onto a polyline."""
    metric = line["metric"]
    cum = line["cum"]
    best = None
    for i in range(len(metric) - 1):
        ax, ay = metric[i]
        bx, by = metric[i + 1]
        abx = bx - ax
        aby = by - ay
        den = abx * abx + aby * aby
        t = ((x - ax) * abx + (y - ay) * aby) / den if den > 0 else 0.0
        t = max(0.0, min(1.0, t))
        qx = ax + t * abx
        qy = ay + t * aby
        dd = math.hypot(x - qx, y - qy)
        measure = cum[i] + t * (cum[i + 1] - cum[i])
        if best is None or dd < best["distance"]:
            best = {"distance": dd, "measure": measure, "x": qx, "y": qy}
    return best


def _bridge_overlaps(edges: list[dict], bridge_m: float,
                     same_component) -> tuple[list[dict], list[dict], list[dict]]:
    """Split near-overlapping edges and return (edges, joins, new_nodes).

    Every pair of edges from DIFFERENT base components whose geometries come
    within ``bridge_m`` is split at the closest contact; the two contact nodes
    are joined with an explicit synthetic join. Reuses an edge's own endpoint
    node when a contact lands on it. Deterministic; never touches source
    geometry beyond the split.
    """
    n = len(edges)
    if n == 0 or bridge_m <= 0:
        return edges, [], []
    lines = [_line_metric(e["coordinates"]) for e in edges]
    bboxes = []
    for e in edges:
        lons = [c[0] for c in e["coordinates"]]
        lats = [c[1] for c in e["coordinates"]]
        bboxes.append((min(lons), max(lons), min(lats), max(lats)))
    by_lon = sorted(range(n), key=lambda i: bboxes[i][0])
    lons = [bboxes[i][0] for i in by_lon]

    dl = bridge_m * _DEG_LON_PER_M
    dla = bridge_m * _DEG_LAT_PER_M
    contacts: dict = {}  # (i, j) -> (measure_i, wgs84_i, measure_j, wgs84_j)
    for pos, i in enumerate(by_lon):
        x0, x1, y0, y1 = bboxes[i]
        lo = bisect_left(lons, x0 - dl)
        hi = bisect_right(lons, x1 + dl)
        for k in range(lo, hi):
            j = by_lon[k]
            if k <= pos:
                continue
            if same_component(i, j):
                continue
            bx0, bx1, by0, by1 = bboxes[j]
            if bx1 < x0 - dl or bx0 > x1 + dl or by1 < y0 - dla or by0 > y1 + dla:
                continue
            best = None
            # vertices of i onto line j
            for vi, p in enumerate(lines[i]["metric"]):
                hit = _pt_line_hit(lines[j], p[0], p[1])
                if hit["distance"] < bridge_m and (best is None
                                                   or hit["distance"] < best["distance"]):
                    best = {"distance": hit["distance"],
                            "i_measure": lines[i]["cum"][vi],
                            "i_wgs84": edges[i]["coordinates"][vi],
                            "j_measure": hit["measure"],
                            "j_wgs84": [round(projection.unproject_point(hit["x"], hit["y"])[0], 9),
                                        round(projection.unproject_point(hit["x"], hit["y"])[1], 9)]}
            # vertices of j onto line i
            for vj, p in enumerate(lines[j]["metric"]):
                hit = _pt_line_hit(lines[i], p[0], p[1])
                if hit["distance"] < bridge_m and (best is None
                                                   or hit["distance"] < best["distance"]):
                    best = {"distance": hit["distance"],
                            "i_measure": hit["measure"],
                            "i_wgs84": [round(projection.unproject_point(hit["x"], hit["y"])[0], 9),
                                        round(projection.unproject_point(hit["x"], hit["y"])[1], 9)],
                            "j_measure": lines[j]["cum"][vj],
                            "j_wgs84": edges[j]["coordinates"][vj]}
            if best is not None:
                contacts[(i, j)] = best

    # Collect split points per edge.
    edge_cuts: dict = {}  # edge idx -> list of {"measure","node_id","wgs84"}
    joins: list[dict] = []
    new_nodes: dict = {}  # node id -> wgs84
    for (i, j), c in contacts.items():
        a_node = _split_node(edges[i], lines[i], c["i_measure"], c["i_wgs84"], edge_cuts, i, new_nodes)
        b_node = _split_node(edges[j], lines[j], c["j_measure"], c["j_wgs84"], edge_cuts, j, new_nodes)
        joins.append({
            "id": "SGPJ_" + _hash16(_canon({"a": a_node, "b": b_node})),
            "from": a_node, "to": b_node,
            "distance_m": round(c["distance"], 6),
            "coordinates": [list(c["i_wgs84"]), list(c["j_wgs84"])],
        })

    # Apply splits.
    final: list[dict] = []
    for i, edge in enumerate(edges):
        cuts = edge_cuts.get(i)
        if not cuts:
            final.append(edge)
            continue
        line = lines[i]
        cut_list = [{"measure": 0.0, "node_id": edge["from"], "wgs84": edge["coordinates"][0]},
                    {"measure": line["length"], "node_id": edge["to"], "wgs84": edge["coordinates"][-1]}]
        cut_list.extend(cuts)
        cut_list.sort(key=lambda c: (c["measure"], c["node_id"]))
        deduped = []
        for cut in cut_list:
            if deduped and abs(deduped[-1]["measure"] - cut["measure"]) < _EPS \
                    and deduped[-1]["node_id"] == cut["node_id"]:
                continue
            deduped.append(cut)
        for k in range(len(deduped) - 1):
            a, b = deduped[k], deduped[k + 1]
            if b["measure"] - a["measure"] < _EPS or a["node_id"] == b["node_id"]:
                continue
            coords = [list(a["wgs84"])]
            for v in range(1, len(edge["coordinates"]) - 1):
                m = line["cum"][v]
                if a["measure"] < m < b["measure"]:
                    coords.append(list(edge["coordinates"][v]))
            coords.append(list(b["wgs84"]))
            cleaned = []
            for c in coords:
                if cleaned and cleaned[-1] == c:
                    continue
                cleaned.append(c)
            if len(cleaned) < 2:
                continue
            metric = [projection.project_point(c[0], c[1]) for c in cleaned]
            length = sum(math.hypot(metric[j][0] - metric[j - 1][0],
                                    metric[j][1] - metric[j - 1][1])
                         for j in range(1, len(metric)))
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
    new_nodes_list = [{"id": nid, "lon": coords[0], "lat": coords[1]}
                      for nid, coords in sorted(new_nodes.items())]
    return final, joins, new_nodes_list


def _split_node(edge: dict, line: dict, measure: float, wgs84: list,
                edge_cuts: dict, edge_idx: int, new_nodes: dict) -> str:
    """Return the node id for a contact cut on an edge, reusing endpoints."""
    if abs(measure - 0.0) < _EPS:
        return edge["from"]
    if abs(measure - line["length"]) < _EPS:
        return edge["to"]
    nid = _node_id(wgs84[0], wgs84[1])
    new_nodes.setdefault(nid, wgs84)
    edge_cuts.setdefault(edge_idx, []).append(
        {"measure": measure, "node_id": nid, "wgs84": wgs84})
    return nid


def build_plan_graph(graph: dict, bridge_m: float = 5.0) -> dict:
    """Compact browser-routing graph for the map-preview client planner.

    Exactly the routing topology the interactive planner uses, reduced to what
    a browser Dijkstra needs: node coordinates plus undirected weighted edges
    with full geometry. Source ``edges`` and provenance stay out; the node set
    is exactly the endpoints referenced by ``traversal_edges`` and
    ``synthetic_joins`` (plus any ``--bridge-m`` overlap-bridging nodes).
    Byte-deterministic; written atomically by the caller.
    """
    sections.validate_anchored_graph(graph)
    node_coords: dict = {}
    for node in graph["nodes"] + graph["synthetic_nodes"] + graph["anchor_nodes"]:
        coords = node.get("coordinates")
        if coords:
            node_coords[node["id"]] = list(coords)
    traversal = [{
        "id": edge["id"], "from": edge["from"], "to": edge["to"],
        "length_m": edge["length_m"],
        "coordinates": [list(c) for c in edge["coordinates"]],
    } for edge in graph["traversal_edges"]]
    joins = []
    for join in graph["synthetic_joins"]:
        coords = join.get("coordinates")
        if not coords:
            if join["from"] not in node_coords or join["to"] not in node_coords:
                raise ValueError("synthetic join %s has no geometry and no node "
                                 "coordinates" % join["id"])
            coords = [node_coords[join["from"]], node_coords[join["to"]]]
        joins.append({
            "id": join["id"], "from": join["from"], "to": join["to"],
            "distance_m": join["distance_m"],
            "coordinates": [list(c) for c in coords],
        })

    if bridge_m > 0:
        # Only bridge pairs that are currently in different components, so
        # near-parallel edges already connected stay untouched.
        comp_parent = {nid: nid for nid in node_coords}

        def cfind(a):
            while comp_parent[a] != a:
                comp_parent[a] = comp_parent[comp_parent[a]]
                a = comp_parent[a]
            return a

        def cunion(a, b):
            ra, rb = cfind(a), cfind(b)
            if ra != rb:
                comp_parent[rb] = ra

        for edge in traversal:
            cunion(edge["from"], edge["to"])
        for join in joins:
            cunion(join["from"], join["to"])
        edge_root = [cfind(edge["from"]) for edge in traversal]

        def same_component(i: int, j: int) -> bool:
            return edge_root[i] == edge_root[j]

        traversal, bridge_joins, bridge_nodes = _bridge_overlaps(
            traversal, bridge_m, same_component)
        joins.extend(bridge_joins)
        for node in bridge_nodes:
            node_coords[node["id"]] = [node["lon"], node["lat"]]

    # Split topology from geometry: routing edges carry no per-vertex geometry;
    # the drawing/snapping geometry lives in a separate edge_id -> coordinates
    # lookup. This keeps the routing graph small (Dijkstra + node snapping
    # never touch polyline vertices) and defers geometry materialisation until
    # a chosen route actually needs to be drawn.
    edge_geometry: dict = {}
    topo = []
    for edge in traversal:
        edge_geometry[edge["id"]] = edge["coordinates"]
        topo.append({k: v for k, v in edge.items() if k != "coordinates"})
    join_topo = []
    for join in joins:
        edge_geometry[join["id"]] = join["coordinates"]
        join_topo.append({k: v for k, v in join.items() if k != "coordinates"})

    node_ids = sorted({
        nid for edge in topo for nid in (edge["from"], edge["to"])
    } | {nid for join in join_topo for nid in (join["from"], join["to"])})
    nodes = [{"id": nid, "lon": node_coords[nid][0], "lat": node_coords[nid][1]}
             for nid in node_ids]
    return {
        "schema_version": 2,
        "kind": "plan_graph",
        "dataset_id": graph["dataset_id"],
        "snapshot_sha256": graph["snapshot_sha256"],
        "projection": dict(graph["projection"]),
        "limitation": graph["limitation"],
        "note": "browser-routing graph with topology/geometry split: nodes + "
                "topology edges (no per-edge vertices) + edge_geometry lookup "
                "(edge_id -> coordinates, used only for snapping and drawing). "
                "The Dijkstra layer is tiny; geometry is materialised only when "
                "a chosen route is drawn. Overlapping lines within %.0fm are "
                "bridged with synthetic joins (browser-only; the exact topology "
                "stays authoritative)." % bridge_m,
        "nodes": nodes,
        "traversal_edges": sorted(topo, key=lambda e: e["id"]),
        "synthetic_joins": sorted(join_topo, key=lambda j: j["id"]),
        "edge_geometry": dict(sorted(edge_geometry.items())),
        "accounting": {
            "bridge_m": bridge_m,
            "bridged_edges": sum(
                1 for e in traversal if e["id"].startswith("OHE_")),
            "geometry_points": sum(
                len(c) for c in edge_geometry.values()),
            "components": 0,
        },
    }


def run_export_plan_graph(input_path: str, output_path: str, bridge_m: float = 5.0) -> dict:
    with open(input_path, encoding="utf-8") as stream:
        graph = json.load(stream)
    result = build_plan_graph(graph, bridge_m)
    normalize.write_atomic(output_path, result)
    return result


if __name__ == "__main__":
    raise SystemExit("use: python3 -m sekaiisan_henro export-plan-graph --help")