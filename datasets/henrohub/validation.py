"""Source and consumer geometry/accounting checks for Henro Hub."""

from collections import Counter
import math

ROLES = {"canonical_shikoku88", "unique_alternative", "transition_connector", "continuity_fallback"}
ROUTED_ROLES = {"canonical_shikoku88", "unique_alternative"}


def coordinate(value, dimensions=(2, 3)):
    if (not isinstance(value, list) or len(value) not in dimensions or
            not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in value) or
            not (131 < value[0] < 136 and 31.5 < value[1] < 35.5)):
        raise ValueError("Invalid Shikoku coordinate")


def line_parts(geometry, dimensions=(3,)):
    kind = geometry.get("type")
    if kind not in ("LineString", "MultiLineString"):
        raise ValueError("Expected route line geometry")
    parts = [geometry.get("coordinates")] if kind == "LineString" else geometry.get("coordinates")
    if not isinstance(parts, list) or not parts:
        raise ValueError("Empty route geometry")
    for part in parts:
        if not isinstance(part, list) or len(part) < 2:
            raise ValueError("Degenerate route part")
        for point in part:
            coordinate(point, dimensions)
        if not any(point[:2] != part[0][:2] for point in part[1:]):
            raise ValueError("Zero-length route part")
    return parts


def validate_routes(data, *, planner=False, expected_count=None):
    if data.get("type") != "FeatureCollection" or not isinstance(data.get("features"), list) or not data["features"]:
        raise ValueError("Expected nonempty route FeatureCollection")
    ids, roles, points, parts_count = set(), Counter(), 0, 0
    for feature in data["features"]:
        if feature.get("type") != "Feature":
            raise ValueError("Invalid route feature")
        props = feature["properties"]
        rid = (props.get("route_feature_id") or feature.get("id")) if planner else props.get("route_id")
        if not isinstance(rid, str) or not rid or rid in ids:
            raise ValueError("Missing or duplicate route ID")
        ids.add(rid)
        role = props.get("route_role")
        if role not in ROLES:
            raise ValueError(f"Unknown route role: {role}")
        roles[role] += 1
        route_sets = props.get("route_set_ids" if planner else "route_sets")
        if not isinstance(route_sets, list) or not all(isinstance(v, str) and v for v in route_sets):
            raise ValueError(f"Invalid route sets: {rid}")
        route_class = props.get("effective_route_class" if planner else "route_class")
        if not isinstance(route_class, str) or not route_class:
            raise ValueError(f"Missing route class: {rid}")
        if not planner and (props.get("kind") != "line" or feature.get("id") != rid or not props.get("name")):
            raise ValueError(f"Invalid consumer properties: {rid}")
        for field in ("length_m", "ascent_m", "descent_m", "elevation_min_m", "elevation_max_m"):
            value = props.get(field)
            if value is not None and (not isinstance(value, (int, float)) or isinstance(value, bool) or
                                      not math.isfinite(value) or (field in ("length_m", "ascent_m", "descent_m") and value < 0)):
                raise ValueError(f"Invalid {field}: {rid}")
        parts = line_parts(feature["geometry"])
        parts_count += len(parts)
        points += sum(len(part) for part in parts)
    if expected_count is not None and len(ids) != expected_count:
        raise ValueError("Planner count differs from release manifest")
    if not any(roles[role] for role in ROUTED_ROLES):
        raise ValueError("No walkable main/alternative routes")
    return {"feature_count": len(ids), "part_count": parts_count, "point_count": points, "by_role": dict(sorted(roles.items()))}


def validate_graph(graph, routes):
    if graph.get("schema_version") != 2 or graph.get("kind") != "plan_graph" or graph.get("dataset_id") != "henrohub":
        raise ValueError("Unexpected plan graph schema")
    nodes = {node["id"]: node for node in graph["nodes"]}
    if not nodes or len(nodes) != len(graph["nodes"]):
        raise ValueError("Empty/duplicate graph nodes")
    for node in nodes.values():
        coordinate([node["lon"], node["lat"]], (2,))
    edges, joins, geometry = graph["traversal_edges"], graph["synthetic_joins"], graph["edge_geometry"]
    ids = [edge["id"] for edge in edges + joins]
    if not edges or len(ids) != len(set(ids)) or set(ids) != set(geometry):
        raise ValueError("Graph geometry/topology ID mismatch")
    parent = {node: node for node in nodes}

    def root(node):
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    referenced = set()
    for edge in edges + joins:
        a, b = edge["from"], edge["to"]
        length = edge.get("length_m", edge.get("distance_m"))
        if (a not in nodes or b not in nodes or ("distance_m" in edge and a == b) or
                not isinstance(length, (int, float)) or isinstance(length, bool) or
                not math.isfinite(length) or length < 0 or ("length_m" in edge and length == 0)):
            raise ValueError("Invalid graph edge endpoint/weight")
        coords = geometry[edge["id"]]
        line_parts({"type": "LineString", "coordinates": coords}, (2, 3))
        referenced.update((a, b))
        parent[root(a)] = root(b)
    if referenced != set(nodes):
        raise ValueError("Unreferenced graph node")
    components = Counter(root(node) for node in nodes)
    expected = {"segments": sum(len(line_parts(f["geometry"])) for f in routes["features"]
                                if f["properties"]["route_role"] in ROUTED_ROLES),
                "nodes": len(nodes), "edges": len(edges), "synthetic_joins": len(joins),
                "geometry_points": sum(len(part) for part in geometry.values()),
                "components": len(components), "largest_component_nodes": max(components.values())}
    if graph["accounting"] != expected:
        raise ValueError("Graph accounting mismatch")
    # Traversal geometry must retain elevation; synthetic joins may be 2D.
    for edge in edges:
        if any(len(point) != 3 for point in geometry[edge["id"]]):
            raise ValueError("Graph lost source elevation")
    return expected
