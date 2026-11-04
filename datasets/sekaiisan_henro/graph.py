"""Phase 2B exact-only route graph construction for 88sekaiisan.

Builds an undirected, auditable graph from a normalized route document plus its
Phase 2A topology inventory, using ONLY exact source evidence:

* every route start/end is a graph node;
* canonical WGS84 source vertices shared by >=2 route records are nodes and
  connect those routes;
* exact geometric endpoint-on-other-line-interior touches (inventory
  ``intersections.endpoint_touches``) become exact T nodes: the target line is
  split at the exact intersection and the endpoint route connects to that same
  node;
* source-shared internal vertices connect;
* interior/interior ``ambiguous_crossing`` intersections stay UNCONNECTED and
  never become shared nodes.

There is deliberately NO proximity behaviour: no endpoint clustering, no <=5m
join, no movement/snapping, no synthetic connector, no temple anchor. Later
Phase 2C will add conservative proximity connections; this milestone is the
trustworthy exact graph base.

This module never mutates normalized geometry and writes byte-deterministically
(temp -> flush -> fsync -> replace). On failure the prior output is untouched.
"""

from __future__ import annotations

import hashlib
import json

from shapely.geometry import LineString, Point

from datasets.sekaiisan_henro import normalize
from datasets.sekaiisan_henro.projection import (
    PROJECTION_METADATA,
    limitation_note,
    project_point,
    unproject_point,
)

# --- determinism / tolerance constants (documented) -------------------------

# Metric "same point" epsilon (metres) for cut de-duplication.
_EPS = 1e-9
# Metric "effectively at an endpoint" epsilon (metres) for resolving which route
# of an endpoint_touch record owns the endpoint.
_AT_ENDPOINT_EPS = 1e-6
# Per-route length reconstruction tolerance: pass if the absolute error is
# below _LENGTH_TOL_ABS metres OR below _LENGTH_TOL_REL relative to the source
# length. (A single source line split into edges is partitioned exactly, so the
# real error is float-rounding-scale; these bounds are generous but clear.)
_LENGTH_TOL_ABS = 1e-5
_LENGTH_TOL_REL = 1e-9

# Canonical / ID quantization: every coordinate fed into a node/edge ID hash is
# quantized to _ID_QUANT degrees (default 1e-9 deg ~ 0.1 mm). This keeps IDs
# stable for unchanged geometry while never being the sole distinguishing input
# (source refs and kinds are also hashed). Quantization rules: v -> round(v /
# _ID_QUANT) * _ID_QUANT, applied per-axis to WGS84 lon/lat only.
_ID_QUANT = 1e-9
# SHA-256 truncation width (hex chars) for SHN_/SHE_/SHC_ IDs.
_ID_LEN = 16

_POSITIONS = ("start", "end", "interior")

# Strength order for de-duplicating cuts that share a metric position and
# topology group: keep the strongest kind flag so merged connectivity evidence
# is never weakened.
_KIND_STRENGTH = {"endpoint": 1, "shared_vertex": 2, "exact_t_junction": 3}


def _quantize(value: float) -> float:
    return round(value / _ID_QUANT) * _ID_QUANT


def _canon(obj) -> str:
    """Deterministic canonical JSON (sorted keys, compact separators)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash16(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:_ID_LEN]


# --- validation --------------------------------------------------------------


def validate_normalized(data: dict) -> None:
    """Validate the normalized schema; raise ValueError on any issue."""
    if not isinstance(data, dict):
        raise ValueError("normalized input must be a JSON object")
    for key in ("schema_version", "dataset_id", "snapshot_sha256", "routes", "accounting"):
        if key not in data:
            raise ValueError("normalized input missing required key: %s" % key)
    routes = data["routes"]
    if not isinstance(routes, list):
        raise ValueError("normalized 'routes' must be a list")
    seen = set()
    for idx, route in enumerate(routes):
        if not isinstance(route, dict) or "id" not in route:
            raise ValueError("route record %d missing 'id'" % idx)
        route_id = route["id"]
        if route_id in seen:
            raise ValueError("duplicate route id in normalized: %s" % route_id)
        seen.add(route_id)
        geometry = route.get("geometry")
        if not isinstance(geometry, dict) or geometry.get("type") != "LineString":
            raise ValueError("route %s geometry must be a LineString" % route_id)
        coords = geometry.get("coordinates")
        if not isinstance(coords, list) or len(coords) < 2:
            raise ValueError("route %s LineString must have >=2 coordinates" % route_id)
        for coord in coords:
            if not (isinstance(coord, (list, tuple)) and len(coord) >= 2):
                raise ValueError("route %s has a malformed coordinate" % route_id)


def validate_inventory(data: dict) -> None:
    """Validate the topology inventory schema; raise ValueError on issues."""
    if not isinstance(data, dict):
        raise ValueError("inventory input must be a JSON object")
    if data.get("kind") != "topology_inventory":
        raise ValueError("inventory must be kind=topology_inventory, got %r"
                         % data.get("kind"))
    for key in ("dataset_id", "snapshot_sha256", "exact_connections", "intersections",
                "route_sources", "source_accounting"):
        if key not in data:
            raise ValueError("inventory missing required key: %s" % key)
    for section in ("exact_connections", "intersections"):
        if not isinstance(data[section], dict):
            raise ValueError("inventory %s must be an object" % section)
    if not isinstance(data["intersections"].get("endpoint_touches"), list):
        raise ValueError("inventory intersections.endpoint_touches must be a list")
    if not isinstance(data["intersections"].get("duplicate_geometries"), list):
        raise ValueError("inventory intersections.duplicate_geometries must be a list")
    if not isinstance(data["intersections"].get("linear_overlaps"), list):
        raise ValueError("inventory intersections.linear_overlaps must be a list")


# --- route entries -----------------------------------------------------------


def _coord_tuple(coord):
    return (coord[0], coord[1])


def _vertex_kind(count: int, vertex_index: int) -> str:
    if vertex_index == 0:
        return "start"
    if vertex_index == count - 1:
        return "end"
    return "interior"


def _load_entries(data: dict) -> list[dict]:
    """Project routes, drop/count consecutive duplicates, fail if degenerate.

    Returns analysis-only records; the raw normalized data is never mutated.
    """
    entries = []
    for route in data["routes"]:
        coords = [_coord_tuple(c) for c in route["geometry"]["coordinates"]]
        cleaned = []
        duplicate_count = 0
        for coord in coords:
            if cleaned and cleaned[-1] == coord:
                duplicate_count += 1
            else:
                cleaned.append(coord)
        if len(cleaned) < 2:
            raise ValueError(
                "route %s degenerate after removing consecutive duplicates: <2 points"
                % route["id"])
        metric = [project_point(*coord) for coord in cleaned]
        line = LineString(metric)
        # Cumulative metric length at each vertex.
        cum = [0.0]
        for prev, cur in zip(metric, metric[1:]):
            cum.append(cum[-1] + ((cur[0] - prev[0]) ** 2 + (cur[1] - prev[1]) ** 2) ** 0.5)
        entries.append({
            "id": route["id"],
            "prefecture": route.get("prefecture"),
            "source_file": route.get("source_file"),
            "source_fid": route.get("source_fid"),
            "part": route.get("part"),
            "source_identity": route.get("source_identity"),
            "source_identity_kind": route.get("source_identity_kind"),
            "geometry_sha256": route.get("geometry_sha256"),
            "wgs84": cleaned,
            "metric": metric,
            "line": line,
            "length": line.length,
            "cum": cum,
            "duplicate_count": duplicate_count,
            "source_point_count": len(coords),
        })
    return entries


# --- node groups -------------------------------------------------------------


def _build_groups(entries: list[dict]) -> dict:
    """Build node groups keyed by representative exact WGS84 coordinate.

    A group dict is ``{coord_tuple: {"refs": set, "shared": bool}}`` where a ref
    is ``(route_id, position, vertex_index_or_None)``. Groups are created for
    (a) every canonical coordinate shared by >=2 distinct routes and (b) every
    isolated route start/end. Endpoint-touch target refs are added later.
    """
    occurrences: dict = {}
    for entry in entries:
        for vertex_index, coord in enumerate(entry["wgs84"]):
            occurrences.setdefault(coord, []).append((entry["id"], vertex_index))

    shared_coords = set()
    for coord, members in occurrences.items():
        routes = {route_id for route_id, _ in members}
        if len(routes) >= 2:
            shared_coords.add(coord)

    groups: dict = {}
    for coord, members in sorted(occurrences.items()):
        routes = {route_id for route_id, _ in members}
        shared = len(routes) >= 2
        if shared:
            refs = set()
            for route_id, vertex_index in members:
                kind = _vertex_kind(len(_entry_by_id(entries, route_id)["wgs84"]),
                                    vertex_index)
                refs.add((route_id, kind, vertex_index))
            groups[coord] = {"refs": refs, "shared": True}

    for entry in entries:
        n = len(entry["wgs84"])
        for vertex_index in (0, n - 1):
            coord = entry["wgs84"][vertex_index]
            if coord in shared_coords:
                continue  # already created a shared group
            kind = _vertex_kind(n, vertex_index)
            group = groups.setdefault(coord, {"refs": set(), "shared": False})
            group["refs"].add((entry["id"], kind, vertex_index))
    return groups


def _entry_by_id(entries: list[dict], route_id: str) -> dict:
    return next(e for e in entries if e["id"] == route_id)


def _process_endpoint_touches(entries: list[dict], inventory: dict,
                              groups: dict, target_cuts: dict) -> tuple[int, int]:
    """Resolve exact endpoint-on-other-line-interior T-junctions.

    Returns (applied, skipped). ``applied`` counts T-junctions created; a record
    is skipped when both routes have an endpoint at the intersection point
    (near-coincident but WGS84-distinct endpoints) — that is a proximity-like
    situation and exact-only leaves them disconnected.
    """
    by_id = {e["id"]: e for e in entries}
    applied = 0
    skipped = 0
    for rec in inventory["intersections"]["endpoint_touches"]:
        endpoint_entry = by_id[rec["route_a"]]
        target_entry = by_id[rec["route_b"]]
        px, py = project_point(*rec["coordinates"])
        p = Point(px, py)

        def _at_end(entry) -> bool:
            return (p.distance(Point(entry["metric"][0])) < _AT_ENDPOINT_EPS or
                    p.distance(Point(entry["metric"][-1])) < _AT_ENDPOINT_EPS)

        a_end = _at_end(endpoint_entry)
        b_end = _at_end(target_entry)
        if a_end and b_end:
            skipped += 1
            continue
        if a_end:
            endpoint, target = endpoint_entry, target_entry
        elif b_end:
            endpoint, target = target_entry, endpoint_entry
        else:
            # Both interior: not an endpoint_touch; ignore defensively.
            skipped += 1
            continue
        if p.distance(Point(endpoint["metric"][0])) < p.distance(Point(endpoint["metric"][-1])):
            ecoord = endpoint["wgs84"][0]
            ekind = "start"
        else:
            ecoord = endpoint["wgs84"][-1]
            ekind = "end"
        group = groups.setdefault(ecoord, {"refs": set(), "shared": False})
        group["refs"].add((endpoint["id"], ekind, 0 if ekind == "start" else len(endpoint["wgs84"]) - 1))
        group["refs"].add((target["id"], "interior", None))
        s = target["line"].project(p)
        target_cuts.setdefault(target["id"], []).append({
            "s": s,
            "point": (px, py),
            "wgs84": unproject_point(px, py),
            "group": ecoord,
            "kind": "exact_t_junction",
            "is_vertex": False,
        })
        applied += 1
    return applied, skipped


# --- splitting ---------------------------------------------------------------


def _route_cuts(entry: dict, shared_coords: set, target_cuts: list) -> list[dict]:
    """Collect this route's cut points: start/end, shared vertices, T targets."""
    n = len(entry["wgs84"])
    cuts = []
    for vertex_index in (0, n - 1):
        coord = entry["wgs84"][vertex_index]
        cuts.append({
            "s": entry["cum"][vertex_index],
            "point": entry["metric"][vertex_index],
            "wgs84": coord,
            "group": coord,
            "kind": "endpoint",
            "is_vertex": True,
        })
    for vertex_index in range(1, n - 1):
        coord = entry["wgs84"][vertex_index]
        if coord in shared_coords:
            cuts.append({
                "s": entry["cum"][vertex_index],
                "point": entry["metric"][vertex_index],
                "wgs84": coord,
                "group": coord,
                "kind": "shared_vertex",
                "is_vertex": True,
            })
    cuts.extend(target_cuts)
    # Sort by position along the line; deterministic tie-break by group then kind.
    cuts.sort(key=lambda c: (c["s"], _canon(c["group"]), c["kind"]))
    # De-duplicate cuts at the same metric position. Two cuts at the same
    # position must belong to the SAME topology group (they are the same
    # junction); if they differ, that would silently lose connectivity, so we
    # fail explicitly rather than pick one. For a same-group collision we keep
    # the strongest kind flag and the exact source vertex coordinate when one of
    # the colliding cuts is a true source vertex (an interpolated cut's point is
    # only kept if it is the sole representative).
    deduped = []
    for cut in cuts:
        if deduped and abs(deduped[-1]["s"] - cut["s"]) < _EPS:
            prev = deduped[-1]
            if prev["group"] != cut["group"]:
                raise ValueError(
                    "route %s conflicting cuts at measure %.6fm: topology groups "
                    "%s and %s" % (entry["id"], cut["s"],
                                   _canon(prev["group"]), _canon(cut["group"])))
            if _KIND_STRENGTH[cut["kind"]] > _KIND_STRENGTH[prev["kind"]]:
                prev["kind"] = cut["kind"]
            if cut["is_vertex"] and not prev["is_vertex"]:
                prev["is_vertex"] = True
                prev["wgs84"] = cut["wgs84"]
                prev["point"] = cut["point"]
            continue
        deduped.append(cut)
    return deduped


def _split_route(entry: dict, cuts: list[dict]) -> list[dict]:
    """Split a route into ordered edges between consecutive cuts.

    Retains every intermediate source vertex byte/value-identically; an interior
    (non-vertex) cut interpolates only that exact cut point via the inverse
    projection. Never uses a blanket Shapely substring that rewrites points.
    """
    wgs84 = entry["wgs84"]
    cum = entry["cum"]
    n = len(wgs84)
    segments = []
    for i in range(len(cuts) - 1):
        a, b = cuts[i], cuts[i + 1]
        seg = [a["wgs84"]]
        for k in range(n):
            if a["s"] < cum[k] < b["s"]:
                seg.append(wgs84[k])
        seg.append(b["wgs84"])
        cleaned = []
        for coord in seg:
            if cleaned and cleaned[-1] == coord:
                continue
            cleaned.append(coord)
        if len(cleaned) < 2:
            raise ValueError("route %s produced a degenerate edge" % entry["id"])
        metric = [project_point(*c) for c in cleaned]
        length = sum(
            ((metric[j][0] - metric[j - 1][0]) ** 2 + (metric[j][1] - metric[j - 1][1]) ** 2) ** 0.5
            for j in range(1, len(metric))
        )
        segments.append({
            "from_group": a["group"],
            "to_group": b["group"],
            "coordinates": cleaned,
            "length_m": length,
            "from_cut": a,
            "to_cut": b,
        })
    return segments


# --- node / edge identity ----------------------------------------------------


def _node_kinds(group: dict, coord: tuple) -> list[str]:
    kinds = set()
    positions = {ref[1] for ref in group["refs"]}
    routes = {ref[0] for ref in group["refs"]}
    if positions & {"start", "end"}:
        kinds.add("endpoint")
    if group["shared"]:
        kinds.add("shared_vertex")
    if len(routes) >= 2 and positions & {"start", "end"} and "interior" in positions:
        kinds.add("exact_t_junction")
    return sorted(kinds)


def _node_source_refs(group: dict) -> list[dict]:
    refs = []
    for route_id, position, index in group["refs"]:
        refs.append({"route_id": route_id, "position": position,
                     "index": index if index is not None else None})
    refs.sort(key=lambda r: (r["route_id"], _POSITIONS.index(r["position"]),
                             -1 if r["index"] is None else r["index"]))
    return refs


def _build_nodes(groups: dict) -> tuple[dict, dict]:
    """Build node dicts keyed by node ID; also returns group->node_id map.

    Raises ValueError on any ID collision (two distinct groups hashing equal).
    """
    nodes: dict = {}
    group_to_node: dict = {}
    for coord, group in sorted(groups.items()):
        kinds = _node_kinds(group, coord)
        refs = _node_source_refs(group)
        node_id = "SHN_" + _hash16(_canon({
            "coord": [_quantize(coord[0]), _quantize(coord[1])],
            "refs": refs,
            "kinds": kinds,
        }))
        if node_id in nodes and nodes[node_id] is not group:
            raise ValueError("node ID collision: %s" % node_id)
        group_to_node[coord] = node_id
        nodes[node_id] = {
            "id": node_id,
            "coordinates": [coord[0], coord[1]],
            "lon": coord[0],
            "lat": coord[1],
            "kinds": kinds,
            "source_refs": refs,
        }
    return nodes, group_to_node


def _build_edges(entries: list[dict], segments_by_route: dict,
                 group_to_node: dict) -> list[dict]:
    """Build edge dicts from split segments; raises ValueError on ID collision."""
    edges: dict = {}
    for entry in entries:
        for seg in segments_by_route[entry["id"]]:
            from_id = group_to_node[seg["from_group"]]
            to_id = group_to_node[seg["to_group"]]
            provenance = {
                "route_id": entry["id"],
                "prefecture": entry["prefecture"],
                "source_file": entry["source_file"],
                "source_fid": entry["source_fid"],
                "source_identity": entry["source_identity"],
                "source_identity_kind": entry["source_identity_kind"],
                "part": entry["part"],
                "source_start_measure": seg["from_cut"]["s"],
                "source_end_measure": seg["to_cut"]["s"],
            }
            if entry["geometry_sha256"] is not None:
                provenance["geometry_sha256"] = entry["geometry_sha256"]
            canonical_geom = [[_quantize(x), _quantize(y)] for x, y in seg["coordinates"]]
            ordered_ids = sorted((from_id, to_id))
            edge_id = "SHE_" + _hash16(_canon({
                "from": ordered_ids[0],
                "to": ordered_ids[1],
                "geometry": canonical_geom,
                "provenance": provenance,
            }))
            if edge_id in edges:
                raise ValueError("edge ID collision: %s" % edge_id)
            edges[edge_id] = {
                "id": edge_id,
                "from": from_id,
                "to": to_id,
                "coordinates": [list(c) for c in seg["coordinates"]],
                "length_m": seg["length_m"],
                "provenance": provenance,
            }
    return edges


# --- components --------------------------------------------------------------


def _components(nodes: dict, edges: dict) -> list[dict]:
    parent = {nid: nid for nid in nodes}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for edge in edges.values():
        union(edge["from"], edge["to"])
    members = {}
    for nid in nodes:
        members.setdefault(find(nid), []).append(nid)
    edge_members = {}
    for edge in edges.values():
        edge_members.setdefault(find(edge["from"]), []).append(edge["id"])
    components = []
    for root, member_ids in members.items():
        member_ids = sorted(member_ids)
        edge_ids = sorted(edge_members.get(root, []))
        comp_id = "SHC_" + _hash16(_canon(member_ids))
        components.append({
            "id": comp_id,
            "node_count": len(member_ids),
            "edge_count": len(edge_ids),
            "nodes": member_ids,
            "edges": edge_ids,
        })
    components.sort(key=lambda c: c["id"])
    return components


# --- orchestration -----------------------------------------------------------


def _length_validation(entries: list[dict], edges_by_route: dict) -> dict:
    """Per-route and global length reconstruction; fail on out-of-tolerance."""
    global_original = 0.0
    global_reconstructed = 0.0
    max_abs = 0.0
    max_rel = 0.0
    per_route = {}
    for entry in entries:
        recon = sum(e["length_m"] for e in edges_by_route[entry["id"]])
        original = entry["length"]
        err = abs(original - recon)
        rel = err / original if original else 0.0
        if err > _LENGTH_TOL_ABS and err > _LENGTH_TOL_REL * original:
            raise ValueError(
                "route %s length reconstruction error %.3e m exceeds tolerance "
                "(abs %.1e / rel %.1e)" % (entry["id"], err, _LENGTH_TOL_ABS, _LENGTH_TOL_REL))
        global_original += original
        global_reconstructed += recon
        max_abs = max(max_abs, err)
        max_rel = max(max_rel, rel)
        per_route[entry["id"]] = {"original_m": original, "reconstructed_m": recon,
                                  "error_m": err}
    return {
        "global_original_m": global_original,
        "global_reconstructed_m": global_reconstructed,
        "max_absolute_error_m": max_abs,
        "max_relative_error": max_rel,
        "per_route": per_route,
    }


def build_graph(data: dict, inventory: dict) -> dict:
    """Build the deterministic exact-only graph document.

    ``data`` is the normalized document and ``inventory`` its Phase 2A topology
    inventory (same snapshot). Raises ValueError on schema/accounting mismatch,
    unsupported duplicates/overlaps, ID collision, or length reconstruction
    failure.
    """
    validate_normalized(data)
    validate_inventory(inventory)

    if data["dataset_id"] != inventory["dataset_id"]:
        raise ValueError("dataset mismatch: normalized=%r inventory=%r"
                         % (data["dataset_id"], inventory["dataset_id"]))
    if data["snapshot_sha256"] != inventory["snapshot_sha256"]:
        raise ValueError("snapshot mismatch: normalized=%r inventory=%r"
                         % (data["snapshot_sha256"], inventory["snapshot_sha256"]))
    if data["accounting"] != inventory["source_accounting"]:
        raise ValueError("source accounting mismatch between normalized and inventory")

    # Fail explicitly on unsupported multi-provenance geometry.
    duplicates = inventory["intersections"]["duplicate_geometries"]
    overlaps = inventory["intersections"]["linear_overlaps"]
    if duplicates or overlaps:
        raise ValueError(
            "unsupported: inventory reports %d duplicate geometries and %d linear "
            "overlaps; exact-only Phase 2B cannot represent multi-provenance "
            "silently" % (len(duplicates), len(overlaps)))

    ambiguous = inventory["intersections"]["ambiguous_crossings"]
    if not isinstance(ambiguous, list):
        raise ValueError("inventory intersections.ambiguous_crossings must be a list")

    entries = _load_entries(data)
    source_accounting = data["accounting"]
    total_source_points = sum(e["source_point_count"] for e in entries)
    if source_accounting.get("linestrings") != len(entries):
        raise ValueError("source accounting mismatch: normalized linestrings=%r "
                         "analyzed=%d" % (source_accounting.get("linestrings"), len(entries)))
    if source_accounting.get("points") != total_source_points:
        raise ValueError("source accounting mismatch: normalized points=%r "
                         "analyzed=%d" % (source_accounting.get("points"), total_source_points))

    groups = _build_groups(entries)
    shared_coords = {coord for coord, g in groups.items() if g["shared"]}
    target_cuts: dict = {}
    touches_applied, touches_skipped = _process_endpoint_touches(
        entries, inventory, groups, target_cuts)

    segments_by_route: dict = {}
    cut_counts = {"endpoint": 0, "shared_vertex": 0, "exact_t_junction": 0}
    for entry in entries:
        cuts = _route_cuts(entry, shared_coords, target_cuts.get(entry["id"], []))
        for cut in cuts:
            cut_counts[cut["kind"]] += 1
        segments_by_route[entry["id"]] = _split_route(entry, cuts)

    nodes, group_to_node = _build_nodes(groups)
    edges = _build_edges(entries, segments_by_route, group_to_node)

    # Every ambiguous crossing must stay unconnected: we never create cuts at
    # ambiguous crossings, so assert no crossing point became a node junction.
    components = _components(nodes, edges)
    isolated_components = sum(1 for c in components if c["edge_count"] == 0)
    largest_component = max(components, key=lambda c: (c["node_count"], c["id"]))

    edges_by_route = {entry["id"]: [] for entry in entries}
    for edge in edges.values():
        edges_by_route[edge["provenance"]["route_id"]].append(edge)
    lengths = _length_validation(entries, edges_by_route)

    exact_shared = inventory["exact_connections"]
    exact_summary = exact_shared.get("summary", {})
    exact_consumed = {
        "shared_vertex_groups": sum(1 for g in groups.values() if g["shared"]),
        "endpoint_touches_applied": touches_applied,
        "endpoint_touches_skipped_both_endpoint_near_coincident": touches_skipped,
        "from_inventory": {
            "shared_endpoints": exact_summary.get("shared_endpoints", 0),
            "endpoint_to_vertex": exact_summary.get("endpoint_to_vertex", 0),
            "shared_internal_vertices": exact_summary.get("shared_internal_vertices", 0),
            "endpoint_touches": len(inventory["intersections"]["endpoint_touches"]),
        },
    }

    route_sources = {}
    for entry in entries:
        info = {
            "prefecture": entry["prefecture"],
            "source_file": entry["source_file"],
            "source_fid": entry["source_fid"],
            "part": entry["part"],
        }
        if entry["source_identity"] is not None:
            info["source_identity"] = entry["source_identity"]
        if entry["source_identity_kind"] is not None:
            info["source_identity_kind"] = entry["source_identity_kind"]
        if entry["geometry_sha256"] is not None:
            info["geometry_sha256"] = entry["geometry_sha256"]
        route_sources[entry["id"]] = info

    sorted_nodes = [nodes[nid] for nid in sorted(nodes)]
    sorted_edges = [edges[eid] for eid in sorted(edges)]

    return {
        "schema_version": 1,
        "kind": "exact_route_graph",
        "dataset_id": data["dataset_id"],
        "snapshot_sha256": data["snapshot_sha256"],
        "projection": dict(PROJECTION_METADATA),
        "limitation": limitation_note(),
        "note": "exact-only undirected graph built from source evidence: shared "
                "canonical WGS84 vertices, exact endpoint touches (T nodes), and "
                "route endpoints. No proximity clustering, no snapping, no "
                "movement, no synthetic connector, no temple anchor. Ambiguous "
                "interior/interior crossings and proximity candidates remain "
                "unconnected.",
        "route_sources": route_sources,
        "nodes": sorted_nodes,
        "edges": sorted_edges,
        "components": components,
        "accounting": {
            "source_routes": source_accounting.get("routes"),
            "source_linestrings": len(entries),
            "source_points": total_source_points,
            "nodes": len(nodes),
            "edges": len(edges),
            "components": len(components),
            "isolated_components": isolated_components,
            "largest_component_nodes": largest_component["node_count"],
            "largest_component_edges": largest_component["edge_count"],
            "cut_counts": cut_counts,
            "lengths": {
                "global_original_m": lengths["global_original_m"],
                "global_reconstructed_m": lengths["global_reconstructed_m"],
                "max_absolute_error_m": lengths["max_absolute_error_m"],
                "max_relative_error": lengths["max_relative_error"],
                "per_route": lengths["per_route"],
            },
            "exact_connections_consumed": exact_consumed,
            "proximity_connections_applied": 0,
            "ambiguous_crossings_connected": 0,
            "ambiguous_crossings_total": len(ambiguous),
            "note": "exact-only: proximity_connections_applied=0, "
                    "ambiguous_crossings_connected=0; Phase 2C will add "
                    "conservative proximity connections.",
        },
    }


def run_graph(input_path: str, inventory_path: str, output_path: str) -> dict:
    """Load normalized + inventory JSON, build the graph, write atomically.

    On failure the prior output (if any) is left untouched.
    """
    with open(input_path, encoding="utf-8") as stream:
        data = json.load(stream)
    with open(inventory_path, encoding="utf-8") as stream:
        inventory = json.load(stream)
    graph = build_graph(data, inventory)
    normalize.write_atomic(output_path, graph)
    return graph
