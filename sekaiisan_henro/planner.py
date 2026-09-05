"""Compact browser-routing graph export for the 88sekaiisan effective graph.

Consumes the Phase 3 ``anchored_route_graph`` (``build-anchors`` output) and
reduces it to exactly what the map-preview client-side planner needs: node
coordinates plus undirected weighted edges with full geometry. Source ``edges``
and provenance stay out; routing runs only over ``traversal_edges`` (weight =
``length_m``) + ``synthetic_joins`` (weight = ``distance_m``).

The interactive day-planning itself runs in the browser (map-preview/src/
planner.ts) over this exported graph; this module only builds that graph.
Byte-deterministic; written atomically via the shared ``normalize.write_atomic``.
"""

from __future__ import annotations

import json

from sekaiisan_henro import normalize, sections


def build_plan_graph(graph: dict) -> dict:
    """Compact browser-routing graph for the map-preview client planner.

    Exactly the routing topology the interactive planner uses, reduced to what
    a browser Dijkstra needs: node coordinates plus undirected weighted edges
    with full geometry. Source ``edges`` and provenance stay out; the node set
    is exactly the endpoints referenced by ``traversal_edges`` and
    ``synthetic_joins``. Byte-deterministic; written atomically by the caller.
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
    node_ids = sorted({
        nid for edge in traversal for nid in (edge["from"], edge["to"])
    } | {nid for join in joins for nid in (join["from"], join["to"])})
    nodes = [{"id": nid, "lon": node_coords[nid][0], "lat": node_coords[nid][1]}
             for nid in node_ids]
    return {
        "schema_version": 1,
        "kind": "plan_graph",
        "dataset_id": graph["dataset_id"],
        "snapshot_sha256": graph["snapshot_sha256"],
        "projection": dict(graph["projection"]),
        "limitation": graph["limitation"],
        "note": "compact browser-routing graph: nodes + traversal_edges + "
                "synthetic_joins only, for the map-preview client-side planner.",
        "nodes": nodes,
        "traversal_edges": traversal,
        "synthetic_joins": joins,
    }


def run_export_plan_graph(input_path: str, output_path: str) -> dict:
    with open(input_path, encoding="utf-8") as stream:
        graph = json.load(stream)
    result = build_plan_graph(graph)
    normalize.write_atomic(output_path, result)
    return result


if __name__ == "__main__":
    raise SystemExit("use: python3 -m sekaiisan_henro export-plan-graph --help")
