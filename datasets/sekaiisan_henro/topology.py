"""Phase 2A deterministic READ-ONLY topology inventory.

Diagnostic geometry analysis of the normalized route data. This module NEVER
mutates normalized geometry, builds graph nodes/edges, snaps/moves/splits
geometry, infers temple anchors/sections, or applies overrides. It produces a
byte-deterministic inventory of exact connections, proximity candidates,
intersections, and diagnostic endpoint-only connected-component counts.

All metric work uses Shapely 2.x ``STRtree`` for spatial candidate generation
(no O(n^2) brute force over all lines/endpoints); a small O(k^2) pass within
candidate clusters is acceptable. Reported metric distances are rounded to a
fixed precision, while geometry operations use full precision.
"""

from __future__ import annotations

from shapely.geometry import LineString, Point
from shapely.strtree import STRtree

from datasets.sekaiisan_henro import normalize
from datasets.sekaiisan_henro.projection import (
    PROJECTION_METADATA,
    limitation_note,
    project_point,
    unproject_point,
)

# Metric "same point / effectively at endpoint" epsilon (metres).
_EXACT_EPS = 1e-9
_AT_ENDPOINT_EPS = 1e-6
# Fixed decimals for reported metric distances.
_PRECISION = 6
# Diagnostic endpoint-only component tolerances (metres).
_COMPONENT_TOLERANCES = (0.0, 1.0, 5.0, 10.0)
_END_KINDS = ("start", "end")


def _round6(value: float) -> float:
    return round(value, _PRECISION)


def _coord_tuple(coord) -> tuple:
    return (coord[0], coord[1])


def validate_normalized(data) -> bool:
    """Validate the expected normalized schema; raise ValueError on issues."""
    if not isinstance(data, dict):
        raise ValueError("normalized input must be a JSON object")
    for key in ("schema_version", "dataset_id", "snapshot_sha256", "routes", "accounting"):
        if key not in data:
            raise ValueError("normalized input missing required key: %s" % key)
    routes = data["routes"]
    if not isinstance(routes, list):
        raise ValueError("normalized 'routes' must be a list")
    for idx, route in enumerate(routes):
        if not isinstance(route, dict) or "id" not in route:
            raise ValueError("route record %d missing 'id'" % idx)
        geometry = route.get("geometry")
        if not isinstance(geometry, dict) or geometry.get("type") != "LineString":
            raise ValueError("route %s geometry must be a LineString" % route["id"])
        coords = geometry.get("coordinates")
        if not isinstance(coords, list) or len(coords) < 2:
            raise ValueError("route %s LineString must have >=2 coordinates" % route["id"])
        for coord in coords:
            if not (isinstance(coord, (list, tuple)) and len(coord) >= 2):
                raise ValueError("route %s has a malformed coordinate" % route["id"])
    return True


def _load_routes(data: dict) -> list[dict]:
    """Project each source LineString; count/drop consecutive duplicates.

    Raises ValueError if a route is degenerate (fewer than 2 points after
    removing consecutive duplicates). Returns analysis-only records; the raw
    normalized data is never mutated.
    """
    entries = []
    for idx, route in enumerate(data["routes"]):
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
                % route["id"]
            )
        metric = [project_point(*coord) for coord in cleaned]
        line = LineString(metric)
        entries.append({
            "index": idx,
            "id": route["id"],
            "prefecture": route.get("prefecture"),
            "source_file": route.get("source_file"),
            "source_fid": route.get("source_fid"),
            "part": route.get("part"),
            "source_identity": route.get("source_identity"),
            "source_identity_kind": route.get("source_identity_kind"),
            "wgs84": cleaned,            # cleaned canonical WGS84 (lon, lat) tuples
            "metric": metric,
            "duplicate_count": duplicate_count,
            "source_point_count": len(coords),
            "line": line,
            "start": metric[0],
            "end": metric[-1],
        })
    return entries


def _coord_map(entries: list[dict]) -> dict:
    """Map canonical WGS84 coordinate tuple -> [(route_index, vertex_index), ...].

    Used for exact equality matching (never proximity).
    """
    mapping: dict = {}
    for entry in entries:
        for vertex_index, coord in enumerate(entry["wgs84"]):
            mapping.setdefault(coord, []).append((entry["index"], vertex_index))
    return mapping


def _vertex_kind(entry: dict, vertex_index: int) -> str:
    count = len(entry["wgs84"])
    if vertex_index == 0:
        return "start"
    if vertex_index == count - 1:
        return "end"
    return "interior"


def _exact_connections(entries: list[dict], mapping: dict) -> dict:
    """Exact shared endpoints, endpoint-to-vertex (T) and shared internal vertices.

    Uses canonical WGS84 coordinate-tuple equality only.
    """
    shared_endpoints = []
    endpoint_to_vertex = []
    shared_internal = []
    seen = set()
    for coord, members in mapping.items():
        by_route: dict = {}
        for route_index, vertex_index in members:
            by_route.setdefault(route_index, []).append(vertex_index)
        route_indices = sorted(by_route)
        for a in range(len(route_indices)):
            for b in range(a + 1, len(route_indices)):
                left, right = route_indices[a], route_indices[b]
                e_left, e_right = entries[left], entries[right]
                pair = (left, right)
                for vi in by_route[left]:
                    for vj in by_route[right]:
                        ki = _vertex_kind(e_left, vi)
                        kj = _vertex_kind(e_right, vj)
                        if ki in _END_KINDS and kj in _END_KINDS:
                            bucket = shared_endpoints
                            bucket_key = ("shared_endpoint", pair, coord)
                        elif ki == "interior" and kj == "interior":
                            bucket = shared_internal
                            bucket_key = ("shared_internal", pair, coord)
                        else:
                            bucket = endpoint_to_vertex
                            bucket_key = ("endpoint_to_vertex", pair, coord)
                        if bucket_key in seen:
                            continue
                        seen.add(bucket_key)
                        bucket.append({
                            "coordinates": [coord[0], coord[1]],
                            "route_a": e_left["id"],
                            "route_b": e_right["id"],
                            "vertex_a": ki,
                            "vertex_b": kj,
                        })
    sort_key = lambda r: (tuple(r["coordinates"]), r["route_a"], r["route_b"])
    shared_endpoints.sort(key=sort_key)
    endpoint_to_vertex.sort(key=sort_key)
    shared_internal.sort(key=sort_key)
    return {
        "summary": {
            "shared_endpoints": len(shared_endpoints),
            "endpoint_to_vertex": len(endpoint_to_vertex),
            "shared_internal_vertices": len(shared_internal),
        },
        "shared_endpoints": shared_endpoints,
        "endpoint_to_vertex": endpoint_to_vertex,
        "shared_internal_vertices": shared_internal,
    }


def _endpoint_pairs(entries: list[dict]) -> tuple[list, list, dict]:
    """Endpoint-to-endpoint proximity candidates in (0,5]m and (5,20]m.

    Uses an STRtree over all endpoints with a 20 m buffer query. Excludes pairs
    from the same route record. Effectively-exact matches (projected distance
    <= eps) are NOT emitted as proximity detail candidates, but ARE kept in the
    returned edge-distance map with their TRUE tiny distance (> 0) for the
    endpoint-only component diagnostic, so they connect at tolerances >= that
    distance but never at 0 m (which uses only exactly-coincident endpoints).
    Deterministically sorted and deduplicated. The edge-distance map is full
    precision (rounded values are only for output).
    """
    endpoint_records = []
    for entry in entries:
        endpoint_records.append({
            "route": entry["index"], "kind": "start",
            "point": Point(entry["start"]), "wgs84": tuple(entry["wgs84"][0]),
        })
        endpoint_records.append({
            "route": entry["index"], "kind": "end",
            "point": Point(entry["end"]), "wgs84": tuple(entry["wgs84"][-1]),
        })
    tree = STRtree([record["point"] for record in endpoint_records])
    found = {}
    edge_distances = {}
    for index, record in enumerate(endpoint_records):
        for other in tree.query(record["point"].buffer(20.0)):
            if other == index:
                continue
            other_record = endpoint_records[other]
            if other_record["route"] == record["route"]:
                continue  # same route record excluded
            distance = record["point"].distance(other_record["point"])
            if distance > 20.0:
                continue
            left_idx, right_idx = record["route"], other_record["route"]
            pair = (min(left_idx, right_idx), max(left_idx, right_idx))
            if distance <= _EXACT_EPS:
                # Effectively identical endpoints (tiny nonzero projected
                # separation): keep the edge for component diagnostics with its
                # TRUE tiny distance (NOT clamped to 0.0), so it only connects
                # at tolerances >= its distance (1/5/10 m), never at 0 m.
                # Exclude from proximity detail candidates (they are effectively
                # exact connections, handled by canonical mapping).
                edge_distances[pair] = min(edge_distances.get(pair, float("inf")), distance)
                continue
            left_id = entries[record["route"]]["id"]
            right_id = entries[other_record["route"]]["id"]
            key = tuple(sorted([
                (left_id, record["kind"], record["wgs84"]),
                (right_id, other_record["kind"], other_record["wgs84"]),
            ]))
            if key not in found or distance < found[key][0]:
                found[key] = (distance, record, other_record)
    bucket5, bucket20 = [], []
    for distance, a, b in found.values():
        left_idx, right_idx = a["route"], b["route"]
        pair = (min(left_idx, right_idx), max(left_idx, right_idx))
        edge_distances[pair] = min(edge_distances.get(pair, float("inf")), distance)
        a_id = entries[a["route"]]["id"]
        b_id = entries[b["route"]]["id"]
        if (a_id, a["kind"]) <= (b_id, b["kind"]):
            route_a, kind_a, coord_a = a_id, a["kind"], list(a["wgs84"])
            route_b, kind_b, coord_b = b_id, b["kind"], list(b["wgs84"])
        else:
            route_a, kind_a, coord_a = b_id, b["kind"], list(b["wgs84"])
            route_b, kind_b, coord_b = a_id, a["kind"], list(a["wgs84"])
        record = {
            "route_a": route_a, "endpoint_a": kind_a, "coordinates_a": coord_a,
            "route_b": route_b, "endpoint_b": kind_b, "coordinates_b": coord_b,
            "distance_m": _round6(distance),
        }
        (bucket5 if distance <= 5.0 else bucket20).append(record)
    key = lambda r: (r["route_a"], r["endpoint_a"], r["route_b"], r["endpoint_b"],
                     tuple(r["coordinates_a"]), tuple(r["coordinates_b"]))
    bucket5.sort(key=key)
    bucket20.sort(key=key)
    return bucket5, bucket20, edge_distances


def _endpoint_to_line(entries: list[dict], line_tree) -> tuple[list, list]:
    """Endpoint-to-other-line-interior nearest projections in (0,5]m and (5,20]m.

    Excludes the endpoint's own line and projections that land effectively at a
    target line endpoint (those belong in the endpoint-pair buckets).
    """
    bucket5, bucket20 = [], []
    for entry in entries:
        for kind, metric in (("start", entry["start"]), ("end", entry["end"])):
            point = Point(metric)
            for target_index in line_tree.query(point.buffer(20.0)):
                if target_index == entry["index"]:
                    continue
                target = entries[target_index]
                nearest = target["line"].interpolate(target["line"].project(point))
                distance = point.distance(nearest)
                if distance <= _EXACT_EPS or distance > 20.0:
                    continue
                # Projection effectively at a target endpoint -> endpoint pair.
                if (nearest.distance(Point(target["start"])) < _AT_ENDPOINT_EPS or
                        nearest.distance(Point(target["end"])) < _AT_ENDPOINT_EPS):
                    continue
                lon, lat = unproject_point(nearest.x, nearest.y)
                record = {
                    "endpoint_route": entry["id"],
                    "endpoint": kind,
                    "endpoint_coordinates": list(
                        entry["wgs84"][0] if kind == "start" else entry["wgs84"][-1]),
                    "target_route": target["id"],
                    "distance_m": _round6(distance),
                    "projected_coordinates": [lon, lat],
                }
                (bucket5 if distance <= 5.0 else bucket20).append(record)
    key = lambda r: (r["endpoint_route"], r["endpoint"], r["target_route"],
                     tuple(r["projected_coordinates"]))
    bucket5.sort(key=key)
    bucket20.sort(key=key)
    return bucket5, bucket20


def _shared_between(entries: list[dict], mapping: dict) -> dict:
    """Map (route_index_a, route_index_b) -> set of shared canonical WGS84 coords."""
    shared = {}
    for coord, members in mapping.items():
        by_route: dict = {}
        for route_index, _ in members:
            by_route.setdefault(route_index, None)
        route_indices = sorted(by_route)
        for a in range(len(route_indices)):
            for b in range(a + 1, len(route_indices)):
                shared.setdefault((route_indices[a], route_indices[b]), set()).add(coord)
    return shared


def _flatten_intersection(geom, linear, points) -> None:
    """Recursively split an intersection result into linear and point parts.

    Handles GeometryCollection (mixed) so no intersection component is silently
    ignored. Only zero-length degenerate parts are dropped; everything else is
    preserved for classification.
    """
    kind = geom.geom_type
    if kind == "LineString":
        if geom.length > 0:
            linear.append(geom)
    elif kind in ("MultiLineString", "GeometryCollection", "MultiPoint"):
        for part in geom.geoms:
            _flatten_intersection(part, linear, points)
    elif kind == "Point":
        points.append(geom)


def _intersections(entries: list[dict], line_tree, shared_between: dict) -> dict:
    """Line-pair intersection inventory (each unordered pair once).

    Every positive-length linear component records a single ``linear_overlaps``
    entry for the route pair with summed length; point components continue
    through shared / ambiguous / touch classification.
    """
    duplicates = []
    overlaps = []
    ambiguous_crossings = []
    shared_vertex_intersections = []
    endpoint_touches = []
    for index, entry in enumerate(entries):
        for other_index in line_tree.query(entry["line"]):
            if other_index <= index:
                continue
            other = entries[other_index]
            inter = entry["line"].intersection(other["line"])
            if inter.is_empty:
                continue
            # Topologically equal source LineStrings (direction- and
            # extra-collinear-vertex-insensitive).
            if entry["line"].equals(other["line"]):
                duplicates.append({
                    "route_a": entry["id"], "route_b": other["id"],
                    "length_m": _round6(inter.length),
                })
                continue
            linear_parts = []
            point_parts = []
            _flatten_intersection(inter, linear_parts, point_parts)
            if linear_parts:
                total_length = sum(part.length for part in linear_parts)
                overlaps.append({
                    "route_a": entry["id"], "route_b": other["id"],
                    "length_m": _round6(total_length),
                })
            for point in point_parts:
                at_end_i = min(point.distance(Point(entry["start"])),
                               point.distance(Point(entry["end"]))) < _AT_ENDPOINT_EPS
                at_end_j = min(point.distance(Point(other["start"])),
                               point.distance(Point(other["end"]))) < _AT_ENDPOINT_EPS
                shared = _is_shared_vertex(point, index, other_index, shared_between)
                interior_i = not at_end_i
                interior_j = not at_end_j
                lon, lat = unproject_point(point.x, point.y)
                record = {"route_a": entry["id"], "route_b": other["id"],
                          "coordinates": [lon, lat]}
                if interior_i and interior_j:
                    if shared:
                        shared_vertex_intersections.append(record)
                    else:
                        ambiguous_crossings.append(record)
                elif shared:
                    shared_vertex_intersections.append(record)
                else:
                    endpoint_touches.append(record)
    by_coords = lambda r: (r["route_a"], r["route_b"], tuple(r["coordinates"]))
    by_len = lambda r: (r["route_a"], r["route_b"], r["length_m"])
    duplicates.sort(key=by_len)
    overlaps.sort(key=by_len)
    ambiguous_crossings.sort(key=by_coords)
    shared_vertex_intersections.sort(key=by_coords)
    endpoint_touches.sort(key=by_coords)
    return {
        "summary": {
            "duplicate_geometries": len(duplicates),
            "linear_overlaps": len(overlaps),
            "ambiguous_crossings": len(ambiguous_crossings),
            "shared_vertex_intersections": len(shared_vertex_intersections),
            "endpoint_touches": len(endpoint_touches),
        },
        "duplicate_geometries": duplicates,
        "linear_overlaps": overlaps,
        "ambiguous_crossings": ambiguous_crossings,
        "shared_vertex_intersections": shared_vertex_intersections,
        "endpoint_touches": endpoint_touches,
    }


def _is_shared_vertex(point, left: int, right: int, shared_between: dict) -> bool:
    """True if the metric point coincides with a source-shared vertex of both."""
    for coord in shared_between.get((left, right), ()) or shared_between.get((right, left), ()):
        mx, my = project_point(*coord)
        if (mx - point.x) ** 2 + (my - point.y) ** 2 < _EXACT_EPS ** 2:
            return True
    return False


def _endpoint_edge_distances(entries: list[dict], mapping: dict,
                             endpoint_pair_distances: dict) -> dict:
    """Min endpoint-to-endpoint distance per unordered route pair (for diagnostics).

    Includes exact shared endpoints (distance 0) and full-precision endpoint
    proximity pairs.
    """
    distances = dict(endpoint_pair_distances)
    # Exact shared endpoints (both vertices are endpoints) -> distance 0.
    for coord, members in mapping.items():
        by_route: dict = {}
        for route_index, vertex_index in members:
            by_route.setdefault(route_index, []).append(vertex_index)
        route_indices = sorted(by_route)
        for a in range(len(route_indices)):
            for b in range(a + 1, len(route_indices)):
                left, right = route_indices[a], route_indices[b]
                kinds_left = {_vertex_kind(entries[left], v) for v in by_route[left]}
                kinds_right = {_vertex_kind(entries[right], v) for v in by_route[right]}
                if kinds_left & set(_END_KINDS) and kinds_right & set(_END_KINDS):
                    # An exact shared endpoint (distance 0) always overrides any
                    # nonzero endpoint distance between the same route records.
                    distances[(left, right)] = 0.0
    return distances


def _components(entries: list[dict], edge_distances: dict, tolerance: float) -> dict:
    """Endpoint-only connected components at ``tolerance`` via union-find.

    SINGLE-LINK diagnostic only; route records are joined ONLY by endpoint
    pairs (exact shared endpoints + endpoint-to-endpoint proximity) within the
    tolerance. This is never reused as graph snapping.
    """
    parent = list(range(len(entries)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for (left, right), distance in edge_distances.items():
        if distance <= tolerance:
            union(left, right)

    roots = {}
    for index in range(len(entries)):
        roots.setdefault(find(index), []).append(index)
    sizes = [len(component) for component in roots.values()]
    component_count = len(roots)
    largest = max(sizes) if sizes else 0
    isolated = sum(1 for size in sizes if size == 1)
    return {
        "component_count": component_count,
        "largest_component_lines": largest,
        "isolated_lines": isolated,
    }


def build_inventory(data: dict) -> dict:
    """Compute the full deterministic topology inventory from normalized data."""
    validate_normalized(data)
    entries = _load_routes(data)
    mapping = _coord_map(entries)
    line_tree = STRtree([entry["line"] for entry in entries])

    exact = _exact_connections(entries, mapping)
    endpoint5, endpoint20, endpoint_pair_distances = _endpoint_pairs(entries)
    interior5, interior20 = _endpoint_to_line(entries, line_tree)
    shared_between = _shared_between(entries, mapping)
    intersections = _intersections(entries, line_tree, shared_between)

    edge_distances = _endpoint_edge_distances(entries, mapping, endpoint_pair_distances)
    components = {}
    for tolerance in _COMPONENT_TOLERANCES:
        label = "%dm" % int(tolerance)
        components[label] = _components(entries, edge_distances, tolerance)

    source_accounting = data["accounting"]
    total_source_points = sum(e["source_point_count"] for e in entries)
    linestrings_ok = source_accounting.get("linestrings") == len(entries)
    points_ok = source_accounting.get("points") == total_source_points
    if not linestrings_ok or not points_ok:
        raise ValueError(
            "source accounting mismatch: normalized linestrings=%r (analyzed=%d), "
            "points=%r (analyzed=%d)" % (
                source_accounting.get("linestrings"), len(entries),
                source_accounting.get("points"), total_source_points))
    validated = {
        "route_records_match": True,
        "source_points_match": True,
        "validated": True,
    }
    analysis_accounting = {
        "route_records": len(entries),
        "source_points": total_source_points,
        "consecutive_duplicate_points": sum(e["duplicate_count"] for e in entries),
        "cleaned_points": sum(len(e["wgs84"]) for e in entries),
        "degenerate_lines": 0,
        "projected_length_m": _round6(sum(e["line"].length for e in entries)),
        "source_accounting_validated": validated,
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
        route_sources[entry["id"]] = info

    return {
        "schema_version": 1,
        "kind": "topology_inventory",
        "dataset_id": data["dataset_id"],
        "snapshot_sha256": data["snapshot_sha256"],
        "projection": dict(PROJECTION_METADATA),
        "limitation": limitation_note(),
        "note": "read-only diagnostic geometry inventory; no graph, snapping, "
                "temple anchors, or overrides are applied. Diagnostic records "
                "refer to routes by ID; provenance lives once in 'route_sources'.",
        "source_accounting": source_accounting,
        "route_sources": route_sources,
        "analysis_accounting": analysis_accounting,
        "exact_connections": exact,
        "proximity_candidates": {
            "endpoint_pairs": {"<=5m": endpoint5, "5-20m": endpoint20},
            "endpoint_to_line": {"<=5m": interior5, "5-20m": interior20},
            "summary": {
                "endpoint_pairs_<=5m": len(endpoint5),
                "endpoint_pairs_5-20m": len(endpoint20),
                "endpoint_to_line_<=5m": len(interior5),
                "endpoint_to_line_5-20m": len(interior20),
            },
        },
        "intersections": intersections,
        "diagnostic_components": {
            "note": "SINGLE-LINK endpoint-only connected components: route "
                    "records are joined ONLY by endpoint-to-endpoint pairs "
                    "(exact shared endpoints or endpoint proximity within "
                    "tolerance). T-junctions (endpoint-to-interior vertex), "
                    "endpoint-to-line projections, interior shared vertices, "
                    "and crossings are DELIBERATELY EXCLUDED, so this is not "
                    "full connectivity. Diagnostic only; never reused as graph "
                    "snapping.",
            "tolerances": components,
        },
    }


def run_inventory(input_path: str, output_path: str) -> dict:
    """Load normalized JSON, compute the inventory, and write it atomically.

    On failure the prior output (if any) is left untouched.
    """
    import json

    with open(input_path, encoding="utf-8") as stream:
        data = json.load(stream)
    inventory = build_inventory(data)
    normalize.write_atomic(output_path, inventory)
    return inventory