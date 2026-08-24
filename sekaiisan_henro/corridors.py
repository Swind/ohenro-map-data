"""Phase 4b parallel section-corridor classifier for 88sekaiisan.

Consumes the Phase 3 ``anchored_route_graph`` (``build-anchors`` output) and
writes two deterministic documents covering all 87 temple intervals
(1->2 through 87->88):

* ``section-corridors.json`` - one record per interval classifying the exact
  set of effective edges that lie on at least one SIMPLE path from the interval
  anchor to the next, with every OTHER usable temple anchor node forbidden as
  an internal transit node;
* ``section-corridor-edges.geojson`` - one LineString feature per
  ``(section_id, effective_edge_id)`` assignment (plus one feature per
  unassigned effective edge), sorted with stable feature IDs for QGIS.

Corridor definition (fixed by the lead):

* ``SEC_i_(i+1)`` corridor = UNION of all effective edges that lie on at least
  one SIMPLE path from temple ``i`` anchor to temple ``i+1`` anchor, with every
  other usable temple anchor node forbidden as an internal transit node. All
  reconnecting recommended branches are retained regardless of length (NO
  1.15x / length threshold). Dead ends, lollipop cycles attached through one
  articulation, and the opposite around-Shikoku route (which passes other
  temple anchors) are excluded.
* Simple paths are NOT enumerated. The exact edge set is found via deterministic
  undirected vertex-biconnected edge blocks (Tarjan edge stack, correctly
  supporting parallel edges) plus the block-cut forest: after removing the
  forbidden other-anchor nodes, the unique block-cut-tree path between the
  section endpoints is found and all edge blocks on it are unioned. This is the
  exact edge set lying on some allowed simple s-t path.
* Statuses: ``corridor`` (cyclomatic number E-V+1 == 0), ``branched_corridor``
  (E-V+1 > 0), ``disconnected`` (no allowed path), ``anchor_review_required``
  (either endpoint anchor unusable).
* ``s == t`` is a zero-edge corridor with shortest length 0. Positive/zero edge
  weights never affect corridor membership. Synthetic joins remain explicit.

Routing / membership is over the EFFECTIVE undirected graph consisting ONLY of
the derived ``traversal_edges`` plus the existing ``synthetic_joins``. The
original source ``edges`` are never routed on and a temple's offset distance is
never used as an edge or cost. The shortest-path field is a diagnostic over the
corridor only (reusing the deterministic Dijkstra semantics of ``sections.py``
as a reference); it is NOT the corridor definition.

A global effective-edge classification lists every effective edge with its
sorted section ids, assignment count and ``assigned_once`` /
``assigned_multiple`` / ``unassigned`` label; no claim is made that assignment
is exclusive (an edge may legitimately appear in more than one corridor).

This module never mutates source geometry and writes byte-deterministically
(temp -> flush -> fsync -> replace). Both payloads are fully built in memory
before any write, and each file is written atomically on its own; a filesystem
failure between the two writes can leave a mixed-version pair (no whole-pack
transaction is engineered).
"""

from __future__ import annotations

import heapq
import json
import os

from sekaiisan_henro import normalize, sections

# Tiny epsilon (metres) for shortest-diagnostic weight tie-breaking: two paths
# whose total weight differs by <= this are treated as tied and resolved by the
# lexicographically smallest ordered edge-ID sequence (guards float round-off).
_TIE_EPS = 1e-6

_STATUSES = ("corridor", "branched_corridor", "disconnected",
             "anchor_review_required")


def _canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


# --- validation (trust boundary) --------------------------------------------


def validate_anchored_graph(data: dict) -> None:
    """Validate the anchored route graph; reuses the Phase 4 trust boundary."""
    sections.validate_anchored_graph(data)


# --- effective graph helpers ------------------------------------------------


def _effective_edges(data: dict) -> list[dict]:
    """Return every effective edge (traversal_edges + synthetic_joins) with a
    unified ``kind`` and, for traversal edges, its ``source_edge_id``."""
    out = []
    for te in data["traversal_edges"]:
        out.append({
            "id": te["id"], "from": te["from"], "to": te["to"],
            "kind": "traversal_edge",
            "source_edge_id": te.get("source_edge_id"),
            "length_m": te["length_m"], "coordinates": te["coordinates"],
        })
    for sj in data["synthetic_joins"]:
        out.append({
            "id": sj["id"], "from": sj["from"], "to": sj["to"],
            "kind": "synthetic_join", "source_edge_id": None,
            "length_m": sj["distance_m"], "coordinates": None,
        })
    return out


def _node_coordinate_index(data: dict) -> dict:
    """Map node id -> [lon, lat] over source + synthetic + anchor nodes."""
    index: dict = {}
    for section in ("nodes", "synthetic_nodes", "anchor_nodes"):
        for node in data.get(section, ()):
            nid = node.get("id")
            coords = node.get("coordinates")
            if not nid or not isinstance(coords, (list, tuple)) or len(coords) < 2:
                raise ValueError("node record missing id/coordinates")
            index[nid] = [coords[0], coords[1]]
    return index


# --- graph traversal helpers -------------------------------------------------


def _component(adj: dict, start: str) -> set:
    """BFS reachable node set from ``start`` over undirected adjacency."""
    seen = {start}
    queue = [start]
    while queue:
        cur = queue.pop(0)
        for (nb, _eid) in adj.get(cur, ()):
            if nb not in seen:
                seen.add(nb)
                queue.append(nb)
    return seen


def _connected(adj: dict, start: str, goal: str) -> bool:
    return goal in _component(adj, start)


def _biconnected_blocks(adj: dict, nodes: list) -> list[list]:
    """Vertex-biconnected components (edge blocks) via Tarjan edge stack.

    ``adj`` maps node -> list of ``(neighbor, edge_id)`` (deterministically
    pre-sorted). Correctly supports parallel edges: only the exact parent edge
    is skipped, so a second parallel edge to an ancestor is treated as a back
    edge and keeps both parallel edges in the same block. Returns a list of
    blocks, each a list of edge ids.
    """
    disc: dict = {}
    low: dict = {}
    stack: list = []
    blocks: list = []
    time = 0

    def dfs(u: str, parent_edge):
        nonlocal time
        disc[u] = low[u] = time
        time += 1
        for (v, eid) in adj.get(u, ()):
            if eid == parent_edge:
                continue  # skip only the exact tree edge back to the parent
            if v not in disc:
                stack.append(eid)
                dfs(v, eid)
                low[u] = min(low[u], low[v])
                if low[v] >= disc[u]:
                    block = []
                    while True:
                        top = stack.pop()
                        block.append(top)
                        if top == eid:
                            break
                    blocks.append(block)
            elif disc[v] < disc[u]:
                # Back edge to an ancestor: record it on the stack.
                stack.append(eid)
                low[u] = min(low[u], disc[v])
            # else forward/cross edge to a descendant: ignore.

    for node in nodes:
        if node not in disc:
            dfs(node, None)
    return blocks


def _tree_path(tree: dict, start, goal):
    """Unique simple path between two nodes in a tree (BFS), as node list."""
    if start == goal:
        return [start]
    prev = {start: None}
    queue = [start]
    while queue:
        cur = queue.pop(0)
        for nb in tree.get(cur, ()):
            if nb not in prev:
                prev[nb] = cur
                if nb == goal:
                    path = []
                    node = goal
                    while node is not None:
                        path.append(node)
                        node = prev[node]
                    return path[::-1]
                queue.append(nb)
    return None


def _corridor_subgraph(adj: dict, start: str, goal: str,
                       forbidden: set) -> tuple[dict | None, set]:
    """Restrict ``adj`` to the start-goal component after removing forbidden
    nodes. Returns ``(comp_adj, comp_nodes)`` or ``(None, set())`` when start
    and goal are no longer connected."""
    sub = {}
    sub_nodes = set()
    for u, nbrs in adj.items():
        if u in forbidden:
            continue
        for (v, eid) in nbrs:
            if v in forbidden:
                continue
            sub_nodes.add(u)
            sub_nodes.add(v)
            sub.setdefault(u, []).append((v, eid))
    # ``adj`` is already symmetric (both directions present), so ``sub`` is too.
    if start not in sub_nodes or goal not in sub_nodes:
        return None, set()
    comp_nodes = _component(sub, start)
    if goal not in comp_nodes:
        return None, set()
    comp = {}
    for node in comp_nodes:
        comp[node] = [(v, eid) for (v, eid) in sub.get(node, ())
                      if v in comp_nodes]
    return comp, comp_nodes


# --- shortest-path diagnostic (over the corridor only) ----------------------


def _path_lt(weight_a, seq_a, nodes_a, weight_b, seq_b, nodes_b) -> bool:
    """True when path A strictly precedes path B under the deterministic order
    used by ``sections.py`` (mirror of its tie-break)."""
    if weight_b - weight_a > _TIE_EPS:
        return True
    if weight_a - weight_b > _TIE_EPS:
        return False
    return (seq_a, nodes_a) < (seq_b, nodes_b)


def _shortest_in_corridor(corridor_edges: list[dict], start: str,
                          goal: str) -> dict | None:
    """Weighted shortest s-t path restricted to ``corridor_edges`` (diagnostic).

    Returns ``{"edge_ids", "directions", "node_ids", "length_m"}`` or None.
    Simple paths only (no node revisit), so it terminates on zero-weight edges.
    """
    if start == goal:
        return {"edge_ids": [], "directions": [], "node_ids": [start],
                "length_m": 0.0}
    adj: dict = {}
    for e in corridor_edges:
        for a, b, direction in ((e["from"], e["to"], "forward"),
                                (e["to"], e["from"], "reverse")):
            adj.setdefault(a, []).append((b, e["length_m"], e["id"], direction))
    best: dict = {}
    heap: list = [(0.0, (), (start,), start, None, None)]
    while heap:
        weight, seq, nodes, node, eid, direction = heapq.heappop(heap)
        current = best.get(node)
        if current is not None and not _path_lt(
                weight, seq, nodes, current[0], current[1], current[2]):
            continue
        best[node] = (weight, seq, nodes)
        if node == goal:
            continue
        for neighbor, w, nid, direction in adj.get(node, ()):
            if neighbor in nodes:
                continue
            heapq.heappush(heap, (weight + w, seq + (nid,), nodes + (neighbor,),
                                  neighbor, nid, direction))
    result = best.get(goal)
    if result is None:
        return None
    weight, seq, nodes = result
    directions = []
    for i in range(len(nodes) - 1):
        a, b = nodes[i], nodes[i + 1]
        for nb, _, nid, direction in adj.get(a, ()):
            if nb == b and nid == seq[i]:
                directions.append(direction)
                break
        else:
            raise AssertionError("failed to reconstruct direction for path %s"
                                 % (seq,))
    return {"edge_ids": list(seq), "directions": directions,
            "node_ids": list(nodes), "length_m": weight}


# --- corridor construction ---------------------------------------------------


def _anchor_summary(anchor: dict) -> dict:
    return sections._anchor_summary(anchor)


def _empty_counts() -> dict:
    return {
        "edge_ids": [], "traversal_edge_ids": [], "synthetic_join_ids": [],
        "source_edge_ids": [], "node_ids": [],
        "edge_count": 0, "traversal_edge_count": 0, "synthetic_join_count": 0,
        "node_count": 0, "source_edge_count": 0, "cyclomatic_number": 0,
        "excluded_other_anchor_node_ids": [],
        "excluded_other_anchor_node_count": 0,
    }


def _corridor_for_interval(anchors_by_number: dict, eff_by_id: dict,
                           synthetic_ids: set, i: int) -> dict:
    """Compute one section-corridor record for interval ``i -> i+1``."""
    sid = "SEC_%d_%d" % (i, i + 1)
    from_anchor = anchors_by_number[i]
    to_anchor = anchors_by_number[i + 1]
    section = {
        "id": sid,
        "from_temple": i,
        "to_temple": i + 1,
        "anchors": {
            "from": _anchor_summary(from_anchor),
            "to": _anchor_summary(to_anchor),
        },
    }
    if not (from_anchor["usable_for_routing"] and to_anchor["usable_for_routing"]):
        section["status"] = "anchor_review_required"
        section.update(_empty_counts())
        section["shortest"] = None
        return section

    s = from_anchor["anchor_node_id"]
    t = to_anchor["anchor_node_id"]

    # Other usable temple anchor nodes to forbid as internal transit nodes.
    # Never remove the current s/t; if another usable temple shares s or t,
    # record a deterministic shared-anchor diagnostic instead of removing it.
    other_nodes: set = set()
    conflicts: list = []
    for k in range(1, 89):
        if k == i or k == i + 1:
            continue
        anchor = anchors_by_number[k]
        if not anchor["usable_for_routing"]:
            continue
        nid = anchor["anchor_node_id"]
        if nid in (s, t):
            conflicts.append({
                "temple_number": k,
                "anchor_node_id": nid,
                "shares_node_with": s if nid == s else t,
            })
            continue
        other_nodes.add(nid)
    other_nodes = sorted(other_nodes)
    if conflicts:
        conflicts.sort(key=lambda c: c["temple_number"])
        section["shared_anchor_conflicts"] = conflicts

    # s == t is a zero-edge corridor (shortest length 0).
    if s == t:
        section["status"] = "corridor"
        section.update(_empty_counts())
        section["node_ids"] = [s]
        section["node_count"] = 1
        section["shortest"] = {
            "edge_ids": [], "directions": [], "node_ids": [s], "length_m": 0.0,
        }
        section["excluded_other_anchor_node_ids"] = other_nodes
        section["excluded_other_anchor_node_count"] = len(other_nodes)
        return section

    forbidden = set(other_nodes)

    # Full undirected adjacency over the effective graph.
    adj: dict = {}
    for e in eff_by_id.values():
        adj.setdefault(e["from"], []).append((e["to"], e["id"]))
        adj.setdefault(e["to"], []).append((e["from"], e["id"]))
    for key in adj:
        adj[key].sort(key=lambda pair: (pair[0], pair[1]))

    comp_adj, comp_nodes = _corridor_subgraph(adj, s, t, forbidden)
    if comp_adj is None:
        section["status"] = "disconnected"
        section.update(_empty_counts())
        section["shortest"] = None
        section["excluded_other_anchor_node_ids"] = other_nodes
        section["excluded_other_anchor_node_count"] = len(other_nodes)
        return section

    blocks = _biconnected_blocks(comp_adj, sorted(comp_nodes))

    # Vertex -> incident blocks; articulation = in more than one block.
    vblocks: dict = {}
    for idx, block in enumerate(blocks):
        verts = set()
        for eid in block:
            e = eff_by_id[eid]
            verts.add(e["from"])
            verts.add(e["to"])
        for v in verts:
            vblocks.setdefault(v, []).append(idx)
    articulation = {v for v, blist in vblocks.items() if len(blist) > 1}

    # Block-cut tree: articulation vertex nodes linked to their block nodes.
    tree: dict = {}

    def add_tree(a, b):
        tree.setdefault(a, []).append(b)
        tree.setdefault(b, []).append(a)

    for v, blist in vblocks.items():
        if v in articulation:
            for idx in blist:
                add_tree(("artic", v), ("block", idx))

    def home(v):
        if v in articulation:
            return ("artic", v)
        blist = vblocks.get(v, [])
        if not blist:
            return None
        return ("block", blist[0])

    hs, ht = home(s), home(t)
    path = _tree_path(tree, hs, ht) if (hs is not None and ht is not None) else None
    if path is None:
        # Defensive: should be impossible after the connectivity check.
        section["status"] = "disconnected"
        section.update(_empty_counts())
        section["shortest"] = None
        section["excluded_other_anchor_node_ids"] = other_nodes
        section["excluded_other_anchor_node_count"] = len(other_nodes)
        return section

    corridor_block_indices = sorted({val for kind, val in path if kind == "block"})
    corridor_edge_ids = set()
    for idx in corridor_block_indices:
        corridor_edge_ids.update(blocks[idx])
    corridor_edge_ids = sorted(corridor_edge_ids)

    corr_nodes = set()
    for eid in corridor_edge_ids:
        e = eff_by_id[eid]
        corr_nodes.add(e["from"])
        corr_nodes.add(e["to"])
    corr_nodes = sorted(corr_nodes)

    e_count = len(corridor_edge_ids)
    v_count = len(corr_nodes)
    cyclomatic = e_count - v_count + 1
    status = "branched_corridor" if cyclomatic > 0 else "corridor"

    te_ids = sorted(eid for eid in corridor_edge_ids if eid not in synthetic_ids)
    sj_ids = sorted(eid for eid in corridor_edge_ids if eid in synthetic_ids)
    source_edge_ids = sorted({
        eff_by_id[eid]["source_edge_id"] for eid in te_ids
        if eff_by_id[eid]["source_edge_id"]
    })

    corr_edges = [eff_by_id[eid] for eid in corridor_edge_ids]
    shortest = _shortest_in_corridor(corr_edges, s, t)
    if shortest is None:
        raise AssertionError("corridor %s has no shortest path though connected"
                             % sid)

    section.update({
        "status": status,
        "edge_ids": corridor_edge_ids,
        "traversal_edge_ids": te_ids,
        "synthetic_join_ids": sj_ids,
        "source_edge_ids": source_edge_ids,
        "node_ids": corr_nodes,
        "edge_count": e_count,
        "traversal_edge_count": len(te_ids),
        "synthetic_join_count": len(sj_ids),
        "node_count": v_count,
        "source_edge_count": len(source_edge_ids),
        "cyclomatic_number": cyclomatic,
        "excluded_other_anchor_node_ids": other_nodes,
        "excluded_other_anchor_node_count": len(other_nodes),
        "shortest": shortest,
    })
    return section


# --- orchestration -----------------------------------------------------------


def build_corridors(data: dict) -> dict:
    """Build the deterministic section-corridor + edge-classification document.

    ``data`` is the Phase 3 ``anchored_route_graph``. Raises ValueError on
    schema/validation failure.
    """
    validate_anchored_graph(data)

    anchors_by_number = {a["temple_number"]: a for a in data["temple_anchors"]}
    effective = _effective_edges(data)
    eff_by_id = {e["id"]: e for e in effective}
    synthetic_ids = {sj["id"] for sj in data["synthetic_joins"]}

    sections_out: list[dict] = []
    assignment: dict = {}  # edge_id -> set of section ids

    for i in range(1, 88):
        section = _corridor_for_interval(anchors_by_number, eff_by_id,
                                         synthetic_ids, i)
        for eid in section["edge_ids"]:
            assignment.setdefault(eid, set()).add(section["id"])
        sections_out.append(section)

    # Global effective-edge classification.
    edge_classification: list[dict] = []
    for e in sorted(effective, key=lambda x: x["id"]):
        secs = sorted(assignment.get(e["id"], set()))
        count = len(secs)
        if count == 0:
            cls = "unassigned"
        elif count == 1:
            cls = "assigned_once"
        else:
            cls = "assigned_multiple"
        rec = {
            "edge_id": e["id"], "kind": e["kind"],
            "section_ids": secs, "assignment_count": count,
            "classification": cls,
        }
        if e["source_edge_id"]:
            rec["source_edge_id"] = e["source_edge_id"]
        edge_classification.append(rec)

    by_status = {st: 0 for st in _STATUSES}
    for sec in sections_out:
        by_status[sec["status"]] += 1
    cls_counts = {"assigned_once": 0, "assigned_multiple": 0, "unassigned": 0}
    for rec in edge_classification:
        cls_counts[rec["classification"]] += 1
    shared_conflicts_total = sum(
        len(sec.get("shared_anchor_conflicts", ())) for sec in sections_out)

    return {
        "schema_version": 1,
        "kind": "section_corridors",
        "dataset_id": data["dataset_id"],
        "snapshot_sha256": data["snapshot_sha256"],
        "projection": dict(data["projection"]),
        "limitation": data["limitation"],
        "note": "Phase 4b section corridors over the effective undirected graph "
                "of traversal_edges + synthetic_joins only (original source "
                "edges and temple offset distances are never routed). Each "
                "corridor is the exact union of effective edges on some simple "
                "s-t path with every other usable temple anchor node forbidden "
                "as an internal transit node, computed via Tarjan vertex-"
                "biconnected edge blocks + the block-cut tree (no simple-path "
                "enumeration, no 1.15x/length threshold, parallel-edge aware). "
                "Dead ends, lollipop cycles attached through one articulation, "
                "and opposite routes crossing other anchors are excluded. The "
                "shortest field is a diagnostic over the corridor only; it is "
                "NOT the corridor definition.",
        "sections": sections_out,
        "closure_88_1": {"status": "not_requested"},
        "edge_classification": edge_classification,
        "accounting": {
            "sections_total": len(sections_out),
            "by_status": dict(by_status),
            "effective_edges_total": len(effective),
            "traversal_edges_total": len(effective)
                - len(synthetic_ids),
            "synthetic_joins_total": len(synthetic_ids),
            "corridor_assignments_total": sum(len(v) for v in assignment.values()),
            "edge_classification": dict(cls_counts),
            "shared_anchor_conflicts_total": shared_conflicts_total,
            "note": "deterministic output; no timestamp. Intervals 1->2 through "
                    "87->88 (87 sections); closure_88_1 is not requested. Edge "
                    "assignment is not claimed exclusive.",
        },
    }


def build_corridor_geojson(data: dict, result: dict) -> dict:
    """Build the section-corridor-edges GeoJSON FeatureCollection.

    One LineString feature per ``(section_id, effective_edge_id)`` assignment
    with stable feature IDs ``<section_id>:<edge_id>``, plus one feature per
    unassigned edge using ``section_id=null`` / ``classification=unassigned``.
    Synthetic-join geometry is derived from anchored node coordinates. Offset
    lines are never included. Features are sorted by feature id.
    """
    node_coords = _node_coordinate_index(data)
    effective = _effective_edges(data)
    eff_by_id = {e["id"]: e for e in effective}

    assignment: dict = {}
    for rec in result["edge_classification"]:
        assignment[rec["edge_id"]] = rec["section_ids"]
    assigned_ids = {eid for eid, secs in assignment.items() if secs}
    unassigned_ids = {e["id"] for e in effective} - assigned_ids

    def geometry_for(e: dict) -> dict:
        if e["kind"] == "traversal_edge":
            return {"type": "LineString", "coordinates": e["coordinates"]}
        # synthetic join: line between its anchored endpoint node coordinates
        if e["from"] not in node_coords or e["to"] not in node_coords:
            raise ValueError("synthetic join %s endpoint not in node universe"
                             % e["id"])
        return {"type": "LineString",
                "coordinates": [node_coords[e["from"]], node_coords[e["to"]]]}

    features: list[dict] = []
    for sec in result["sections"]:
        sid = sec["id"]
        status = sec["status"]
        for eid in sec["edge_ids"]:
            e = eff_by_id[eid]
            synthetic = e["kind"] == "synthetic_join"
            features.append({
                "type": "Feature",
                "id": "%s:%s" % (sid, eid),
                "geometry": geometry_for(e),
                "properties": {
                    "section_id": sid, "status": status, "edge_id": eid,
                    "edge_kind": e["kind"],
                    "source_edge_id": e["source_edge_id"],
                    "synthetic": synthetic, "applied": synthetic,
                    "assignment_count": len(assignment[eid]),
                },
            })
    for eid in sorted(unassigned_ids):
        e = eff_by_id[eid]
        synthetic = e["kind"] == "synthetic_join"
        features.append({
            "type": "Feature",
            "id": "unassigned:%s" % eid,
            "geometry": geometry_for(e),
            "properties": {
                "section_id": None, "status": None, "edge_id": eid,
                "edge_kind": e["kind"],
                "source_edge_id": e["source_edge_id"],
                "synthetic": synthetic, "applied": synthetic,
                "assignment_count": 0, "classification": "unassigned",
            },
        })
    features.sort(key=lambda f: f["id"])
    return {"type": "FeatureCollection", "features": features}


def run_corridors(input_path: str, output_path: str, geojson_path: str) -> dict:
    """Load the anchored graph, build corridors + GeoJSON in memory, and write
    each file atomically. There is no whole-pack transaction: a filesystem
    failure between the two writes can leave a mixed-version pair."""
    with open(input_path, encoding="utf-8") as stream:
        data = json.load(stream)
    result = build_corridors(data)
    geojson = build_corridor_geojson(data, result)
    normalize.write_atomic(output_path, result)
    normalize.write_atomic(geojson_path, geojson)
    return result