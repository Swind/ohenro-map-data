"""Phase 4 temple interval candidate inference for 88sekaiisan.

Consumes the Phase 3 ``anchored_route_graph`` (``build-anchors`` output) and
writes a NEW deterministic ``temple_sections`` document with exactly 87
temple intervals (1->2 through 87->88), each statused as one of:

* ``candidate`` - a single weighted-shortest path exists (no near-equal
  replacement);
* ``ambiguous`` - a replacement path within ``1.15x`` of the primary is kept
  alongside it;
* ``disconnected`` - the two usable anchors are not in the same effective
  component;
* ``anchor_review_required`` - either anchor is not usable, so no automatic
  inference is attempted.

Routing is over the EFFECTIVE undirected graph that consists ONLY of the
derived ``traversal_edges`` (weight = ``length_m``) plus the existing
``synthetic_joins`` (weight = ``distance_m``). The original source ``edges``
are never routed on, and a temple's offset distance is never used as an edge
or cost.

Per datasets/sekaiisan_henro/docs/sekaiisan-henro-graph-plan.md §Phase 5, the weighted shortest
path uses stdlib heapq Dijkstra with a deterministic lexicographic tie-break
(shortest total weight; within a tiny documented epsilon prefer the
lexicographically smallest ordered edge-ID sequence, then node sequence).
No invented join ever crosses a disconnected gap, and no result is ever
labelled resolved / official / navigable. ``closure_88_1`` is always
``{"status": "not_requested"}``.

This module never mutates source geometry and writes byte-deterministically
(temp -> flush -> fsync -> replace). On failure the prior output is untouched.
"""

from __future__ import annotations

import heapq
import json
import math

from datasets.sekaiisan_henro import normalize

# Tiny epsilon (metres) for path-weight tie-breaking: two paths to the same
# node whose total weight differs by <= this are treated as tied and resolved
# by the lexicographically smallest edge-ID sequence (guards float round-off;
# real path lengths are thousands of metres, so this is far below any
# meaningful difference).
_TIE_EPS = 1e-6
# Tiny explicit epsilon added to the 1.15x ambiguous threshold so the boundary
# comparison is a strict float guard, not a claim of exact metre equality.
_REPLACEMENT_FACTOR = 1.15
_REPL_EPS = 1e-6

_STATUSES = ("candidate", "ambiguous", "disconnected", "anchor_review_required")


def _canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


# --- validation (trust boundary) --------------------------------------------


def validate_anchored_graph(data: dict) -> None:
    """Validate the anchored route graph schema; raise ValueError on issues."""
    if not isinstance(data, dict):
        raise ValueError("sections input must be a JSON object")
    if data.get("kind") != "anchored_route_graph":
        raise ValueError("sections input must be kind=anchored_route_graph, got %r"
                         % data.get("kind"))
    for key in ("dataset_id", "snapshot_sha256", "schema_version", "nodes",
                "synthetic_nodes", "anchor_nodes", "edges", "synthetic_joins",
                "temple_anchors", "traversal_edges", "components", "accounting"):
        if key not in data:
            raise ValueError("anchored graph missing required key: %s" % key)
    for section in ("nodes", "synthetic_nodes", "anchor_nodes", "edges",
                    "synthetic_joins", "temple_anchors", "traversal_edges"):
        if not isinstance(data[section], list):
            raise ValueError("anchored graph %s must be a list" % section)

    # Node id universe for endpoint-reference checks.
    universe = set()
    for n in data["nodes"] + data["synthetic_nodes"] + data["anchor_nodes"]:
        if not isinstance(n, dict) or "id" not in n:
            raise ValueError("a node record is missing 'id'")
        universe.add(n["id"])

    # Unique edge ids + nonnegative finite weights + endpoint references.
    seen_edge_ids: set = set()
    for section, key, wkey in (("traversal_edges", "id", "length_m"),
                               ("synthetic_joins", "id", "distance_m")):
        for edge in data[section]:
            if not isinstance(edge, dict):
                raise ValueError("a %s record is not an object" % section)
            eid = edge.get(key)
            if not isinstance(eid, str) or not eid:
                raise ValueError("a %s record is missing a valid %s" % (section, key))
            if eid in seen_edge_ids:
                raise ValueError("duplicate edge id across traversal/synthetic: %s" % eid)
            seen_edge_ids.add(eid)
            for node_key in ("from", "to"):
                node_id = edge.get(node_key)
                if node_id not in universe:
                    raise ValueError("%s %s endpoint %r not in node universe"
                                     % (section, eid, node_id))
            weight = edge.get(wkey)
            if not isinstance(weight, (int, float)) or isinstance(weight, bool):
                raise ValueError("%s %s has a non-numeric weight" % (section, eid))
            if not math.isfinite(weight):
                raise ValueError("%s %s has a non-finite weight" % (section, eid))
            if weight < 0:
                raise ValueError("%s %s has a negative weight" % (section, eid))

    # 88 temple anchors numbered exactly 1..88 once.
    anchors = data["temple_anchors"]
    if len(anchors) != 88:
        raise ValueError("expected exactly 88 temple anchors, got %d" % len(anchors))
    seen_numbers: set = set()
    for anchor in anchors:
        if not isinstance(anchor, dict) or "temple_number" not in anchor:
            raise ValueError("a temple anchor record is missing 'temple_number'")
        number = anchor["temple_number"]
        if not isinstance(number, int) or not (1 <= number <= 88):
            raise ValueError("temple anchor number %r out of range 1..88" % (number,))
        if number in seen_numbers:
            raise ValueError("duplicate temple anchor number %d" % number)
        seen_numbers.add(number)
        usable = anchor.get("usable_for_routing")
        if not isinstance(usable, bool):
            raise ValueError("temple anchor %d missing usable_for_routing flag" % number)
        if usable and anchor.get("anchor_node_id") not in universe:
            raise ValueError(
                "usable temple anchor %d has no valid anchor_node_id in the "
                "effective graph" % number)
    if seen_numbers != set(range(1, 89)):
        raise ValueError("temple anchor numbers missing: %s"
                         % ", ".join(map(str, sorted(set(range(1, 89)) - seen_numbers))))


# --- Dijkstra ---------------------------------------------------------------


def _path_lt(weight_a: float, seq_a: tuple, nodes_a: tuple,
             weight_b: float, seq_b: tuple, nodes_b: tuple) -> bool:
    """True when path A strictly precedes path B under the deterministic order.

    A clearly lower weight wins; otherwise, when the two weights differ by
    ``<= _TIE_EPS`` (the documented tiny float guard), the lexicographically
    smallest edge-ID sequence wins, then the node sequence. This is the single
    comparison used both by Dijkstra's per-node best selection and by the
    replacement-path candidate selection, so they can never disagree.
    """
    if weight_b - weight_a > _TIE_EPS:
        return True  # A is clearly lighter
    if weight_a - weight_b > _TIE_EPS:
        return False  # B is clearly lighter
    # Weights within epsilon: tie-break by edge sequence, then node sequence.
    return (seq_a, nodes_a) < (seq_b, nodes_b)


def _adjacency(traversal_edges: list[dict], synthetic_joins: list[dict]) -> dict:
    """Build undirected adjacency from traversal edges + synthetic joins.

    Returns ``node -> list[(neighbor, weight, edge_id, direction)]`` where
    ``direction`` is ``"forward"`` when the stored edge.from->edge.to matches
    the traversal direction and ``"reverse"`` otherwise.
    """
    adj: dict = {}
    for edge in traversal_edges:
        w = edge["length_m"]
        for a, b, direction in ((edge["from"], edge["to"], "forward"),
                                (edge["to"], edge["from"], "reverse")):
            adj.setdefault(a, []).append((b, w, edge["id"], direction))
    for join in synthetic_joins:
        w = join["distance_m"]
        for a, b, direction in ((join["from"], join["to"], "forward"),
                                (join["to"], join["from"], "reverse")):
            adj.setdefault(a, []).append((b, w, join["id"], direction))
    return adj


def _shortest_path(adj: dict, start: str, goal: str,
                   forbidden_edge_ids: frozenset) -> dict | None:
    """Weighted shortest path (stdlib heapq Dijkstra).

    Returns ``{"weight", "edge_ids", "directions", "node_ids"}`` or None when no
    path exists. Tie-break: within ``_TIE_EPS`` of the best weight, prefer the
    lexicographically smallest ordered edge-ID sequence (then node sequence).
    Simple paths only (no node revisit), which guarantees termination even with
    zero-weight synthetic edges.
    """
    if start == goal:
        return {"weight": 0.0, "edge_ids": [], "directions": [], "node_ids": [start]}
    # best[node] = (weight, edge_seq, node_seq)
    best: dict = {}
    # heap: (weight, edge_seq, node_seq, node, edge_id, direction)
    heap: list = [(0.0, (), (start,), start, None, None)]
    while heap:
        weight, edge_seq, node_seq, node, edge_id, direction = heapq.heappop(heap)
        current = best.get(node)
        if current is not None and not _path_lt(
                weight, edge_seq, node_seq, current[0], current[1], current[2]):
            continue  # not strictly better than the recorded best
        best[node] = (weight, edge_seq, node_seq)
        if node == goal:
            continue  # a goal path is found; keep searching for better ties
        for neighbor, w, eid, direction in adj.get(node, ()):
            if eid in forbidden_edge_ids:
                continue  # edge removed (replacement-path rerun)
            if neighbor in node_seq:
                continue  # no node revisit (simple paths only, terminates)
            heapq.heappush(heap, (weight + w, edge_seq + (eid,),
                                  node_seq + (neighbor,), neighbor, eid, direction))
    result = best.get(goal)
    if result is None:
        return None
    weight, edge_seq, node_seq = result
    # Reconstruct directions by re-walking the chosen node sequence.
    directions = []
    for i in range(len(node_seq) - 1):
        a, b = node_seq[i], node_seq[i + 1]
        for nb, _, eid, direction in adj.get(a, ()):
            if nb == b and eid == edge_seq[i]:
                directions.append(direction)
                break
        else:
            raise AssertionError("failed to reconstruct direction for path %s" % (edge_seq,))
    return {
        "weight": weight,
        "edge_ids": list(edge_seq),
        "directions": directions,
        "node_ids": list(node_seq),
    }


# --- section building -------------------------------------------------------


def _anchor_summary(anchor: dict) -> dict:
    summary = {
        "temple_number": anchor["temple_number"],
        "confidence": anchor["confidence"],
        "status": anchor["status"],
        "usable_for_routing": anchor["usable_for_routing"],
        "distance_m": anchor["distance_m"],
    }
    if "anchor_node_id" in anchor:
        summary["node_id"] = anchor["anchor_node_id"]
    return summary


def _path_summary(path: dict) -> dict:
    return {
        "edge_ids": list(path["edge_ids"]),
        "directions": list(path["directions"]),
        "length_m": path["weight"],
    }


def _best_replacement(adj: dict, start: str, goal: str, primary_edge_ids: list,
                      primary_weight: float) -> dict | None:
    """Shortest replacement path excluding each primary edge in turn.

    Returns the best (weight, edge_ids, directions, node_ids) among the
    deduplicated per-edge reruns, by the same deterministic ordering, or None
    when no edge-free rerun finds a path.
    """
    candidates: dict = {}  # edge_ids tuple -> path
    for excluded in primary_edge_ids:
        path = _shortest_path(adj, start, goal, frozenset({excluded}))
        if path is None:
            continue
        key = tuple(path["edge_ids"])
        if key in candidates:
            continue  # deduplicate identical path sequences
        candidates[key] = path
    if not candidates:
        return None

    best = None
    for path in candidates.values():
        if best is None or _path_lt(
                path["weight"], tuple(path["edge_ids"]), tuple(path["node_ids"]),
                best["weight"], tuple(best["edge_ids"]), tuple(best["node_ids"])):
            best = path
    return best


def build_sections(data: dict) -> dict:
    """Build the deterministic 87-section temple sections document.

    ``data`` is the Phase 3 ``anchored_route_graph``. Raises ValueError on
    schema/validation failure.
    """
    validate_anchored_graph(data)

    anchors_by_number = {a["temple_number"]: a for a in data["temple_anchors"]}
    traversal_edges = sorted(data["traversal_edges"], key=lambda e: e["id"])
    synthetic_joins = sorted(data["synthetic_joins"], key=lambda j: j["id"])
    adj = _adjacency(traversal_edges, synthetic_joins)

    sections: list[dict] = []
    by_status = {"candidate": 0, "ambiguous": 0, "disconnected": 0,
                 "anchor_review_required": 0}
    paths_using_synthetic = 0
    synthetic_ids = {j["id"] for j in synthetic_joins}

    for i in range(1, 88):
        from_anchor = anchors_by_number[i]
        to_anchor = anchors_by_number[i + 1]
        section = {
            "id": "SEC_%d_%d" % (i, i + 1),
            "from_temple": i,
            "to_temple": i + 1,
            "anchors": {
                "from": _anchor_summary(from_anchor),
                "to": _anchor_summary(to_anchor),
            },
        }
        if not (from_anchor["usable_for_routing"] and to_anchor["usable_for_routing"]):
            section["status"] = "anchor_review_required"
            by_status["anchor_review_required"] += 1
            sections.append(section)
            continue

        start = from_anchor["anchor_node_id"]
        goal = to_anchor["anchor_node_id"]
        primary = _shortest_path(adj, start, goal, frozenset())
        if primary is None:
            section["status"] = "disconnected"
            by_status["disconnected"] += 1
            sections.append(section)
            continue

        if synthetic_ids & set(primary["edge_ids"]):
            paths_using_synthetic += 1

        replacement = _best_replacement(adj, start, goal, primary["edge_ids"],
                                        primary["weight"])
        section["primary"] = _path_summary(primary)
        if replacement is not None and (
                replacement["weight"] <= _REPLACEMENT_FACTOR * primary["weight"] + _REPL_EPS):
            section["status"] = "ambiguous"
            section["alternative"] = _path_summary(replacement)
            section["diagnostics"] = {
                "alternative_length_m": replacement["weight"],
                "alternative_to_primary_ratio": (
                    replacement["weight"] / primary["weight"] if primary["weight"] else None),
                "note": "replacement path is not resolved and remains a candidate "
                        "for human review",
            }
            by_status["ambiguous"] += 1
        else:
            section["status"] = "candidate"
            if replacement is not None:
                section["diagnostics"] = {
                    "best_rejected_alternative_length_m": replacement["weight"],
                    "alternative_to_primary_ratio": (
                        replacement["weight"] / primary["weight"] if primary["weight"] else None),
                    "note": "replacement exceeds 1.15x primary; only the primary "
                            "candidate is retained",
                }
            by_status["candidate"] += 1
        sections.append(section)

    return {
        "schema_version": 1,
        "kind": "temple_sections",
        "dataset_id": data["dataset_id"],
        "snapshot_sha256": data["snapshot_sha256"],
        "projection": dict(data["projection"]),
        "limitation": data["limitation"],
        "note": "Phase 4 temple interval candidate inference over the effective "
                "undirected graph of traversal_edges + synthetic_joins only "
                "(original source edges and temple offset distances are never "
                "routed). Weighted shortest path via stdlib Dijkstra with "
                "deterministic lexicographic tie-break. No interval is resolved, "
                "official or navigable; disconnected and anchor_review_required "
                "are legitimate, traceable outcomes and no invented join ever "
                "crosses a gap.",
        "sections": sections,
        "closure_88_1": {"status": "not_requested"},
        "accounting": {
            "sections_total": len(sections),
            "by_status": dict(by_status),
            "paths_using_synthetic_joins": paths_using_synthetic,
            "note": "deterministic output; no timestamp. Intervals 1->2 through "
                    "87->88 (87 sections); closure_88_1 is not requested.",
        },
    }


def run_sections(input_path: str, output_path: str) -> dict:
    """Load the anchored graph, build sections, and write them atomically.

    On failure the prior output (if any) is left untouched.
    """
    with open(input_path, encoding="utf-8") as stream:
        data = json.load(stream)
    result = build_sections(data)
    normalize.write_atomic(output_path, result)
    return result