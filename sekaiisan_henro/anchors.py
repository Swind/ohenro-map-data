"""Phase 3 temple anchors + derived traversal segmentation for 88sekaiisan.

Consumes the Phase 2C proximity graph (``apply-proximity`` output) plus the
normalized document (for the 88 temple points and snapshot validation) and
writes a NEW deterministic ``anchored_route_graph``:

* the exact source ``nodes``, ``edges``, ``route_sources``, synthetic nodes /
  joins and the source length accounting are preserved byte/value-identically;
* every one of the 88 temples is projected (in the metric projection) onto its
  nearest SOURCE edge and classified by confidence (near <=50m, offset <=150m,
  review_required >150m, or review_required on a tied nearest result);
* distinct ``temple_anchors`` records and ``anchor_nodes`` entries are added --
  the original temple point is never moved and the temple-to-route offset line
  is never added as an edge;
* a derived ``traversal_edges`` list is produced WITHOUT changing the source
  edges: each source edge is split at every usable anchor node AND at every
  attached Phase 2C synthetic T node into positive-length traversal edges (with
  a one-to-one traversal edge for unsplit edges), so Phase 4 can route only
  over this complete traversal edge list.

Rules / invariants (per reference/sekaiisan-henro-graph-plan.md §Phase 4):

* Only source ``edges`` are nearest-route candidates; synthetic connector
  geometry is never a candidate.
* A unique nearest edge gets a chosen projection/measure and a stable anchor
  node ID.
* A TIED nearest result (within a fixed documented metric epsilon) is
  ``review_required`` unless it is a genuine **shared-node tie**: when the
  nearest projection onto EVERY candidate edge coincides (within a documented
  metric epsilon) and lands on the SAME existing source graph node that is
  incident to every candidate edge, the tie is resolved automatically as a
  single unambiguous anchor location. It reuses that existing source node (no
  new SHA_ node, no chosen edge, no edge split, no offset-as-edge) and its
  confidence / usability derive solely from distance. A tied result whose
  projections differ (or land on distinct source nodes, or in the interiors)
  stays ``review_required`` and never creates a usable anchor.
* Unique nearest >150m may retain its projection and anchor node for audit but
  is marked unusable and is never inserted into the traversal topology.
* Review-required anchors are never inserted into traversal topology.
* Multiple attachments at effectively the same measure reuse one traversal node
  or fail clearly when the node IDs conflict; zero-length traversal edges are
  never created.
* Component count over the effective traversal graph + synthetic joins must
  equal the Phase 2C component count (anchoring only subdivides edges).

This module never mutates source geometry and writes byte-deterministically
(temp -> flush -> fsync -> replace). On failure the prior output is untouched.
"""

from __future__ import annotations

import json

from shapely.geometry import LineString, Point

from sekaiisan_henro import graph, normalize
from sekaiisan_henro.projection import project_point, unproject_point

# Confidence thresholds (metres), per graph plan §Phase 4.1.
_NEAR_M = 50.0
_OFFSET_M = 150.0
# Metric epsilon for treating two edges as TIED nearest (a temple equidistant
# within this tiny distance is ambiguous, never silently chosen).
_CANDIDATE_EPS = 1e-6
# Metric "same measure" epsilon for reusing a traversal node (graph._EPS).
_EPS = 1e-9
# Metric epsilon (metres) within which ALL candidate-edge nearest projections
# must coincide for a tied nearest result to be resolved automatically as a
# shared-node tie. A true shared-node tie projects exactly onto the common
# source-node endpoint of every candidate edge, so the projections coincide to
# float round-off; this epsilon only guards that round-off and never permits an
# interior-vs-endpoint or distinct-interior projection to be merged.
_NODE_TIE_EPS = 1e-6


def _canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash16(text: str) -> str:
    return graph._hash16(text)


def _quantize(value: float) -> float:
    return graph._quantize(value)


def _point(pair) -> Point:
    return Point(project_point(pair[0], pair[1]))


def _unproject(point) -> tuple[float, float]:
    return unproject_point(point.x, point.y)


def _edge_measure(edge: dict, metric_point) -> tuple[float, Point, float]:
    """Return (measure_m, projected metric Point, line length_m)."""
    line = LineString([project_point(*c) for c in edge["coordinates"]])
    measure = line.project(metric_point)
    return measure, line.interpolate(measure), line.length


def _landing_node(edge: dict, measure: float, edge_length: float) -> str | None:
    """Return the existing source endpoint node the projection lands on.

    ``None`` means the projection falls in the edge interior (not an endpoint),
    so it cannot be part of a shared-node tie (a shared-node tie must project
    exactly onto the common endpoint node of every candidate edge).
    """
    if abs(measure - 0.0) < _EPS:
        return edge["from"]
    if abs(measure - edge_length) < _EPS:
        return edge["to"]
    return None


# --- validation --------------------------------------------------------------


def validate_proximity_graph(data: dict) -> None:
    """Validate the Phase 2C proximity graph schema; raise ValueError on issues."""
    if not isinstance(data, dict):
        raise ValueError("graph input must be a JSON object")
    if data.get("kind") != "proximity_route_graph":
        raise ValueError("graph input must be kind=proximity_route_graph, got %r"
                         % data.get("kind"))
    for key in ("dataset_id", "snapshot_sha256", "projection", "limitation",
                "note", "route_sources", "nodes", "synthetic_nodes", "edges",
                "synthetic_joins", "components", "accounting"):
        if key not in data:
            raise ValueError("proximity graph missing required key: %s" % key)
    for section in ("nodes", "synthetic_nodes", "edges", "synthetic_joins",
                    "components"):
        if not isinstance(data[section], list):
            raise ValueError("proximity graph %s must be a list" % section)


def _validate_temples(normalized: dict) -> None:
    """Validate the normalized 88-temple invariant (numbers 1..88, unique)."""
    temples = normalized.get("temples")
    if not isinstance(temples, list):
        raise ValueError("normalized 'temples' must be a list")
    seen = set()
    for idx, temple in enumerate(temples):
        if not isinstance(temple, dict) or "number" not in temple:
            raise ValueError("temple record %d missing 'number'" % idx)
        number = temple["number"]
        if not isinstance(number, int) or not (1 <= number <= 88):
            raise ValueError("temple number %r out of range 1..88" % (number,))
        if number in seen:
            raise ValueError("duplicate temple number %d" % number)
        seen.add(number)
        geometry = temple.get("geometry")
        if not (isinstance(geometry, dict)
                and geometry.get("type") == "Point"
                and isinstance(geometry.get("coordinates"), (list, tuple))
                and len(geometry["coordinates"]) >= 2):
            raise ValueError("temple %d geometry must be a Point" % number)
    if seen != set(range(1, 89)):
        missing = sorted(set(range(1, 89)) - seen)
        raise ValueError("temple numbers missing: %s" % ", ".join(map(str, missing)))


# --- traversal segmentation --------------------------------------------------


def _split_edge(edge: dict, cuts: list[dict]) -> list[dict]:
    """Split ``edge`` into traversal sub-edges at the given cut positions.

    ``cuts`` is a list of ``{"measure", "node_id", "wgs84"}`` already sorted by
    measure and de-duplicated (no zero-length gaps). Each traversal edge keeps
    every original intermediate source vertex, interpolates only the exact cut
    point via the inverse projection, references ``source_edge_id``, preserves
    the source provenance, and records the source measure start/end.
    """
    coords = [tuple(c) for c in edge["coordinates"]]
    metric = [project_point(*c) for c in coords]
    cum = [0.0]
    for prev, cur in zip(metric, metric[1:]):
        cum.append(cum[-1] + ((cur[0] - prev[0]) ** 2 + (cur[1] - prev[1]) ** 2) ** 0.5)
    length = cum[-1]

    segments = []
    for i in range(len(cuts) - 1):
        a, b = cuts[i], cuts[i + 1]
        if b["measure"] - a["measure"] < _EPS:
            continue  # zero-length protection (should not happen after dedup)
        seg_coords = [list(a["wgs84"])]
        for k in range(len(metric)):
            if a["measure"] < cum[k] < b["measure"]:
                seg_coords.append(list(coords[k]))
        seg_coords.append(list(b["wgs84"]))
        cleaned = []
        for coord in seg_coords:
            if cleaned and cleaned[-1] == coord:
                continue
            cleaned.append(coord)
        if len(cleaned) < 2:
            raise ValueError("edge %s produced a degenerate traversal edge"
                             % edge["id"])
        seg_metric = [project_point(*c) for c in cleaned]
        seg_len = sum(
            ((seg_metric[j][0] - seg_metric[j - 1][0]) ** 2
             + (seg_metric[j][1] - seg_metric[j - 1][1]) ** 2) ** 0.5
            for j in range(1, len(seg_metric))
        )
        ordered = sorted((a["node_id"], b["node_id"]))
        te_id = "STE_" + _hash16(_canon({
            "from": ordered[0], "to": ordered[1],
            "source_edge_id": edge["id"],
            "source_start_measure": a["measure"],
            "source_end_measure": b["measure"],
        }))
        segments.append({
            "id": te_id,
            "from": a["node_id"],
            "to": b["node_id"],
            "source_edge_id": edge["id"],
            "coordinates": [list(c) for c in cleaned],
            "length_m": seg_len,
            "source_start_measure": a["measure"],
            "source_end_measure": b["measure"],
            "provenance": dict(edge["provenance"]),
        })
    if not segments:
        raise ValueError("edge %s produced no traversal edges" % edge["id"])
    return segments


def _traversal_components(traversal_edges: list[dict],
                          synthetic_joins: list[dict]) -> list[dict]:
    """Union-find components over the effective traversal graph + joins.

    Traversal edges already connect source nodes, usable anchor nodes and
    attached synthetic T nodes; synthetic joins add the endpoint-to-T
    connectivity. Component ids follow the SHC_ scheme for consistency.
    """
    node_ids = set()
    for te in traversal_edges:
        node_ids.add(te["from"])
        node_ids.add(te["to"])
    for join in synthetic_joins:
        node_ids.add(join["from"])
        node_ids.add(join["to"])
    parent = {n: n for n in node_ids}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for te in traversal_edges:
        union(te["from"], te["to"])
    for join in synthetic_joins:
        union(join["from"], join["to"])

    members: dict = {}
    for nid in node_ids:
        members.setdefault(find(nid), []).append(nid)
    edge_members: dict = {}
    for te in traversal_edges:
        edge_members.setdefault(find(te["from"]), []).append(te["id"])
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


# --- orchestration -----------------------------------------------------------


def build_anchors_graph(prox: dict, normalized: dict) -> dict:
    """Build the deterministic anchored route graph.

    ``prox`` is the Phase 2C proximity graph and ``normalized`` the shared
    normalized document (same snapshot). Raises ValueError on schema/snapshot
    mismatch, 88-temple invariant failure, conflicting attachments, component
    count change, or length reconstruction failure.
    """
    validate_proximity_graph(prox)
    graph.validate_normalized(normalized)
    _validate_temples(normalized)

    if prox["dataset_id"] != normalized["dataset_id"]:
        raise ValueError("dataset mismatch between graph and normalized")
    if prox["snapshot_sha256"] != normalized["snapshot_sha256"]:
        raise ValueError("snapshot mismatch between graph and normalized")

    # Deep, independent copies of the source geometry (never rewritten).
    nodes = [dict(n) for n in prox["nodes"]]
    synthetic_nodes = [dict(n) for n in prox["synthetic_nodes"]]
    edges = [dict(e) for e in prox["edges"]]
    synthetic_joins = [dict(j) for j in prox["synthetic_joins"]]
    edge_by_id = {e["id"]: e for e in edges}
    node_coord_by_id = {n["id"]: n["coordinates"] for n in nodes}

    temples = sorted(normalized["temples"], key=lambda t: t["number"])

    # ---- 1. project every temple onto its nearest SOURCE edge ---------------
    temple_anchors: list[dict] = []
    anchor_nodes: list[dict] = []
    attachments: dict = {}  # edge_id -> list of {"measure","node_id","wgs84"}
    for temple in temples:
        number = temple["number"]
        tlon, tlat = temple["geometry"]["coordinates"]
        p = _point((tlon, tlat))
        distances = {eid: LineString(
            [project_point(*c) for c in edge["coordinates"]]).distance(p)
            for eid, edge in edge_by_id.items()}
        best_dist = min(distances.values())
        candidates = sorted(
            eid for eid, dist in distances.items()
            if abs(dist - best_dist) <= _CANDIDATE_EPS)
        unique = len(candidates) == 1
        distance_m = best_dist

        if distance_m <= _NEAR_M:
            distance_confidence = "near"
        elif distance_m <= _OFFSET_M:
            distance_confidence = "offset"
        else:
            distance_confidence = "review_required"

        record = {
            "temple_number": number,
            "temple_id": temple["id"],
            "name_jp": temple.get("name_jp"),
            # Original temple point, preserved verbatim (never moved).
            "coordinates": [tlon, tlat],
            "distance_m": distance_m,
            "candidate_edge_ids": candidates,
        }
        if unique:
            chosen_eid = candidates[0]
            edge = edge_by_id[chosen_eid]
            measure, proj_metric, edge_length = _edge_measure(edge, p)
            proj_wgs84 = _unproject(proj_metric)
            # A projection landing exactly on a source edge endpoint is
            # represented by that existing endpoint node: we never fabricate a
            # detached anchor node (Phase 4 must start at a traversal node).
            anchor_node_id = _landing_node(edge, measure, edge_length)
            if anchor_node_id is None:
                anchor_id = "SHA_" + _hash16(_canon({
                    "temple_number": number,
                    "edge": chosen_eid,
                    "coord": [_quantize(proj_wgs84[0]), _quantize(proj_wgs84[1])],
                }))
                anchor_nodes.append({
                    "id": anchor_id,
                    "temple_number": number,
                    "coordinates": [proj_wgs84[0], proj_wgs84[1]],
                    "lon": proj_wgs84[0],
                    "lat": proj_wgs84[1],
                    "kinds": ["temple_anchor"],
                    "source_refs": [],
                    "attached": {
                        "route_id": edge["provenance"]["route_id"],
                        "edge_id": chosen_eid,
                    },
                    "measure_m": measure,
                    "distance_m": distance_m,
                    "usable_for_routing": distance_confidence in ("near", "offset"),
                })
                anchor_node_id = anchor_id
                # Only interior (newly created) usable anchors split the edge;
                # an endpoint anchor is already an existing traversal junction.
                if distance_confidence in ("near", "offset"):
                    attachments.setdefault(chosen_eid, []).append({
                        "measure": measure, "node_id": anchor_id,
                        "wgs84": [proj_wgs84[0], proj_wgs84[1]],
                    })
            record.update({
                "confidence": distance_confidence,
                "status": distance_confidence,
                "usable_for_routing": distance_confidence in ("near", "offset"),
                "chosen_edge_id": chosen_eid,
                "measure_m": measure,
                "projected_coordinates": [proj_wgs84[0], proj_wgs84[1]],
                "anchor_node_id": anchor_node_id,
            })
        else:
            # TIED nearest: attempt automatic resolution as a shared-node tie.
            # Project onto EVERY candidate edge and resolve only when all
            # projections coincide (within a documented metric epsilon) AND land
            # on the SAME existing source graph node incident to every candidate
            # edge. We never resolve merely because the candidate edges happen to
            # share some node while the nearest projections are elsewhere.
            projections = []
            landing_nodes = []
            for eid in candidates:
                edge = edge_by_id[eid]
                measure, proj_metric, edge_length = _edge_measure(edge, p)
                projections.append(proj_metric)
                landing_nodes.append(_landing_node(edge, measure, edge_length))
            shared_node = None
            if (all(nid is not None for nid in landing_nodes)
                    and len(set(landing_nodes)) == 1
                    and all(proj.distance(projections[0]) < _NODE_TIE_EPS
                            for proj in projections)):
                shared_node = landing_nodes[0]

            if shared_node is not None:
                # A single unambiguous anchor location at an existing source
                # node endpoint: reuse it. No chosen edge (there is no single
                # closest edge), no measure (it is per-edge, 0 on some and the
                # full length on others), no new SHA_ node, no edge split, and
                # never an offset-as-edge. Confidence/usable come only from
                # distance thresholds; a >150m shared-node tie keeps the audit
                # node/projection but stays unusable.
                node_coord = node_coord_by_id[shared_node]
                record.update({
                    "confidence": distance_confidence,
                    "status": distance_confidence,
                    "usable_for_routing": distance_confidence in ("near", "offset"),
                    "anchor_node_id": shared_node,
                    "projected_coordinates": list(node_coord),
                    "resolution": "shared_node_tie",
                    "resolved_edge_ids": candidates,
                })
            else:
                # Tied projections differ (or land on distinct source nodes /
                # interiors): retain review_required with no node/projection
                # selection. No usable anchor is ever created.
                record.update({
                    "confidence": "review_required",
                    "status": "review_required",
                    "usable_for_routing": False,
                })
        temple_anchors.append(record)

    # ---- 2. include attached Phase 2C synthetic T nodes as split points -----
    for sn in synthetic_nodes:
        attached = sn.get("attached")
        if not attached or attached.get("edge_id") not in edge_by_id:
            raise ValueError("synthetic node %s has no valid attached edge"
                             % sn["id"])
        eid = attached["edge_id"]
        measure, _, _ = _edge_measure(edge_by_id[eid],
                                      Point(project_point(sn["lon"], sn["lat"])))
        attachments.setdefault(eid, []).append({
            "measure": measure, "node_id": sn["id"],
            "wgs84": [sn["lon"], sn["lat"]],
        })

    # ---- 3. split every source edge into traversal edges --------------------
    traversal_edges: list[dict] = []
    for edge in sorted(edges, key=lambda e: e["id"]):
        coords = [tuple(c) for c in edge["coordinates"]]
        metric = [project_point(*c) for c in coords]
        cum = [0.0]
        for prev, cur in zip(metric, metric[1:]):
            cum.append(cum[-1] + ((cur[0] - prev[0]) ** 2
                                  + (cur[1] - prev[1]) ** 2) ** 0.5)
        length = cum[-1]
        cuts = [
            {"measure": 0.0, "node_id": edge["from"], "wgs84": list(coords[0])},
            {"measure": length, "node_id": edge["to"], "wgs84": list(coords[-1])},
        ]
        for att in attachments.get(edge["id"], []):
            # An attachment that lands exactly on an edge endpoint reuses the
            # endpoint node (the anchor is at an existing junction, so it never
            # creates a separate traversal node or a zero-length edge).
            if abs(att["measure"] - 0.0) < _EPS:
                nid, wgs84 = edge["from"], list(coords[0])
            elif abs(att["measure"] - length) < _EPS:
                nid, wgs84 = edge["to"], list(coords[-1])
            else:
                nid, wgs84 = att["node_id"], list(att["wgs84"])
            cuts.append({"measure": att["measure"], "node_id": nid,
                         "wgs84": wgs84})
        cuts.sort(key=lambda c: (c["measure"], c["node_id"]))
        deduped = []
        for cut in cuts:
            if deduped and abs(deduped[-1]["measure"] - cut["measure"]) < _EPS:
                prev = deduped[-1]
                if prev["node_id"] != cut["node_id"]:
                    raise ValueError(
                        "edge %s conflicting attachments at measure %.6fm: "
                        "nodes %s and %s" % (edge["id"], cut["measure"],
                                             prev["node_id"], cut["node_id"]))
                continue  # same node at effectively the same measure: reuse it
            deduped.append(cut)
        traversal_edges.extend(_split_edge(edge, deduped))

    traversal_edges.sort(key=lambda te: te["id"])
    traversal_node_ids = sorted({
        nid for te in traversal_edges for nid in (te["from"], te["to"])
    })
    anchor_nodes.sort(key=lambda n: n["id"])

    # ---- 4. recompute components over traversal graph + synthetic joins -----
    components_before = [dict(c) for c in prox["components"]]
    components_after = _traversal_components(traversal_edges, synthetic_joins)
    if len(components_after) != len(components_before):
        raise ValueError(
            "anchoring changed component count: before=%d after=%d "
            "(anchoring must only subdivide edges)"
            % (len(components_before), len(components_after)))
    isolated_after = sum(1 for c in components_after if c["edge_count"] == 0)
    largest_after = max(components_after,
                        key=lambda c: (c["node_count"], c["id"]))

    # ---- 5. per-edge / global source length reconstruction validation -------
    per_edge: dict = {}
    global_traversal = 0.0
    for te in traversal_edges:
        per_edge.setdefault(te["source_edge_id"], []).append(te["length_m"])
        global_traversal += te["length_m"]
    global_source = sum(e["length_m"] for e in edges)
    max_abs = 0.0
    max_rel = 0.0
    per_edge_report = {}
    for eid, lens in per_edge.items():
        recon = sum(lens)
        orig = edge_by_id[eid]["length_m"]
        err = abs(orig - recon)
        rel = err / orig if orig else 0.0
        if err > graph._LENGTH_TOL_ABS and err > graph._LENGTH_TOL_REL * orig:
            raise ValueError(
                "edge %s traversal length reconstruction error %.3e m exceeds "
                "tolerance" % (eid, err))
        max_abs = max(max_abs, err)
        max_rel = max(max_rel, rel)
        per_edge_report[eid] = {
            "original_m": orig, "reconstructed_m": recon, "error_m": err,
        }

    return {
        "schema_version": 1,
        "kind": "anchored_route_graph",
        "dataset_id": prox["dataset_id"],
        "snapshot_sha256": prox["snapshot_sha256"],
        "projection": dict(prox["projection"]),
        "limitation": prox["limitation"],
        "note": "Phase 3 anchored graph = Phase 2C proximity graph plus 88 "
                "temple anchors (projection onto nearest source edge with "
                "confidence near/offset/review_required) and a derived "
                "traversal edge list that subdivides source edges at usable "
                "anchors and attached synthetic T nodes. A tied nearest result "
                "whose projections all coincide on the SAME existing source "
                "node endpoint incident to every candidate edge is resolved as "
                "a shared-node tie (resolution=shared_node_tie) reusing that "
                "node with no chosen edge / no new node / no edge split; other "
                "ties stay review_required. Source nodes/edges/synthetic "
                "connectors and the source length accounting are preserved "
                "byte/value-identically; the original temple point is never "
                "moved and the temple-to-route offset line is never an edge. "
                "Review-required anchors are never inserted into traversal "
                "topology.",
        "base_graph_kind": "proximity_route_graph",
        "route_sources": dict(prox["route_sources"]),
        "nodes": nodes,
        "synthetic_nodes": synthetic_nodes,
        "edges": edges,
        "synthetic_joins": synthetic_joins,
        "temple_anchors": temple_anchors,
        "anchor_nodes": anchor_nodes,
        "traversal_nodes": traversal_node_ids,
        "traversal_edges": traversal_edges,
        "components": components_after,
        "components_before": components_before,
        "accounting": {
            "source_routes": prox["accounting"]["source_routes"],
            "source_linestrings": prox["accounting"]["source_linestrings"],
            "source_points": prox["accounting"]["source_points"],
            "nodes": len(nodes),
            "synthetic_nodes": len(synthetic_nodes),
            "edges": len(edges),
            "synthetic_joins": len(synthetic_joins),
            "temple_anchors": len(temple_anchors),
            "anchor_nodes": len(anchor_nodes),
            "anchors_usable": sum(1 for t in temple_anchors
                                  if t["usable_for_routing"]),
            "anchors_review_required": sum(1 for t in temple_anchors
                                           if not t["usable_for_routing"]),
            "traversal_edges": len(traversal_edges),
            "traversal_nodes": len(traversal_node_ids),
            "components_before": len(components_before),
            "components_after": len(components_after),
            "isolated_components_after": isolated_after,
            "largest_component_after_nodes": largest_after["node_count"],
            "largest_component_after_edges": largest_after["edge_count"],
            # Source length accounting preserved byte/value-identically.
            "lengths": dict(prox["accounting"]["lengths"]),
            "traversal_lengths": {
                "global_original_m": global_source,
                "global_reconstructed_m": global_traversal,
                "max_absolute_error_m": max_abs,
                "max_relative_error": max_rel,
                "per_edge": per_edge_report,
            },
            "note": "usable anchors (near/offset) are inserted into traversal "
                    "topology; review_required anchors are excluded from "
                    "automatic section routing.",
        },
    }


def run_anchors(graph_path: str, input_path: str, output_path: str) -> dict:
    """Load proximity graph + normalized JSON, build the anchored graph, and
    write it atomically. On failure the prior output is untouched."""
    with open(graph_path, encoding="utf-8") as stream:
        prox = json.load(stream)
    with open(input_path, encoding="utf-8") as stream:
        normalized = json.load(stream)
    result = build_anchors_graph(prox, normalized)
    normalize.write_atomic(output_path, result)
    return result