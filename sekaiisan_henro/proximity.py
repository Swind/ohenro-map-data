"""Phase 2C conservative proximity connections for 88sekaiisan.

Consumes the Phase 2B exact graph (``build-graph`` output) plus the Phase 2A
topology inventory (and the normalized document for snapshot validation) and
writes a NEW deterministic graph that adds ONLY conservative, unambiguous
proximity joins as explicit synthetic connectors.

Source geometry is never rewritten:

* the exact source ``nodes`` and ``edges`` lists and the source length
  accounting are preserved byte/value-identically;
* every applied join is a distinct ``synthetic_joins`` record;
* a proximity T-junction (endpoint near another line's interior) becomes a
  dedicated ``synthetic_nodes`` entry that carries an ``attached`` edge
  reference; the underlying source edge is NOT split.

Rules (per reference/sekaiisan-henro-graph-plan.md §2.4/2.5/2.6/2.7):

* ``<=5m`` endpoint clusters are joined ONLY when BOTH endpoints have exactly
  one ``<=5m`` endpoint candidate (degree 1) AND the complete-link cluster has
  exactly two endpoints. Any candidate edge whose graph degree is >1 on either
  side (e.g. an A-B, B-C chain with A-C >5m) or which sits in a >2-endpoint
  complete-link cluster is rejected as competing/ambiguous, never joined.
* ``<=5m`` endpoint-to-line-interior joins happen ONLY when the endpoint has
  exactly one ``<=5m`` projection candidate AND the target line is the target
  of exactly one endpoint. Any competing candidate rejects the join (reported).
* ``5-20m`` candidates and all ambiguous interior/interior crossings are
  reported but never joined.

This module never mutates source geometry and writes byte-deterministically
(temp -> flush -> fsync -> replace). On failure the prior output is untouched.
"""

from __future__ import annotations

import json

from shapely.geometry import LineString, Point

from sekaiisan_henro import graph, normalize
from sekaiisan_henro.projection import project_point

# Proximity tolerances (metres), documented in the graph plan.
_PROX5 = 5.0
_PROX20 = 20.0
# Metric epsilon for treating a projection as coincident with an existing node.
_ATTACH_EPS = 1e-6
# Max metric distance from an inventory projection point to its chosen source
# edge (the inventory projects onto the full line; float round-off should be far
# below this).
_TARGET_EDGE_TOL = 1.0
# Metric "same point" epsilon (used for reusing a coincident synthetic node).
_EPS = 1e-9


def _canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash16(text: str) -> str:
    return graph._hash16(text)


def _quantize(value: float) -> float:
    return graph._quantize(value)


# --- validation --------------------------------------------------------------


def validate_exact_graph(data: dict) -> None:
    """Validate the exact (Phase 2B) graph schema; raise ValueError on issues."""
    if not isinstance(data, dict):
        raise ValueError("graph input must be a JSON object")
    if data.get("kind") != "exact_route_graph":
        raise ValueError("graph input must be kind=exact_route_graph, got %r"
                         % data.get("kind"))
    for key in ("dataset_id", "snapshot_sha256", "projection", "limitation",
                "note", "route_sources", "nodes", "edges", "components",
                "accounting"):
        if key not in data:
            raise ValueError("exact graph missing required key: %s" % key)
    for section in ("nodes", "edges", "components"):
        if not isinstance(data[section], list):
            raise ValueError("exact graph %s must be a list" % section)


# --- helpers -----------------------------------------------------------------


def _endpoint_node_index(nodes: list[dict]) -> dict:
    """Map (route_id, position) -> node id for start/end source refs."""
    index: dict = {}
    for node in nodes:
        for ref in node["source_refs"]:
            if ref["position"] in ("start", "end"):
                index[(ref["route_id"], ref["position"])] = node["id"]
    return index


def _complete_link_clusters(units: list, adjacency: dict) -> list[list]:
    """Complete-link clusters (diameter <=5m) over endpoint units.

    Greedy over deterministic sorted order: a new unit joins the current cluster
    only if it is within the tolerance of EVERY current member (no error-chain).
    Returns clusters sorted by their first (deterministic) member.
    """
    remaining = set(units)
    clusters = []
    for seed in units:  # units already sorted
        if seed not in remaining:
            continue
        cluster = {seed}
        remaining.discard(seed)
        changed = True
        while changed:
            changed = False
            for candidate in sorted(remaining):
                if all(candidate in adjacency[member] for member in cluster):
                    cluster.add(candidate)
                    remaining.discard(candidate)
                    changed = True
        clusters.append(sorted(cluster))
    return clusters


def _target_edge(edges: list[dict], target_route: str, metric_point) -> dict:
    """Return the source edge of ``target_route`` containing ``metric_point``."""
    p = Point(metric_point)
    best = None
    for edge in edges:
        if edge["provenance"]["route_id"] != target_route:
            continue
        line = LineString([project_point(*coord) for coord in edge["coordinates"]])
        distance = line.distance(p)
        if best is None or distance < best[0]:
            best = (distance, edge)
    if best is None:
        raise ValueError("no source edge for target route %s" % target_route)
    distance, edge = best
    if distance > _TARGET_EDGE_TOL:
        raise ValueError(
            "projection point not on target route %s edge (distance %.3f m)"
            % (target_route, distance))
    return edge


def _coincident_node(node_by_id: dict, edges: list[dict], target_route: str,
                     metric_point) -> str | None:
    """Return an existing node id coincident with ``metric_point`` on the route,
    or None when the point falls strictly on the target line interior."""
    p = Point(metric_point)
    best = None
    for edge in edges:
        if edge["provenance"]["route_id"] != target_route:
            continue
        for node_id in (edge["from"], edge["to"]):
            node = node_by_id[node_id]
            node_metric = project_point(node["lon"], node["lat"])
            distance = p.distance(Point(node_metric))
            if best is None or distance < best[0]:
                best = (distance, node_id)
    if best is not None and best[0] < _ATTACH_EPS:
        return best[1]
    return None


def _recompute_components(all_node_ids: list, source_edges: list,
                          synthetic_joins: list, synthetic_nodes: list,
                          edge_by_id: dict) -> list[dict]:
    """Union-find components over source edges + synthetic connectors.

    Synthetic T nodes are additionally unioned with the two endpoints of their
    ``attached`` source edge, representing that the node lies ON that edge
    without modifying the source edge list. Component ``edges`` lists include
    source edge ids and synthetic join ids (attachments are implicit).
    """
    parent = {node_id: node_id for node_id in all_node_ids}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for edge in source_edges:
        union(edge["from"], edge["to"])
    for join in synthetic_joins:
        union(join["from"], join["to"])
    for node in synthetic_nodes:
        attached = node.get("attached")
        if attached:
            edge = edge_by_id[attached["edge_id"]]
            union(node["id"], edge["from"])
            union(node["id"], edge["to"])

    members: dict = {}
    for node_id in all_node_ids:
        members.setdefault(find(node_id), []).append(node_id)
    edge_members: dict = {}
    for edge in source_edges:
        edge_members.setdefault(find(edge["from"]), []).append(edge["id"])
    for join in synthetic_joins:
        edge_members.setdefault(find(join["from"]), []).append(join["id"])

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


def _report_key(record: dict):
    from_node = record.get("from_node") or record.get("route_a") or ""
    to_node = record.get("to_node") or record.get("route_b") or ""
    return (record.get("kind", ""), record.get("distance_m", 0.0),
            str(from_node), str(to_node),
            json.dumps(record.get("coordinates", []), sort_keys=True))


# --- orchestration -----------------------------------------------------------


def build_proximity_graph(exact: dict, inventory: dict, normalized: dict) -> dict:
    """Build the deterministic proximity graph document from the exact graph.

    ``exact`` is the Phase 2B graph, ``inventory`` its Phase 2A topology
    inventory, and ``normalized`` the shared normalized document (same snapshot).
    Raises ValueError on schema/snapshot mismatch or unexpected input.
    """
    validate_exact_graph(exact)
    graph.validate_inventory(inventory)
    graph.validate_normalized(normalized)

    if not (exact["dataset_id"] == inventory["dataset_id"] == normalized["dataset_id"]):
        raise ValueError("dataset mismatch between graph/inventory/normalized")
    if not (exact["snapshot_sha256"] == inventory["snapshot_sha256"]
            == normalized["snapshot_sha256"]):
        raise ValueError("snapshot mismatch between graph/inventory/normalized")

    # Deep, independent copies of the exact source geometry (never rewritten).
    nodes = [dict(n) for n in exact["nodes"]]
    edges = [dict(e) for e in exact["edges"]]
    node_by_id = {n["id"]: n for n in nodes}
    edge_by_id = {e["id"]: e for e in edges}
    endpoint_node = _endpoint_node_index(nodes)

    synthetic_nodes: list[dict] = []
    synthetic_joins: list[dict] = []
    report: list[dict] = []
    counts = {
        "endpoint_clusters_applied": 0,
        "endpoint_clusters_rejected_ambiguous": 0,
        "endpoint_to_line_applied": 0,
        "endpoint_to_line_rejected_competing": 0,
        "gaps_5_20m_reported": 0,
        "ambiguous_crossings_total": 0,
        "ambiguous_crossings_connected": 0,
    }
    synthetic_node_by_id: dict = {}

    # ---- 1. <=5m endpoint clusters (complete-link + degree-1, unambiguous) ---
    # A join is applied ONLY when BOTH endpoints have exactly one <=5m endpoint
    # candidate (degree 1). Any candidate edge whose graph degree >1 on either
    # side (e.g. an A-B, B-C chain with A-C >5m) is rejected as
    # competing/ambiguous. Complete-link clustering is still applied so the
    # diameter <=5m protection is explicit and reporting is deterministic.
    ep_pairs = inventory["proximity_candidates"]["endpoint_pairs"]["<=5m"]
    units = sorted({
        (r["route_a"], r["endpoint_a"]) for r in ep_pairs
    } | {(r["route_b"], r["endpoint_b"]) for r in ep_pairs})
    adjacency = {unit: set() for unit in units}
    pair_distance: dict = {}
    for record in ep_pairs:
        u = (record["route_a"], record["endpoint_a"])
        v = (record["route_b"], record["endpoint_b"])
        adjacency[u].add(v)
        adjacency[v].add(u)
        key = tuple(sorted((u, v)))
        distance = record["distance_m"]
        if key not in pair_distance or distance < pair_distance[key]:
            pair_distance[key] = distance

    candidate_edges = sorted(pair_distance)
    degree = {unit: len(adjacency[unit]) for unit in units}
    cluster_of: dict = {}
    for cluster in _complete_link_clusters(units, adjacency):
        for unit in cluster:
            cluster_of[unit] = cluster

    for u, v in candidate_edges:
        node_u = endpoint_node.get(u)
        node_v = endpoint_node.get(v)
        if node_u is None or node_v is None:
            raise ValueError("endpoint node not found for candidate %r" % ((u, v),))
        distance = pair_distance[(u, v)]
        # Complete-link protection (only a 2-endpoint cluster is joinable) AND
        # uniqueness (neither endpoint may have a competing <=5m candidate).
        unique = len(cluster_of[u]) == 2 and degree[u] == 1 and degree[v] == 1
        if node_u == node_v:
            # Endpoints already share a node (effectively exact): nothing to add.
            continue
        if unique:
            ordered = sorted((node_u, node_v))
            join_id = "SHJ_" + _hash16(_canon({
                "kind": "endpoint_cluster", "from": ordered[0], "to": ordered[1],
                "distance_m": distance,
            }))
            synthetic_joins.append({
                "id": join_id,
                "kind": "endpoint_cluster",
                "from": ordered[0],
                "to": ordered[1],
                "distance_m": distance,
                "coordinates": [node_by_id[ordered[0]]["coordinates"],
                                node_by_id[ordered[1]]["coordinates"]],
            })
            counts["endpoint_clusters_applied"] += 1
            report.append({
                "kind": "endpoint_cluster", "applied": True,
                "distance_m": distance,
                "from_node": ordered[0], "to_node": ordered[1],
                "route_a": u[0], "route_b": v[0],
                "coordinates": [node_by_id[ordered[0]]["coordinates"],
                                node_by_id[ordered[1]]["coordinates"]],
                "reason": "applied: unambiguous <=5m endpoint cluster",
            })
        else:
            # A participant has >1 <=5m candidate (competing) or the complete-link
            # cluster has >2 endpoints (ambiguous): reject, never join.
            counts["endpoint_clusters_rejected_ambiguous"] += 1
            report.append({
                "kind": "endpoint_cluster", "applied": False,
                "distance_m": distance,
                "from_node": node_u, "to_node": node_v,
                "route_a": u[0], "route_b": v[0],
                "reason": "rejected: ambiguous/competing endpoint cluster "
                          "(participant has >1 <=5m candidate or cluster has >2 "
                          "endpoints)",
            })

    # ---- 2. <=5m endpoint-to-line-interior (unique, no competition) ---------
    etl_cands = inventory["proximity_candidates"]["endpoint_to_line"]["<=5m"]
    by_endpoint: dict = {}
    by_target: dict = {}
    for candidate in etl_cands:
        by_endpoint.setdefault((candidate["endpoint_route"], candidate["endpoint"]), []).append(candidate)
        by_target.setdefault(candidate["target_route"], []).append(candidate)

    for candidate in etl_cands:
        endpoint_key = (candidate["endpoint_route"], candidate["endpoint"])
        unique_endpoint = len(by_endpoint[endpoint_key]) == 1
        unique_target = len(by_target[candidate["target_route"]]) == 1
        from_node = endpoint_node.get(endpoint_key)
        if from_node is None:
            raise ValueError("endpoint node not found for %r" % (endpoint_key,))
        if unique_endpoint and unique_target:
            metric_proj = project_point(*candidate["projected_coordinates"])
            target_edge = _target_edge(edges, candidate["target_route"], metric_proj)
            coincident = _coincident_node(node_by_id, edges,
                                          candidate["target_route"], metric_proj)
            if coincident is not None:
                to_node = coincident
            else:
                lon, lat = candidate["projected_coordinates"]
                snid = "SHS_" + _hash16(_canon({
                    "kind": "synthetic_t",
                    "coord": [_quantize(lon), _quantize(lat)],
                    "route": candidate["target_route"],
                    "edge": target_edge["id"],
                }))
                existing = synthetic_node_by_id.get(snid)
                if existing is not None:
                    to_node = existing
                else:
                    synthetic_node = {
                        "id": snid,
                        "coordinates": [lon, lat],
                        "lon": lon,
                        "lat": lat,
                        "kinds": ["synthetic_t"],
                        "source_refs": [],
                        "attached": {
                            "route_id": candidate["target_route"],
                            "edge_id": target_edge["id"],
                        },
                    }
                    synthetic_nodes.append(synthetic_node)
                    synthetic_node_by_id[snid] = snid
                    to_node = snid
            ordered = sorted((from_node, to_node))
            join_id = "SHJ_" + _hash16(_canon({
                "kind": "endpoint_to_line", "from": ordered[0], "to": ordered[1],
                "distance_m": candidate["distance_m"],
                "target_route": candidate["target_route"],
                "target_edge": target_edge["id"],
            }))
            synthetic_joins.append({
                "id": join_id,
                "kind": "endpoint_to_line",
                "from": ordered[0],
                "to": ordered[1],
                "distance_m": candidate["distance_m"],
                "endpoint_route": candidate["endpoint_route"],
                "target_route": candidate["target_route"],
                "projected_coordinates": candidate["projected_coordinates"],
                "target_edge": target_edge["id"],
            })
            counts["endpoint_to_line_applied"] += 1
            report.append({
                "kind": "endpoint_to_line", "applied": True,
                "distance_m": candidate["distance_m"],
                "from_node": from_node, "to_node": to_node,
                "route_a": candidate["endpoint_route"],
                "route_b": candidate["target_route"],
                "coordinates": candidate["projected_coordinates"],
                "reason": "applied: unique endpoint-to-line <=5m candidate",
            })
        else:
            counts["endpoint_to_line_rejected_competing"] += 1
            report.append({
                "kind": "endpoint_to_line", "applied": False,
                "distance_m": candidate["distance_m"],
                "from_node": from_node,
                "route_a": candidate["endpoint_route"],
                "route_b": candidate["target_route"],
                "coordinates": candidate["projected_coordinates"],
                "reason": "rejected: competing candidate (endpoint targets "
                          "multiple lines or line targeted by multiple "
                          "endpoints)",
            })

    # ---- 3. 5-20m gaps: reported only ---------------------------------------
    for record in inventory["proximity_candidates"]["endpoint_pairs"]["5-20m"]:
        counts["gaps_5_20m_reported"] += 1
        report.append({
            "kind": "endpoint_pair_gap", "applied": False,
            "distance_m": record["distance_m"],
            "route_a": record["route_a"], "route_b": record["route_b"],
            "coordinates": [record["coordinates_a"], record["coordinates_b"]],
            "reason": "not joined: 5-20m endpoint gap",
        })
    for record in inventory["proximity_candidates"]["endpoint_to_line"]["5-20m"]:
        counts["gaps_5_20m_reported"] += 1
        report.append({
            "kind": "endpoint_to_line_gap", "applied": False,
            "distance_m": record["distance_m"],
            "route_a": record["endpoint_route"], "route_b": record["target_route"],
            "coordinates": record["projected_coordinates"],
            "reason": "not joined: 5-20m endpoint-to-line gap",
        })

    # ---- 4. ambiguous crossings: reported, never joined ---------------------
    ambiguous = inventory["intersections"]["ambiguous_crossings"]
    counts["ambiguous_crossings_total"] = len(ambiguous)
    for record in ambiguous:
        report.append({
            "kind": "ambiguous_crossing", "applied": False, "distance_m": 0.0,
            "route_a": record["route_a"], "route_b": record["route_b"],
            "coordinates": record["coordinates"],
            "reason": "not joined: ambiguous interior/interior crossing",
        })

    # ---- 5. recompute components over source edges + synthetic connectors ---
    synthetic_nodes = sorted(synthetic_nodes, key=lambda n: n["id"])
    synthetic_joins = sorted(synthetic_joins, key=lambda j: j["id"])
    report.sort(key=_report_key)

    all_node_ids = [n["id"] for n in nodes] + [n["id"] for n in synthetic_nodes]
    components_after = _recompute_components(
        all_node_ids, edges, synthetic_joins, synthetic_nodes, edge_by_id)
    components_before = exact["components"]

    isolated_before = sum(1 for c in components_before if c["edge_count"] == 0)
    isolated_after = sum(1 for c in components_after if c["edge_count"] == 0)
    largest_before = max(components_before,
                         key=lambda c: (c["node_count"], c["id"]))
    largest_after = max(components_after,
                        key=lambda c: (c["node_count"], c["id"]))

    return {
        "schema_version": 2,
        "kind": "proximity_route_graph",
        "dataset_id": exact["dataset_id"],
        "snapshot_sha256": exact["snapshot_sha256"],
        "projection": dict(exact["projection"]),
        "limitation": exact["limitation"],
        "note": "Phase 2C graph = Phase 2B exact graph plus ONLY conservative, "
                "unambiguous proximity joins. Every join is an explicit "
                "synthetic connector (synthetic_joins); T-junction points are "
                "dedicated synthetic_nodes with an 'attached' source edge "
                "reference. Source nodes/edges and source length accounting are "
                "preserved byte/value-identically and never rewritten. "
                "5-20m gaps, competing candidates, ambiguous clusters and "
                "ambiguous crossings are reported but never joined.",
        "base_graph_kind": "exact_route_graph",
        "route_sources": dict(exact["route_sources"]),
        "nodes": nodes,
        "synthetic_nodes": synthetic_nodes,
        "edges": edges,
        "synthetic_joins": synthetic_joins,
        "components": components_after,
        "components_before": components_before,
        "proximity_report": report,
        "accounting": {
            "source_routes": exact["accounting"]["source_routes"],
            "source_linestrings": exact["accounting"]["source_linestrings"],
            "source_points": exact["accounting"]["source_points"],
            "nodes": len(nodes),
            "synthetic_nodes": len(synthetic_nodes),
            "edges": len(edges),
            "synthetic_joins": len(synthetic_joins),
            "components_before": len(components_before),
            "components_after": len(components_after),
            "isolated_components_before": isolated_before,
            "isolated_components_after": isolated_after,
            "largest_component_before_nodes": largest_before["node_count"],
            "largest_component_before_edges": largest_before["edge_count"],
            "largest_component_after_nodes": largest_after["node_count"],
            "largest_component_after_edges": largest_after["edge_count"],
            # Source length accounting preserved byte/value-identically.
            "lengths": dict(exact["accounting"]["lengths"]),
            "proximity": counts,
            "note": "proximity_connections_applied = "
                    "endpoint_clusters_applied + endpoint_to_line_applied",
        },
    }


def run_proximity(graph_path: str, inventory_path: str, input_path: str,
                  output_path: str) -> dict:
    """Load exact graph + inventory + normalized, build the proximity graph,
    and write it atomically. On failure the prior output is untouched."""
    with open(graph_path, encoding="utf-8") as stream:
        exact = json.load(stream)
    with open(inventory_path, encoding="utf-8") as stream:
        inventory = json.load(stream)
    with open(input_path, encoding="utf-8") as stream:
        normalized = json.load(stream)
    result = build_proximity_graph(exact, inventory, normalized)
    normalize.write_atomic(output_path, result)
    return result