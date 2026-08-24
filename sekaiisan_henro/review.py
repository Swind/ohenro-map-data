"""Deterministic QGIS review-pack / report exporter for 88sekaiisan.

Consumes the Phase 1 normalized document, the Phase 2A topology inventory, the
Phase 2C proximity graph, the Phase 3 anchored graph and the Phase 4 temple
sections (all of the SAME snapshot) and writes a byte-deterministic, read-only
review pack under ``output/sekaiisan-henro-review``:

* ``source-edges.geojson``  - every anchored source ``edges`` LineString with its
  stable source edge ID and route/provenance fields;
* ``topology.geojson``      - one feature per applied synthetic join, rejected
  <=5m candidate, 5-20m gap and ambiguous crossing;
* ``anchors.geojson``       - every temple Point plus a *review_visualization_only*
  offset LineString (never a graph edge) for each unique projected anchor;
* ``sections.geojson``      - reconstructed primary and alternative path
  LineStrings (continuity / direction / claimed-length verified), none for
  disconnected / review-required sections;
* ``review-items.json``     - the generated immutable review queue (NOT a
  decisions file): one item per topology record, per temple anchor and per
  section, with an empty ``decision: null``;
* ``report.json``           - snapshot, input accounting, output/priority counts,
  unresolved focal counts, preservation notes and the file list.

All review IDs / ordering / content are byte-deterministic; features are sorted
by review ID / stable source ID. No external network or dependency is used, and
no geometry is mutated. The review queue is generated afresh on every run
(reruns overwrite it); decisions belong in a FUTURE separate
``graph_overrides`` / ``review-decisions`` file and are never made here.

Priority policy (explicit in ``report.json``):

* **P0** - ``review_required`` anchors, ``ambiguous``/``disconnected`` (and
  ``anchor_review_required``) sections, and applied synthetic joins used by a
  primary path;
* **P1** - applied synthetic joins used only by alternatives, every rejected
  <=5m candidate, every 5-20m gap and every ambiguous crossing;
* **P2** - other accepted (near/offset) anchors, ``candidate`` sections and
  unused applied synthetic joins.

This module never mutates source geometry and writes byte-deterministically
(temp -> flush -> fsync -> replace). Every payload is fully validated and built
in memory before any write, and each file is written atomically. Because the
pack spans several files, a filesystem failure mid-loop can still leave a
mixed-version directory; this exporter makes no whole-pack transaction
guarantee (no directory transaction is engineered here).
"""

from __future__ import annotations

import json
import os
from collections import Counter

from sekaiisan_henro import graph, normalize

# Absolute metric tolerance for path length reconstruction (metres): the
# Dijkstra path weight is a sum of the very same edge weights in path order, so
# real disagreement is float-round-off far below this; anything larger is a
# genuine continuity/weighting bug and must fail rather than emit broken review
# geometry.
_LEN_EPS = 1e-6

# Category-specific allowed decisions. These are documentation-only labels that
# mirror the documented review workflow (graph_overrides / review-decisions):
# the review module never reads or applies a decision. Topology applied joins,
# reported topology records and anchors share a per-category list; section
# choices are status-specific (see _SECTION_DECISIONS).
_ALLOWED_DECISIONS = {
    "topology_applied": ("accept_as_is", "forbid_join", "needs_more_evidence"),
    "topology_reported": ("keep_disconnected", "forced_join_proposed",
                          "needs_more_evidence"),
    "anchor": ("accept_anchor", "temple_anchor_override", "remain_review_required"),
}
_SECTION_DECISIONS = {
    "candidate": ("accept_as_candidate", "topology_issue", "anchor_issue"),
    "ambiguous": ("ambiguity_unresolved", "primary_plausible",
                  "alternative_plausible", "topology_issue", "anchor_issue"),
    "disconnected": ("expected_source_gap", "topology_issue", "anchor_issue"),
    "anchor_review_required": ("remain_review_required", "anchor_issue"),
}
_SECTION_STATUSES = ("candidate", "ambiguous", "disconnected",
                     "anchor_review_required")


def _canon(obj) -> str:
    return graph._canon(obj)


def _hash16(text: str) -> str:
    return graph._hash16(text)


# --- validation (trust boundary) --------------------------------------------


def validate_inputs(normalized: dict, inventory: dict, prox: dict,
                    anchored: dict, sections: dict) -> None:
    """Validate every input document and cross-input identity; raise ValueError."""
    if not isinstance(normalized, dict):
        raise ValueError("normalized input must be a JSON object")
    for key in ("schema_version", "dataset_id", "snapshot_sha256", "routes",
                "temples", "accounting"):
        if key not in normalized:
            raise ValueError("normalized input missing required key: %s" % key)

    kind_checks = (
        (inventory, "topology_inventory", "inventory"),
        (prox, "proximity_route_graph", "proximity graph"),
        (anchored, "anchored_route_graph", "anchored graph"),
        (sections, "temple_sections", "temple sections"),
    )
    for doc, expected, label in kind_checks:
        if not isinstance(doc, dict):
            raise ValueError("%s input must be a JSON object" % label)
        if doc.get("kind") != expected:
            raise ValueError("%s must be kind=%s, got %r"
                             % (label, expected, doc.get("kind")))
        for key in ("dataset_id", "snapshot_sha256"):
            if key not in doc:
                raise ValueError("%s missing required key: %s" % (label, key))

    dataset_ids = {normalized["dataset_id"], inventory["dataset_id"],
                   prox["dataset_id"], anchored["dataset_id"],
                   sections["dataset_id"]}
    if len(dataset_ids) != 1:
        raise ValueError("dataset mismatch across inputs: %r"
                         % sorted(dataset_ids))
    snapshots = {normalized["snapshot_sha256"], inventory["snapshot_sha256"],
                 prox["snapshot_sha256"], anchored["snapshot_sha256"],
                 sections["snapshot_sha256"]}
    if len(snapshots) != 1:
        raise ValueError("snapshot mismatch across inputs: %r"
                         % sorted(snapshots))

    for section in ("nodes", "synthetic_nodes", "anchor_nodes", "edges",
                    "synthetic_joins", "temple_anchors", "traversal_edges"):
        if not isinstance(anchored.get(section), list):
            raise ValueError("anchored graph %s must be a list" % section)
    if len(anchored["temple_anchors"]) != 88:
        raise ValueError("expected exactly 88 temple anchors, got %d"
                         % len(anchored["temple_anchors"]))
    if len(sections.get("sections", [])) != 87:
        raise ValueError("expected exactly 87 temple sections, got %d"
                         % len(sections.get("sections", [])))

    # Cross-input source accounting identity: these checks substantiate the
    # report's preservation claims, not just the shared snapshot hash.
    norm_acct = normalized["accounting"]
    if not isinstance(norm_acct, dict):
        raise ValueError("normalized accounting must be an object")
    if norm_acct != inventory.get("source_accounting"):
        raise ValueError("source accounting mismatch between normalized and "
                         "inventory")

    pa = prox.get("accounting")
    if not isinstance(pa, dict):
        raise ValueError("proximity graph accounting must be an object")
    for key, norm_key in (("source_routes", "routes"),
                          ("source_linestrings", "linestrings"),
                          ("source_points", "points")):
        if pa.get(key) != norm_acct.get(norm_key):
            raise ValueError("proximity %s=%r does not match normalized %s=%r"
                             % (key, pa.get(key), norm_key,
                                norm_acct.get(norm_key)))

    # The anchored graph must preserve the proximity source payload exactly.
    for key in ("nodes", "synthetic_nodes", "edges", "synthetic_joins",
                "route_sources"):
        if not isinstance(prox.get(key), (list, dict)):
            raise ValueError("proximity graph %s must be a list/object" % key)
        if anchored.get(key) != prox.get(key):
            raise ValueError("anchored %s differs from proximity %s value-identically"
                             % (key, key))
    aa = anchored.get("accounting")
    if not isinstance(aa, dict):
        raise ValueError("anchored graph accounting must be an object")
    if aa.get("lengths") != pa.get("lengths"):
        raise ValueError("anchored source lengths differ from proximity lengths")
    if anchored.get("components_before") != prox.get("components"):
        raise ValueError("anchored components_before differs from proximity components")

    # Temple anchor numbers must be exactly 1..88, each once.
    numbers = [a.get("temple_number") for a in anchored["temple_anchors"]]
    if len(numbers) != 88 or sorted(numbers) != list(range(1, 89)):
        raise ValueError("temple anchor numbers must be exactly 1..88, each once")

    # Sections: exactly 87 unique records SEC_1_2..SEC_87_88 whose statuses
    # agree with the section accounting.
    secs = sections["sections"]
    ids = [s.get("id") for s in secs]
    if ids != ["SEC_%d_%d" % (i, i + 1) for i in range(1, 88)] or len(set(ids)) != 87:
        raise ValueError("section ids must be the unique SEC_1_2..SEC_87_88")
    statuses = [s.get("status") for s in secs]
    counts = {st: statuses.count(st) for st in _SECTION_STATUSES}
    sec_acct = sections.get("accounting") or {}
    if sec_acct.get("sections_total") != 87:
        raise ValueError("section accounting sections_total must be 87")
    if sec_acct.get("by_status") != counts:
        raise ValueError("section accounting by_status does not match records: "
                         "%r != %r" % (sec_acct.get("by_status"), counts))


def _assert_unique_ids(files: dict, items_by_file: dict) -> None:
    """Fail on any duplicate feature id within a file or review id across items."""
    for name, features in (("source-edges.geojson", files["source-edges.geojson"]["features"]),
                           ("topology.geojson", files["topology.geojson"]["features"]),
                           ("anchors.geojson", files["anchors.geojson"]["features"]),
                           ("sections.geojson", files["sections.geojson"]["features"])):
        ids = [f["id"] for f in features]
        dup = next((i for i, c in Counter(ids).items() if c > 1), None)
        if dup is not None:
            raise ValueError("duplicate feature id %r in %s" % (dup, name))
    for filename, items in items_by_file:
        ids = [i["review_id"] for i in items]
        dup = next((i for i, c in Counter(ids).items() if c > 1), None)
        if dup is not None:
            raise ValueError("duplicate review id %r in %s"
                             % (dup, filename))


def _node_coordinate_index(anchored: dict) -> dict:
    """Map node id -> [lon, lat] over source + synthetic + anchor nodes."""
    index: dict = {}
    for section in ("nodes", "synthetic_nodes", "anchor_nodes"):
        for node in anchored.get(section, ()):
            nid = node.get("id")
            coords = node.get("coordinates")
            if not nid or not isinstance(coords, (list, tuple)) or len(coords) < 2:
                raise ValueError("node record missing id/coordinates")
            index[nid] = [coords[0], coords[1]]
    return index


def _edge_lookup(anchored: dict, node_coords: dict) -> dict:
    """Map edge id -> {coordinates, from, to, weight} for reconstruction.

    Traversal edges carry their own WGS84 coordinates; synthetic joins use their
    endpoint node coordinates (endpoint-cluster joins already store coordinates;
    endpoint-to-line joins connect an endpoint node to their synthetic T node).
    """
    lookup: dict = {}
    for te in anchored["traversal_edges"]:
        lookup[te["id"]] = {
            "coordinates": te["coordinates"],
            "from": te["from"], "to": te["to"],
            "weight": te["length_m"],
        }
    for sj in anchored["synthetic_joins"]:
        if sj["from"] not in node_coords or sj["to"] not in node_coords:
            raise ValueError("synthetic join %s endpoint not in node universe"
                             % sj["id"])
        lookup[sj["id"]] = {
            "coordinates": [node_coords[sj["from"]], node_coords[sj["to"]]],
            "from": sj["from"], "to": sj["to"],
            "weight": sj["distance_m"],
        }
    return lookup


def _reconstruct(edge_ids: list, directions: list, claimed_length: float,
                 start_node: str, end_node: str, edge_lookup: dict,
                 node_coords: dict) -> dict:
    """Reconstruct a GeoJSON geometry from an ordered edge path.

    Verifies continuity from ``start_node`` to ``end_node``, that each edge is
    traversed in the recorded direction, and that the summed effective edge
    weights match ``claimed_length`` within ``_LEN_EPS`` m. Fails (ValueError)
    rather than emitting broken review geometry. A zero-edge same-node path
    yields a Point (acceptable; live data has none).
    """
    if not edge_ids:
        if start_node != end_node:
            raise ValueError("empty path but endpoints differ %r -> %r"
                             % (start_node, end_node))
        if abs(claimed_length - 0.0) > _LEN_EPS:
            raise ValueError("empty path claims non-zero length %.6f"
                             % claimed_length)
        if start_node not in node_coords:
            raise ValueError("start node %r has no coordinates" % start_node)
        return {"type": "Point",
                "coordinates": list(node_coords[start_node])}

    if len(edge_ids) != len(directions):
        raise ValueError("edge_ids/directions length mismatch")

    parts: list[list] = []
    current = start_node
    total = 0.0
    for eid, direction in zip(edge_ids, directions):
        edge = edge_lookup.get(eid)
        if edge is None:
            raise ValueError("path references unknown edge %s" % eid)
        if direction == "forward":
            if edge["from"] != current:
                raise ValueError("path discontinuity at %s: expected from=%r "
                                 "got %r" % (eid, current, edge["from"]))
            part = edge["coordinates"]
            current = edge["to"]
        elif direction == "reverse":
            if edge["to"] != current:
                raise ValueError("path discontinuity at %s (reverse): expected "
                                 "to=%r got %r" % (eid, current, edge["to"]))
            part = list(reversed(edge["coordinates"]))
            current = edge["from"]
        else:
            raise ValueError("unknown path direction %r" % direction)
        total += edge["weight"]
        parts.append(part)

    if current != end_node:
        raise ValueError("path ends at %r, expected %r" % (current, end_node))
    if abs(total - claimed_length) > _LEN_EPS:
        raise ValueError("path length %.6f does not match claimed %.6f m"
                         % (total, claimed_length))

    out: list = []
    for part in parts:
        for coord in part:
            if out and out[-1] == coord:
                continue
            out.append(list(coord))
    if len(out) < 2:
        raise ValueError("reconstructed path has <2 coordinates")
    return {"type": "LineString", "coordinates": out}


def _feature(feature_id: str, geometry: dict, properties: dict) -> dict:
    return {"type": "Feature", "id": feature_id,
            "geometry": geometry, "properties": properties}


def _feature_collection(features: list[dict]) -> dict:
    return {"type": "FeatureCollection", "features": features}


# --- per-output builders ----------------------------------------------------


def _build_source_edges(anchored: dict) -> list[dict]:
    features = []
    for edge in sorted(anchored["edges"], key=lambda e: e["id"]):
        prov = edge.get("provenance", {})
        properties = {
            "edge_id": edge["id"],
            "route_id": prov.get("route_id"),
            "prefecture": prov.get("prefecture"),
            "source_file": prov.get("source_file"),
            "source_fid": prov.get("source_fid"),
            "part": prov.get("part"),
        }
        for key in ("source_identity", "source_identity_kind"):
            if prov.get(key) is not None:
                properties[key] = prov[key]
        features.append(_feature(
            edge["id"],
            {"type": "LineString", "coordinates": edge["coordinates"]},
            properties))
    return features


def _section_join_usage(sections: dict, synthetic_ids: set) -> tuple[dict, dict]:
    """Map synthetic join id -> sorted section ids using it (primary/alt)."""
    primary_usage: dict = {}
    alt_usage: dict = {}
    for sec in sections["sections"]:
        sid = sec["id"]
        if "primary" in sec:
            for eid in sec["primary"]["edge_ids"]:
                if eid in synthetic_ids:
                    primary_usage.setdefault(eid, set()).add(sid)
        if "alternative" in sec:
            for eid in sec["alternative"]["edge_ids"]:
                if eid in synthetic_ids:
                    alt_usage.setdefault(eid, set()).add(sid)
    return ({k: sorted(v) for k, v in primary_usage.items()},
            {k: sorted(v) for k, v in alt_usage.items()})


def _topology_priority(applied: bool, used_primary: list, used_alt: list) -> str:
    if applied:
        if used_primary:
            return "P0"
        if used_alt:
            return "P1"
        return "P2"
    return "P1"


def _applied_cluster_route(sj: dict, prox: dict) -> tuple:
    """Deterministically match an applied endpoint_cluster join to its report
    record (kind + unordered node pair + exact stored rounded distance) and
    return (route_a, route_b). Fails on missing or ambiguous match."""
    pair = {sj["from"], sj["to"]}
    matches = []
    for rec in prox["proximity_report"]:
        if rec.get("kind") != "endpoint_cluster" or not rec.get("applied"):
            continue
        if {rec.get("from_node"), rec.get("to_node")} != pair:
            continue
        if rec.get("distance_m") != sj["distance_m"]:
            continue
        matches.append(rec)
    routes = {(rec.get("route_a"), rec.get("route_b")) for rec in matches}
    if not routes:
        raise ValueError("no applied report record for endpoint_cluster join %s"
                         % sj["id"])
    if len(routes) != 1:
        raise ValueError("ambiguous applied report record for endpoint_cluster "
                         "join %s (%d matches)" % (sj["id"], len(routes)))
    return next(iter(routes))


def _topology_items(anchored: dict, prox: dict, inventory: dict,
                    primary_usage: dict, alt_usage: dict,
                    node_coords: dict) -> tuple[list[dict], list[dict]]:
    """Return (geojson features, review-items) for all topology records."""
    features: list[dict] = []
    items: list[dict] = []

    synthetic_ids = {sj["id"] for sj in anchored["synthetic_joins"]}

    # 1. every applied synthetic join (stable SHJ id used as the review id).
    for sj in sorted(anchored["synthetic_joins"], key=lambda j: j["id"]):
        if sj["from"] not in node_coords or sj["to"] not in node_coords:
            raise ValueError("applied join %s endpoint not in node universe"
                             % sj["id"])
        used_primary = primary_usage.get(sj["id"], [])
        used_alt = alt_usage.get(sj["id"], [])
        priority = _topology_priority(True, used_primary, used_alt)
        geometry = {"type": "LineString",
                    "coordinates": [node_coords[sj["from"]],
                                    node_coords[sj["to"]]]}
        if sj["kind"] == "endpoint_cluster":
            route_a, route_b = _applied_cluster_route(sj, prox)
            reason = "applied: unambiguous <=5m endpoint cluster"
        elif sj["kind"] == "endpoint_to_line":
            route_a = sj.get("endpoint_route")
            route_b = sj.get("target_route")
            reason = "applied: unique endpoint-to-line <=5m candidate"
        else:
            raise ValueError("unexpected synthetic join kind %r" % sj["kind"])
        properties = {
            "review_id": sj["id"], "review_kind": sj["kind"], "applied": True,
            "distance_m": sj["distance_m"], "reason": reason,
            "route_a": route_a, "route_b": route_b,
            "from_node": sj["from"], "to_node": sj["to"],
            "priority": priority,
            "used_by_primary_sections": used_primary,
            "used_by_alternative_sections": used_alt,
        }
        features.append(_feature(sj["id"], geometry, properties))
        items.append({
            "review_id": sj["id"], "category": "topology", "kind": sj["kind"],
            "priority": priority, "status": "applied",
            "references": {
                "join_id": sj["id"], "route_a": route_a, "route_b": route_b,
                "from_node": sj["from"], "to_node": sj["to"],
                "distance_m": sj["distance_m"],
                "used_by_primary_sections": used_primary,
                "used_by_alternative_sections": used_alt,
            },
            "allowed_decisions": list(_ALLOWED_DECISIONS["topology_applied"]),
            "evidence_required": False, "decision": None,
        })

    # 2. every reported (rejected / gap / crossing) topology record.
    # Endpoint-to-line endpoint coordinates are matched by a deterministic key
    # that includes the projected coordinates (and the endpoint position) so two
    # candidates sharing a route pair and a rounded distance cannot collide; an
    # ambiguous match fails rather than guessing.
    etl_candidates: dict = {}
    for bucket in ("<=5m", "5-20m"):
        for rec in inventory["proximity_candidates"]["endpoint_to_line"][bucket]:
            key = (rec["endpoint_route"], rec["target_route"], rec["distance_m"],
                   tuple(rec["projected_coordinates"]))
            etl_candidates.setdefault(key, []).append(
                (tuple(rec["endpoint_coordinates"]), rec.get("endpoint")))

    for record in prox["proximity_report"]:
        kind = record["kind"]
        applied = bool(record.get("applied"))
        if applied:
            continue  # applied joins handled above from synthetic_joins
        rid = "REV_" + _hash16(_canon({
            "kind": kind, "route_a": record.get("route_a"),
            "route_b": record.get("route_b"), "distance_m": record.get("distance_m"),
            "coordinates": record.get("coordinates"),
            "from_node": record.get("from_node"), "to_node": record.get("to_node"),
        }))
        priority = "P1"
        if kind == "ambiguous_crossing":
            geometry = {"type": "Point",
                        "coordinates": list(record["coordinates"])}
        elif kind == "endpoint_pair_gap":
            geometry = {"type": "LineString",
                        "coordinates": [list(c) for c in record["coordinates"]]}
        elif kind == "endpoint_cluster":
            if record["from_node"] not in node_coords or \
                    record["to_node"] not in node_coords:
                raise ValueError("rejected join %s endpoint not in node universe"
                                 % rid)
            geometry = {"type": "LineString",
                        "coordinates": [node_coords[record["from_node"]],
                                        node_coords[record["to_node"]]]}
        elif kind == "endpoint_to_line":
            if record["from_node"] not in node_coords:
                raise ValueError("rejected join %s endpoint node missing" % rid)
            geometry = {"type": "LineString",
                        "coordinates": [node_coords[record["from_node"]],
                                        list(record["coordinates"])]}
        elif kind == "endpoint_to_line_gap":
            key = (record["route_a"], record["route_b"], record["distance_m"],
                   tuple(record["coordinates"]))
            matches = etl_candidates.get(key, [])
            if not matches:
                raise ValueError("no endpoint coordinate for %s" % rid)
            distinct = {coords for coords, _ in matches}
            if len(distinct) != 1:
                raise ValueError("ambiguous endpoint coordinate for %s (%d "
                                 "distinct)" % (rid, len(distinct)))
            endpoint = list(next(iter(distinct)))
            geometry = {"type": "LineString",
                        "coordinates": [endpoint, list(record["coordinates"])]}
        else:
            raise ValueError("unexpected proximity report kind %r" % kind)

        properties = {
            "review_id": rid, "review_kind": kind, "applied": False,
            "distance_m": record.get("distance_m"), "reason": record.get("reason"),
            "route_a": record.get("route_a"), "route_b": record.get("route_b"),
            "priority": priority,
        }
        features.append(_feature(rid, geometry, properties))
        items.append({
            "review_id": rid, "category": "topology", "kind": kind,
            "priority": priority, "status": "reported",
            "references": {
                "route_a": record.get("route_a"), "route_b": record.get("route_b"),
                "distance_m": record.get("distance_m"),
            },
            "allowed_decisions": list(_ALLOWED_DECISIONS["topology_reported"]),
            "evidence_required": True, "decision": None,
        })

    features.sort(key=lambda f: f["id"])
    items.sort(key=lambda i: i["review_id"])
    return features, items


def _anchor_priority(usable: bool) -> str:
    return "P0" if not usable else "P2"


def _anchor_items(anchored: dict) -> tuple[list[dict], list[dict]]:
    """Return (geojson features, review-items) for all 88 temple anchors."""
    features: list[dict] = []
    items: list[dict] = []
    for ta in sorted(anchored["temple_anchors"],
                     key=lambda t: t["temple_number"]):
        number = ta["temple_number"]
        rid = "REV_ANCHOR_%d" % number
        priority = _anchor_priority(ta["usable_for_routing"])
        common = {
            "review_id": rid, "temple_number": number,
            "temple_id": ta.get("temple_id"), "name_jp": ta.get("name_jp"),
            "confidence": ta["confidence"], "usable_for_routing": ta["usable_for_routing"],
            "distance_m": ta["distance_m"],
            "candidate_edge_ids": list(ta["candidate_edge_ids"]),
        }
        # Temple Point (always present; the source point is never moved).
        point_props = dict(common)
        point_props.update({
            "anchor_kind": "temple_point", "priority": priority,
        })
        features.append(_feature(
            rid, {"type": "Point", "coordinates": list(ta["coordinates"])},
            point_props))
        # Projected anchors additionally carry a review_visualization_only
        # offset LineString (never a graph edge) whenever a projected location
        # exists. This includes shared-node tie resolutions (which have a
        # projected_coordinates but NO single chosen_edge_id) as well as unique
        # projections. Tied-unresolved anchors have the point only.
        if "projected_coordinates" in ta:
            offset_rid = "%s:offset" % rid
            offset_props = dict(common)
            offset_props.update({
                "anchor_kind": "offset_line",
                "review_visualization_only": True,
                "priority": priority,
            })
            # Truthfully expose the optional chosen edge, the resolution kind and
            # the resolved edge list (present only for shared-node ties).
            if "chosen_edge_id" in ta:
                offset_props["chosen_edge_id"] = ta["chosen_edge_id"]
            if "resolution" in ta:
                offset_props["resolution"] = ta["resolution"]
            if "resolved_edge_ids" in ta:
                offset_props["resolved_edge_ids"] = list(ta["resolved_edge_ids"])
            features.append(_feature(
                offset_rid,
                {"type": "LineString",
                 "coordinates": [list(ta["coordinates"]),
                                 list(ta["projected_coordinates"])]},
                offset_props))

        status = ta["confidence"]
        items.append({
            "review_id": rid, "category": "anchor", "kind": "temple_anchor",
            "priority": priority, "status": status,
            "references": {
                "temple_number": number, "temple_id": ta.get("temple_id"),
                "distance_m": ta["distance_m"],
                "candidate_edge_ids": list(ta["candidate_edge_ids"]),
                "chosen_edge_id": ta.get("chosen_edge_id"),
                "anchor_node_id": ta.get("anchor_node_id"),
                "resolution": ta.get("resolution"),
                "resolved_edge_ids": (list(ta["resolved_edge_ids"])
                                      if "resolved_edge_ids" in ta else None),
            },
            "allowed_decisions": list(_ALLOWED_DECISIONS["anchor"]),
            "evidence_required": status == "review_required", "decision": None,
        })

    features.sort(key=lambda f: f["id"])
    items.sort(key=lambda i: i["review_id"])
    return features, items


def _section_priority(status: str) -> str:
    if status == "candidate":
        return "P2"
    return "P0"  # ambiguous / disconnected / anchor_review_required all need review


def _section_items(anchored: dict, sections: dict, edge_lookup: dict,
                   node_coords: dict) -> tuple[list[dict], list[dict]]:
    """Return (geojson features, review-items) for the 87 temple sections."""
    features: list[dict] = []
    items: list[dict] = []
    synthetic_ids = {sj["id"] for sj in anchored["synthetic_joins"]}
    for sec in sections["sections"]:
        sid = sec["id"]
        status = sec["status"]
        priority = _section_priority(status)
        start_node = sec["anchors"]["from"].get("node_id")
        end_node = sec["anchors"]["to"].get("node_id")

        for variant in ("primary", "alternative"):
            path = sec.get(variant)
            if path is None:
                continue
            if start_node is None or end_node is None:
                raise ValueError("%s %s has no anchor node_id" % (sid, variant))
            geometry = _reconstruct(path["edge_ids"], path["directions"],
                                    path["length_m"], start_node, end_node,
                                    edge_lookup, node_coords)
            join_ids = sorted(eid for eid in path["edge_ids"]
                              if eid in synthetic_ids)
            vid = "%s:%s" % (sid, variant)
            features.append(_feature(
                vid, geometry, {
                    "review_id": vid, "section_id": sid, "status": status,
                    "variant": variant, "length_m": path["length_m"],
                    "synthetic_join_ids": join_ids, "priority": priority,
                }))

        items.append({
            "review_id": sid, "category": "section", "kind": "temple_section",
            "priority": priority, "status": status,
            "references": {
                "from_temple": sec["from_temple"], "to_temple": sec["to_temple"],
                "status": status,
                "primary_edge_ids": (sec.get("primary", {}).get("edge_ids")
                                     if "primary" in sec else None),
                "alternative_edge_ids": (sec.get("alternative", {}).get("edge_ids")
                                         if "alternative" in sec else None),
            },
            "allowed_decisions": list(_SECTION_DECISIONS.get(
                status, _SECTION_DECISIONS["candidate"])),
            "evidence_required": status != "candidate", "decision": None,
        })

    features.sort(key=lambda f: f["id"])
    items.sort(key=lambda i: i["review_id"])
    return features, items


# --- report ----------------------------------------------------------------


def _input_accounting(normalized: dict, inventory: dict, prox: dict,
                      anchored: dict, sections: dict) -> dict:
    norm_acct = normalized["accounting"]
    inv_acct = inventory["analysis_accounting"]
    prox_acct = prox["accounting"]
    anch_acct = anchored["accounting"]
    sec_acct = sections["accounting"]
    return {
        "normalized": {
            "routes": norm_acct.get("routes"), "linestrings": norm_acct.get("linestrings"),
            "points": norm_acct.get("points"), "temples": norm_acct.get("temples"),
        },
        "topology_inventory": {
            "route_records": inv_acct.get("route_records"),
            "source_points": inv_acct.get("source_points"),
            "proximity_summary": inventory["proximity_candidates"].get("summary"),
            "intersections_summary": inventory["intersections"].get("summary"),
        },
        "proximity_graph": {
            "nodes": prox_acct.get("nodes"), "edges": prox_acct.get("edges"),
            "synthetic_nodes": prox_acct.get("synthetic_nodes"),
            "synthetic_joins": prox_acct.get("synthetic_joins"),
            "components_after": prox_acct.get("components_after"),
            "proximity": prox_acct.get("proximity"),
        },
        "anchored_graph": {
            "temple_anchors": anch_acct.get("temple_anchors"),
            "anchors_usable": anch_acct.get("anchors_usable"),
            "anchors_review_required": anch_acct.get("anchors_review_required"),
            "traversal_edges": anch_acct.get("traversal_edges"),
            "components_after": anch_acct.get("components_after"),
        },
        "temple_sections": dict(sec_acct),
    }


def _output_counts(files: dict, topo_features: int, topo_items: int,
                   anchor_features: int, anchor_items: int,
                   section_features: int, section_items: int) -> dict:
    return {
        "source_edges_features": len(files["source-edges.geojson"]["features"]),
        "topology_features": topo_features,
        "topology_items": topo_items,
        "anchors_features": anchor_features,
        "anchor_items": anchor_items,
        "sections_features": section_features,
        "section_items": section_items,
        "review_items_total": topo_items + anchor_items + section_items,
    }


def _priority_counts(topo_items, anchor_items, section_items) -> dict:
    def tally(items):
        counts = {"P0": 0, "P1": 0, "P2": 0}
        for item in items:
            counts[item["priority"]] += 1
        return counts

    return {
        "topology": tally(topo_items),
        "anchor": tally(anchor_items),
        "section": tally(section_items),
        "total": {p: sum(t[p] for t in (
            tally(topo_items), tally(anchor_items), tally(section_items)))
            for p in ("P0", "P1", "P2")},
    }


def _unresolved_focal_counts(topo_items, anchor_items, section_items) -> dict:
    def by_kind(items):
        counts: dict = {}
        for item in items:
            if item["status"] != "reported":
                continue  # only unresolved (reported) topology items
            counts[item["kind"]] = counts.get(item["kind"], 0) + 1
        return counts

    return {
        "review_required_anchors": sum(
            1 for i in anchor_items if i["status"] == "review_required"),
        "disconnected_sections": sum(
            1 for i in section_items if i["status"] == "disconnected"),
        "ambiguous_sections": sum(
            1 for i in section_items if i["status"] == "ambiguous"),
        "anchor_review_required_sections": sum(
            1 for i in section_items if i["status"] == "anchor_review_required"),
        "topology_reported": by_kind(topo_items),
    }


# --- orchestration ----------------------------------------------------------


def build_review_pack(normalized: dict, inventory: dict, prox: dict,
                      anchored: dict, sections: dict) -> dict:
    """Build the complete deterministic review pack in memory.

    Returns ``{"report": ..., "files": {filename: payload}}`` where every payload
    is a JSON-serializable dict. Raises ValueError on validation / continuity /
    accounting failure. Nothing is written here.
    """
    validate_inputs(normalized, inventory, prox, anchored, sections)

    node_coords = _node_coordinate_index(anchored)
    edge_lookup = _edge_lookup(anchored, node_coords)
    synthetic_ids = {sj["id"] for sj in anchored["synthetic_joins"]}
    primary_usage, alt_usage = _section_join_usage(sections, synthetic_ids)

    source_features = _build_source_edges(anchored)
    topo_features, topo_items = _topology_items(
        anchored, prox, inventory, primary_usage, alt_usage, node_coords)
    anchor_features, anchor_items = _anchor_items(anchored)
    section_features, section_items = _section_items(
        anchored, sections, edge_lookup, node_coords)

    files = {
        "source-edges.geojson": _feature_collection(source_features),
        "topology.geojson": _feature_collection(topo_features),
        "anchors.geojson": _feature_collection(anchor_features),
        "sections.geojson": _feature_collection(section_features),
        "review-items.json": {
            "schema_version": 1,
            "kind": "review_items",
            "dataset_id": normalized["dataset_id"],
            "snapshot_sha256": normalized["snapshot_sha256"],
            "note": "generated immutable review queue (NOT a decisions file). "
                    "Reruns overwrite this generated queue; decisions belong in "
                    "a future separate graph_overrides/review-decisions file and "
                    "are never recorded here. decision is always null.",
            "items": topo_items + anchor_items + section_items,
        },
    }
    files["review-items.json"]["items"].sort(key=lambda i: i["review_id"])

    # Fail on any duplicate feature id / review id produced during construction.
    _assert_unique_ids(files, (
        ("review-items.json", files["review-items.json"]["items"]),
    ))

    output_counts = _output_counts(files, len(topo_features), len(topo_items),
                                   len(anchor_features), len(anchor_items),
                                   len(section_features), len(section_items))
    priority_counts = _priority_counts(topo_items, anchor_items, section_items)
    unresolved = _unresolved_focal_counts(topo_items, anchor_items, section_items)

    file_list = [
        {"filename": "source-edges.geojson",
         "features": len(source_features)},
        {"filename": "topology.geojson", "features": len(topo_features)},
        {"filename": "anchors.geojson", "features": len(anchor_features)},
        {"filename": "sections.geojson", "features": len(section_features)},
        {"filename": "review-items.json", "items": len(topo_items) + len(anchor_items) + len(section_items)},
        {"filename": "report.json", "items": 1},
    ]

    report = {
        "schema_version": 1,
        "kind": "review_pack",
        "dataset_id": normalized["dataset_id"],
        "snapshot_sha256": normalized["snapshot_sha256"],
        "projection": dict(anchored.get("projection") or {}),
        "limitation": anchored.get("limitation"),
        "note": "deterministic QGIS review pack; no timestamp. All geometry is "
                "WGS84. The review queue is generated afresh on every run; "
                "decisions are deliberately out of scope (a future "
                "graph_overrides/review-decisions file).",
        "priority_policy": {
            "P0": "review_required anchors; ambiguous/disconnected/"
                  "anchor_review_required sections; applied synthetic joins "
                  "used by a primary path",
            "P1": "applied synthetic joins used only by alternatives; every "
                  "rejected <=5m candidate; every 5-20m gap; every ambiguous "
                  "crossing",
            "P2": "other accepted (near/offset) anchors; candidate sections; "
                  "unused applied synthetic joins",
        },
        "input_accounting": _input_accounting(
            normalized, inventory, prox, anchored, sections),
        "output_counts": output_counts,
        "review_priority_counts": priority_counts,
        "unresolved_focal_counts": unresolved,
        "preservation_notes": [
            "source accounting (normalized==inventory), proximity source "
            "routes/linestrings/points, and anchored nodes/edges/route_sources/"
            "synthetic_nodes/synthetic_joins/source lengths/components_before "
            "are validated equal to their upstream inputs at import, so these "
            "preservation claims are substantiated, not assumed; the review "
            "pack never mutates them",
            "temple points are never moved; offset LineStrings in anchors.geojson "
            "are review_visualization_only=true and are never graph edges",
            "sections.geojson reconstructs geometry ONLY from ordered "
            "traversal_edges + synthetic_joins, respecting directions, with "
            "continuity and claimed-length (1e-6 m) verification; it never "
            "routes on raw source edges",
            "review-items.json is a generated queue, not a decisions file; "
            "reruns overwrite it and decision remains null",
        ],
        "files": file_list,
    }
    files["report.json"] = report
    return {"report": report, "files": files}


def run_review(normalized_path: str, inventory_path: str, prox_path: str,
               anchored_path: str, sections_path: str, output_dir: str) -> dict:
    """Load the five inputs, build the full pack in memory (validating every
    payload before any write), then write each deterministic JSON file atomically
    via the existing atomic writer. Each file is atomic on its own; a filesystem
    failure mid-loop can leave a mixed-version directory (no whole-pack
    transaction is engineered)."""
    with open(normalized_path, encoding="utf-8") as stream:
        normalized = json.load(stream)
    with open(inventory_path, encoding="utf-8") as stream:
        inventory = json.load(stream)
    with open(prox_path, encoding="utf-8") as stream:
        prox = json.load(stream)
    with open(anchored_path, encoding="utf-8") as stream:
        anchored = json.load(stream)
    with open(sections_path, encoding="utf-8") as stream:
        sections = json.load(stream)

    pack = build_review_pack(normalized, inventory, prox, anchored, sections)
    for filename, payload in pack["files"].items():
        normalize.write_atomic(
            os.path.join(output_dir, filename), payload)
    return pack["report"]