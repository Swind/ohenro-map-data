"""Phase 4c: attribute Sekaiisan source edges to temple sections using Arukihenro.

The Arukihenro walking-route maps (output/arukihenro-routes.json) provide a
per-temple-section reference: 86 of the 88 consecutive 札所 intervals are drawn
as Google My Maps lines (40→41 has no KML upstream). We use those lines as an
independent spatial prior to attribute each Sekaiisan source edge (SHE_) to the
nearest temple section, and cross-check the result against the Phase 4b section
corridor attribution.

This is a soft prior, never a hard cut: Arukihenro is an individual's hand-drawn
/ Google-routed map and may follow different roads than the Council's official
引导 route. Distance is measured in the shared local equirectangular projection;
WGS84 lon/lat remains authoritative. Output is byte-deterministic (temp ->
flush -> fsync -> replace); on failure the prior output is untouched.
"""

from __future__ import annotations

import json

from shapely.geometry import LineString, MultiLineString, Point

from sekaiisan_henro import normalize
from sekaiisan_henro.projection import (
    PROJECTION_METADATA,
    limitation_note,
    project_point,
)

ARUKIHENRO_SCHEMA_VERSION = 1


def _project_coords(coords):
    return [project_point(lon, lat) for lon, lat in coords]


def _section_id(from_temple: int, to_temple: int) -> str:
    return "SEC_%d_%d" % (from_temple, to_temple)


def _reference_sections(arukihenro: dict) -> list[dict]:
    """Build one reference section per consecutive 札所 pair with drawn lines.

    Only routes whose ``temple_range`` is exactly ``[n, n+1]`` or the closing
    ``[88, 1]`` are used; combined or single-ended maps are ignored here.
    """
    sections: dict = {}
    for route in arukihenro.get("routes", []):
        temple_range = route.get("temple_range")
        pair = None
        if temple_range == [88, 1]:
            pair = (88, 1)
        elif len(temple_range or []) == 2 and temple_range[1] == temple_range[0] + 1:
            pair = (temple_range[0], temple_range[1])
        if pair is None:
            continue
        entry = sections.setdefault(pair, {"lines": [], "line_count": 0})
        for map_data in route.get("maps", []):
            for line in map_data.get("lines", []):
                coords = line["coordinates"]
                if len(coords) < 2:
                    continue
                entry["lines"].append(_project_coords(coords))
                entry["line_count"] += 1
    result = []
    for (from_temple, to_temple), entry in sorted(sections.items()):
        result.append({
            "id": _section_id(from_temple, to_temple),
            "from_temple": from_temple,
            "to_temple": to_temple,
            "temple_range": [from_temple, to_temple],
            "line_count": entry["line_count"],
            "geometry": MultiLineString(entry["lines"]) if entry["lines"] else None,
        })
    return result


def _edge_geometry(edge: dict):
    return LineString(_project_coords(edge["coordinates"]))


def _attribution_edges(edges: list[dict], references: list[dict],
                       buffer_m: float) -> list[dict]:
    records = []
    for edge in edges:
        edge_line = _edge_geometry(edge)
        candidates = []
        for ref in references:
            if ref["geometry"] is None:
                continue
            distance = edge_line.distance(ref["geometry"])
            candidates.append((ref["id"], distance))
        candidates.sort(key=lambda item: (item[1], item[0]))
        if not candidates:
            records.append({
                "edge_id": edge["id"],
                "status": "unattributed",
                "nearest_section": None,
                "nearest_distance_m": None,
                "within_buffer_sections": [],
            })
            continue
        nearest_id, nearest_distance = candidates[0]
        within = [item for item in candidates if item[1] < buffer_m]
        if not within:
            status = "unattributed"
        elif len(within) >= 2:
            status = "ambiguous"
        else:
            status = "assigned_unique"
        records.append({
            "edge_id": edge["id"],
            "status": status,
            "nearest_section": nearest_id,
            "nearest_distance_m": nearest_distance,
            "within_buffer_sections": [item[0] for item in within],
            "distances_m": {section: distance for section, distance in within},
        })
    return records


def _edge_provenance(edge: dict) -> dict:
    provenance = edge.get("provenance", {})
    result = {"prefecture": provenance.get("prefecture"),
              "source_file": provenance.get("source_file"),
              "source_fid": provenance.get("source_fid"),
              "part": provenance.get("part")}
    return {key: value for key, value in result.items() if value is not None}


def _section_attribution(edges: list[dict], records: list[dict],
                         references: list[dict]) -> list[dict]:
    by_id = {record["edge_id"]: record for record in records}
    length_by_id = {edge["id"]: edge["length_m"] for edge in edges}
    sections = []
    for ref in references:
        section_edges = [
            edge_id for edge_id, record in by_id.items()
            if record["status"] == "assigned_unique"
            and record["nearest_section"] == ref["id"]
        ]
        section_edges.sort()
        sections.append({
            "id": ref["id"],
            "from_temple": ref["from_temple"],
            "to_temple": ref["to_temple"],
            "reference_line_count": ref["line_count"],
            "edge_count": len(section_edges),
            "edge_ids": section_edges,
            "length_m": sum(length_by_id[edge_id] for edge_id in section_edges),
        })
    return sections


def _corridor_crosscheck(corridors: dict | None, by_section: dict,
                         edge_field: str) -> dict:
    if corridors is None:
        return {
            "sections_compared": 0,
            "total_corridor_edges": 0,
            "total_arukihenro_attributed_edges": 0,
            "total_intersection": 0,
            "total_union": 0,
            "jaccard": None,
            "per_section": [],
        }
    per_section = []
    for section in corridors.get("sections", []):
        section_id = section["id"]
        corridor_edges = set(section.get(edge_field, []))
        attributed = set(by_section.get(section_id, {}).get("edge_ids", []))
        intersection = corridor_edges & attributed
        per_section.append({
            "section": section_id,
            "status": section.get("status"),
            "corridor_source_edges": len(corridor_edges),
            "arukihenro_attributed_edges": len(attributed),
            "intersection": len(intersection),
            "corridor_only": len(corridor_edges - attributed),
            "arukihenro_only": len(attributed - corridor_edges),
        })
    per_section.sort(key=lambda item: item["section"])
    compared = [item for item in per_section if item["corridor_source_edges"] > 0]
    total_union = sum(item["corridor_source_edges"] + item["arukihenro_attributed_edges"]
                      - item["intersection"] for item in compared)
    total_intersection = sum(item["intersection"] for item in compared)
    return {
        "sections_compared": len(compared),
        "total_corridor_edges": sum(item["corridor_source_edges"] for item in compared),
        "total_arukihenro_attributed_edges": sum(item["arukihenro_attributed_edges"] for item in compared),
        "total_intersection": total_intersection,
        "total_union": total_union,
        "jaccard": (total_intersection / total_union) if total_union else None,
        "per_section": per_section,
    }


def _validate_arukihenro(data: dict) -> None:
    if not isinstance(data, dict):
        raise ValueError("arukihenro input must be a JSON object")
    if data.get("schema_version") != ARUKIHENRO_SCHEMA_VERSION:
        raise ValueError("unexpected arukihenro schema_version: %r"
                         % data.get("schema_version"))
    if "routes" not in data or not isinstance(data["routes"], list):
        raise ValueError("arukihenro input missing 'routes' list")


def _validate_graph(data: dict, edge_layer: str) -> None:
    if not isinstance(data, dict):
        raise ValueError("graph input must be a JSON object")
    if edge_layer == "traversal":
        expected = "anchored_route_graph"
        required = ("traversal_edges", "snapshot_sha256")
    else:
        expected = "exact_route_graph"
        required = ("edges", "snapshot_sha256")
    if data.get("kind") != expected:
        raise ValueError("graph must be kind=%r for --edge-layer %r, got %r"
                         % (expected, edge_layer, data.get("kind")))
    for key in required:
        if key not in data:
            raise ValueError("graph missing required key: %s" % key)


def build_attribution(arukihenro: dict, graph: dict,
                      corridors: dict | None, buffer_m: float,
                      edge_layer: str = "source") -> dict:
    """Build the deterministic Arukihenro attribution document.

    ``edge_layer`` is ``"source"`` (attribute the evidence-level SHE_ edges
    from an exact_route_graph) or ``"traversal"`` (attribute the temple-anchored
    STE_ traversal edges from an anchored_route_graph). The corridor cross-check
    compares against the corresponding corridor edge field.
    """
    if edge_layer not in ("source", "traversal"):
        raise ValueError("edge-layer must be 'source' or 'traversal'")
    if buffer_m <= 0:
        raise ValueError("buffer-m must be positive")
    _validate_arukihenro(arukihenro)
    _validate_graph(graph, edge_layer)

    if edge_layer == "traversal":
        edges = sorted(graph["traversal_edges"], key=lambda edge: edge["id"])
        corridor_edge_field = "traversal_edge_ids"
    else:
        edges = sorted(graph["edges"], key=lambda edge: edge["id"])
        corridor_edge_field = "source_edge_ids"
    references = _reference_sections(arukihenro)
    records = _attribution_edges(edges, references, buffer_m)

    by_id = {record["edge_id"]: record for record in records}
    section_attribution = _section_attribution(edges, records, references)
    by_section = {section["id"]: section for section in section_attribution}
    crosscheck = _corridor_crosscheck(corridors, by_section, corridor_edge_field)

    provenance_by_id = {edge["id"]: _edge_provenance(edge) for edge in edges}
    edge_records = []
    for record in records:
        edge_records.append({
            "edge_id": record["edge_id"],
            **provenance_by_id[record["edge_id"]],
            "status": record["status"],
            "nearest_section": record["nearest_section"],
            "nearest_distance_m": record["nearest_distance_m"],
            "within_buffer_sections": record["within_buffer_sections"],
            "distances_m": record.get("distances_m", {}),
        })

    from collections import Counter
    status_counts = Counter(record["status"] for record in records)
    distances = [record["nearest_distance_m"] for record in records
                 if record["nearest_distance_m"] is not None]
    distances.sort()
    if distances:
        def percentile(p):
            index = int(p * (len(distances) - 1))
            return distances[index]
        distance_stats = {
            "median_m": percentile(0.5),
            "p90_m": percentile(0.9),
            "p95_m": percentile(0.95),
            "min_m": distances[0],
            "max_m": distances[-1],
        }
    else:
        distance_stats = {}

    reference_count = len(references)
    reference_count_with_lines = sum(1 for ref in references if ref["line_count"] > 0)
    edges_with_attribution = sum(1 for record in records
                                 if record["status"] == "assigned_unique")
    accounting = {
        "edge_layer": edge_layer,
        "buffer_m": buffer_m,
        "reference_sections": reference_count,
        "reference_sections_with_lines": reference_count_with_lines,
        "reference_sections_missing": reference_count - reference_count_with_lines,
        "edges_total": len(records),
        "by_status": dict(sorted(status_counts.items())),
        "edges_with_attribution": edges_with_attribution,
        "attribution_ratio": edges_with_attribution / len(records) if records else None,
        "distance_stats": distance_stats,
        "corridor_crosscheck": {
            "sections_compared": crosscheck["sections_compared"],
            "total_corridor_edges": crosscheck["total_corridor_edges"],
            "total_arukihenro_attributed_edges": crosscheck["total_arukihenro_attributed_edges"],
            "total_intersection": crosscheck["total_intersection"],
            "jaccard": crosscheck["jaccard"],
        },
        "note": "Arukihenro is an independent spatial prior, not an official "
                "route; edges near a missing reference section (40->41) are "
                "attributed to the nearest existing section.",
    }
    return {
        "schema_version": 1,
        "kind": "arukihenro_attribution",
        "dataset_id": graph["dataset_id"],
        "snapshot_sha256": graph["snapshot_sha256"],
        "projection": dict(PROJECTION_METADATA),
        "limitation": limitation_note(),
        "note": "per-%s-edge attribution to the nearest Arukihenro temple "
                "section (buffer = %.1f m). Soft prior only; see limitation."
                % (edge_layer, buffer_m),
        "references": [{
            "id": ref["id"],
            "from_temple": ref["from_temple"],
            "to_temple": ref["to_temple"],
            "temple_range": ref["temple_range"],
            "line_count": ref["line_count"],
        } for ref in references],
        "edges": edge_records,
        "section_attribution": section_attribution,
        "corridor_crosscheck": crosscheck,
        "accounting": accounting,
    }


def run_attribution(arukihenro_path: str, graph_path: str,
                    corridors_path: str | None, buffer_m: float,
                    output_path: str, edge_layer: str = "source") -> dict:
    """Load inputs, build the attribution, write atomically."""
    with open(arukihenro_path, encoding="utf-8") as stream:
        arukihenro = json.load(stream)
    with open(graph_path, encoding="utf-8") as stream:
        graph = json.load(stream)
    corridors = None
    if corridors_path:
        with open(corridors_path, encoding="utf-8") as stream:
            corridors = json.load(stream)
    result = build_attribution(arukihenro, graph, corridors, buffer_m, edge_layer)
    normalize.write_atomic(output_path, result)
    return result