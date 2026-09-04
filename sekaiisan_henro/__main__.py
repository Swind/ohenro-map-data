"""Download an immutable snapshot of the Council's 12 KML source files."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ElementTree
from datetime import UTC, datetime

from sekaiisan_henro import anchors, arukihenro_attribution, corridors, graph, normalize, planner, proximity, review, sections, topology

SOURCE_PAGE_URL = "https://88sekaiisan.org/restroommap/"
DATA_URL = "https://88sekaiisan.org/map/data/"
USER_AGENT = "ohenro-map-data/1.0 (source archive)"
FILES = (
    ("routes/tokushima.kml", "tokushimaken_annairu-to36.kml"),
    ("routes/kochi.kml", "koutiken_annairu-to39.kml"),
    ("routes/ehime.kml", "ehimeken_annairu-to38.kml"),
    ("routes/kagawa.kml", "kagawaken_annairu-to37.kml"),
    ("temples/1-23.kml", "1ban23ban.kml"),
    ("temples/24-39.kml", "24ban39ban.kml"),
    ("temples/40-65.kml", "40ban65ban.kml"),
    ("temples/66-88.kml", "66ban88ban.kml"),
    ("toilets/tokushima.kml", "tokushimaken.kml"),
    ("toilets/kochi.kml", "koutiken.kml"),
    ("toilets/ehime.kml", "ehimeken.kml"),
    ("toilets/kagawa.kml", "kagawaken.kml"),
)


def _write(path: str, body: bytes) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "wb") as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _validate_kml(body: bytes) -> None:
    if not body:
        raise ValueError("response is empty")
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as error:
        raise ValueError("response is not valid KML XML: %s" % error) from error
    if root.tag.rsplit("}", 1)[-1] != "kml":
        raise ValueError("response root is not KML")


def _download(url: str, timeout: int) -> tuple[str, bytes]:
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                if response.status != 200:
                    raise ValueError("GET returned HTTP %s" % response.status)
                return response.headers.get("Content-Type", ""), response.read()
        except (urllib.error.URLError, TimeoutError) as error:
            if attempt == 2:
                raise ValueError("GET failed: %s" % error) from error
            time.sleep(attempt + 1)
    raise AssertionError("unreachable")


def fetch(data_dir: str, timeout: int) -> dict:
    """Fetch every source first, so a failed group never changes current.json."""
    downloaded = []
    digest = hashlib.sha256()
    for local_path, source_file in FILES:
        url = DATA_URL + source_file
        content_type, body = _download(url, timeout)
        _validate_kml(body)
        file_hash = hashlib.sha256(body).hexdigest()
        digest.update(local_path.encode() + b"\0" + bytes.fromhex(file_hash))
        downloaded.append({
            "local_path": local_path,
            "source_file": source_file,
            "url": url,
            "content_type": content_type,
            "size": len(body),
            "sha256": file_hash,
            "body": body,
        })

    snapshot_hash = digest.hexdigest()
    snapshot_dir = os.path.join(data_dir, "snapshots", snapshot_hash)
    is_new = not os.path.exists(os.path.join(snapshot_dir, "metadata.json"))
    checked_at = datetime.now(UTC).isoformat()
    if is_new:
        for file in downloaded:
            _write(os.path.join(snapshot_dir, file["local_path"]), file.pop("body"))
        metadata = {
            "schema_version": 1,
            "dataset_id": "88sekaiisan-henro",
            "organization": "四国遍路世界遺産登録推進協議会",
            "source_page_url": SOURCE_PAGE_URL,
            "retrieved_at": checked_at,
            "sha256": snapshot_hash,
            "files": downloaded,
        }
        _write(os.path.join(snapshot_dir, "metadata.json"), json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True).encode() + b"\n")
    _write(os.path.join(data_dir, "current.json"), json.dumps({
        "schema_version": 1,
        "sha256": snapshot_hash,
        "last_checked_at": checked_at,
    }, ensure_ascii=False, indent=2, sort_keys=True).encode() + b"\n")
    return {"new_snapshot": is_new, "sha256": snapshot_hash, "files": len(downloaded)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="source/88sekaiisan-henro")
    parser.add_argument("--timeout", type=int, default=30)
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("fetch", help="download an immutable snapshot (same as no command)")
    normalize_parser = sub.add_parser("normalize", help="Phase 1 normalization to normalized.json")
    normalize_parser.add_argument("--snapshot", default="current")
    normalize_parser.add_argument("--data-dir", default="source/88sekaiisan-henro")
    normalize_parser.add_argument("--output", default="output/sekaiisan-henro-normalized.json")
    inventory_parser = sub.add_parser(
        "topology-inventory", help="Phase 2A read-only diagnostic topology inventory")
    inventory_parser.add_argument("--input", default="output/sekaiisan-henro-normalized.json")
    inventory_parser.add_argument("--output", default="output/sekaiisan-henro-topology-inventory.json")
    graph_parser = sub.add_parser(
        "build-graph", help="Phase 2B exact-only route graph construction")
    graph_parser.add_argument("--input", default="output/sekaiisan-henro-normalized.json")
    graph_parser.add_argument("--inventory", default="output/sekaiisan-henro-topology-inventory.json")
    graph_parser.add_argument("--output", default="output/sekaiisan-henro-graph.json")
    proximity_parser = sub.add_parser(
        "apply-proximity", help="Phase 2C conservative proximity connections (new graph)")
    proximity_parser.add_argument("--graph", default="output/sekaiisan-henro-graph.json")
    proximity_parser.add_argument("--inventory", default="output/sekaiisan-henro-topology-inventory.json")
    proximity_parser.add_argument("--input", default="output/sekaiisan-henro-normalized.json")
    proximity_parser.add_argument("--output", default="output/sekaiisan-henro-graph-proximity.json")
    anchors_parser = sub.add_parser(
        "build-anchors", help="Phase 3 temple anchors + derived traversal segmentation")
    anchors_parser.add_argument("--graph", default="output/sekaiisan-henro-graph-proximity.json")
    anchors_parser.add_argument("--input", default="output/sekaiisan-henro-normalized.json")
    anchors_parser.add_argument("--output", default="output/sekaiisan-henro-graph-anchors.json")
    sections_parser = sub.add_parser(
        "build-sections", help="Phase 4 temple interval candidate inference")
    sections_parser.add_argument("--input", default="output/sekaiisan-henro-graph-anchors.json")
    sections_parser.add_argument("--output", default="output/sekaiisan-henro-temple-sections.json")
    corridors_parser = sub.add_parser(
        "build-section-corridors", help="Phase 4b parallel section-corridor classification")
    corridors_parser.add_argument("--input", default="output/sekaiisan-henro-graph-anchors.json")
    corridors_parser.add_argument("--output", default="output/sekaiisan-henro-section-corridors.json")
    corridors_parser.add_argument("--geojson", default="output/sekaiisan-henro-section-corridor-edges.geojson")
    review_parser = sub.add_parser(
        "build-review-pack", help="QGIS review-pack / report exporter")
    review_parser.add_argument("--normalized", default="output/sekaiisan-henro-normalized.json")
    review_parser.add_argument("--inventory", default="output/sekaiisan-henro-topology-inventory.json")
    review_parser.add_argument("--proximity", default="output/sekaiisan-henro-graph-proximity.json")
    review_parser.add_argument("--anchored", default="output/sekaiisan-henro-graph-anchors.json")
    review_parser.add_argument("--sections", default="output/sekaiisan-henro-temple-sections.json")
    review_parser.add_argument("--output-dir", default="output/sekaiisan-henro-review")
    attribution_parser = sub.add_parser(
        "arukihenro-attribution", help="Phase 4c attribute route edges to temple sections "
                                       "using the Arukihenro per-section reference maps")
    attribution_parser.add_argument("--arukihenro", default="output/arukihenro-routes.json")
    attribution_parser.add_argument("--input", default=None,
                                    help="graph input; defaults to the graph for the chosen edge layer")
    attribution_parser.add_argument("--edge-layer", choices=("source", "traversal"), default="source",
                                    help="attribute source (SHE_) or traversal (STE_) edges")
    attribution_parser.add_argument("--corridors", default="output/sekaiisan-henro-section-corridors.json")
    attribution_parser.add_argument("--buffer-m", type=float, default=500.0)
    attribution_parser.add_argument("--output", default=None,
                                    help="output path; defaults per edge layer")
    plan_parser = sub.add_parser(
        "plan", help="point-to-point day planning on the effective graph")
    plan_parser.add_argument("--input", default="output/sekaiisan-henro-graph-anchors.json")
    plan_parser.add_argument("--points", nargs="+", required=True,
                             help="2+ 'lon,lat' pairs: start [waypoints...] end")
    plan_parser.add_argument("--elevation-db", default="output/shikoku-elevation.sqlite")
    plan_parser.add_argument("--elevation-bin", default=None,
                             help="gsi-dem query-db binary (fallback when zstandard missing)")
    plan_parser.add_argument("--sample-interval-m", type=float, default=200.0)
    plan_parser.add_argument("--snap-max-m", type=float, default=500.0)
    plan_parser.add_argument("--output", default="output/sekaiisan-henro-plan.json")
    plan_parser.add_argument("--geojson", default="output/sekaiisan-henro-plan.geojson")
    export_parser = sub.add_parser(
        "export-plan-graph",
        help="export the compact browser-routing graph for the map preview")
    export_parser.add_argument("--input", default="output/sekaiisan-henro-graph-anchors.json")
    export_parser.add_argument("--output", default="output/sekaiisan-henro-plan-graph.json")
    return parser


def dispatch(args: argparse.Namespace) -> dict:
    """Route a parsed command to its implementation (fetch by default)."""
    if args.command == "normalize":
        return normalize.run_normalize(args.data_dir, args.snapshot, args.output)
    if args.command == "topology-inventory":
        return topology.run_inventory(args.input, args.output)
    if args.command == "build-graph":
        return graph.run_graph(args.input, args.inventory, args.output)
    if args.command == "apply-proximity":
        return proximity.run_proximity(args.graph, args.inventory, args.input, args.output)
    if args.command == "build-anchors":
        return anchors.run_anchors(args.graph, args.input, args.output)
    if args.command == "build-sections":
        return sections.run_sections(args.input, args.output)
    if args.command == "build-section-corridors":
        return corridors.run_corridors(args.input, args.output, args.geojson)
    if args.command == "build-review-pack":
        return review.run_review(args.normalized, args.inventory, args.proximity,
                                 args.anchored, args.sections, args.output_dir)
    if args.command == "arukihenro-attribution":
        corridors_path = args.corridors if args.corridors else None
        if args.input is None:
            args.input = ("output/sekaiisan-henro-graph-anchors.json"
                          if args.edge_layer == "traversal"
                          else "output/sekaiisan-henro-graph.json")
        if args.output is None:
            args.output = ("output/sekaiisan-henro-arukihenro-attribution-traversal.json"
                           if args.edge_layer == "traversal"
                           else "output/sekaiisan-henro-arukihenro-attribution.json")
        return arukihenro_attribution.run_attribution(
            args.arukihenro, args.input, corridors_path, args.buffer_m,
            args.output, args.edge_layer)
    if args.command == "plan":
        points = [tuple(float(part) for part in pair.split(","))
                  for pair in args.points]
        for pair in points:
            if len(pair) != 2:
                raise ValueError("each --points entry must be 'lon,lat': %r" % (pair,))
        return planner.run_plan(
            args.input, points, args.elevation_db, args.elevation_bin,
            args.sample_interval_m, args.snap_max_m, args.output, args.geojson)
    if args.command == "export-plan-graph":
        return planner.run_export_plan_graph(args.input, args.output)
    return fetch(args.data_dir, args.timeout)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = dispatch(args)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    if args.command == "normalize":
        print("normalized: snapshot=%s temples=%d output=%s" % (
            result["snapshot_sha256"], result["accounting"]["temples"], args.output))
    elif args.command == "topology-inventory":
        print("topology-inventory: routes=%d output=%s" % (
            result["analysis_accounting"]["route_records"], args.output))
    elif args.command == "build-graph":
        acct = result["accounting"]
        print("build-graph: nodes=%d edges=%d components=%d isolated=%d "
              "exact_t=%d len_err=%.3e output=%s" % (
                  acct["nodes"], acct["edges"], acct["components"],
                  acct["isolated_components"],
                  acct["exact_connections_consumed"]["endpoint_touches_applied"],
                  acct["lengths"]["max_absolute_error_m"], args.output))
    elif args.command == "apply-proximity":
        acct = result["accounting"]
        prox = acct["proximity"]
        applied = prox["endpoint_clusters_applied"] + prox["endpoint_to_line_applied"]
        print("apply-proximity: synthetic_joins=%d synthetic_nodes=%d "
              "components %d->%d applied=%d rejected=%d gaps=%d crossings=%d "
              "output=%s" % (
                  acct["synthetic_joins"], acct["synthetic_nodes"],
                  acct["components_before"], acct["components_after"], applied,
                  prox["endpoint_clusters_rejected_ambiguous"]
                  + prox["endpoint_to_line_rejected_competing"],
                  prox["gaps_5_20m_reported"],
                  prox["ambiguous_crossings_total"], args.output))
    elif args.command == "build-anchors":
        acct = result["accounting"]
        print("build-anchors: temple_anchors=%d usable=%d review=%d "
              "traversal_edges=%d traversal_nodes=%d components %d->%d "
              "len_err=%.3e output=%s" % (
                  acct["temple_anchors"], acct["anchors_usable"],
                  acct["anchors_review_required"], acct["traversal_edges"],
                  acct["traversal_nodes"], acct["components_before"],
                  acct["components_after"],
                  acct["traversal_lengths"]["max_absolute_error_m"], args.output))
    elif args.command == "build-sections":
        acct = result["accounting"]
        print("build-sections: sections=%d candidate=%d ambiguous=%d "
              "disconnected=%d review=%d synthetic_paths=%d output=%s" % (
                  acct["sections_total"], acct["by_status"]["candidate"],
                  acct["by_status"]["ambiguous"],
                  acct["by_status"]["disconnected"],
                  acct["by_status"]["anchor_review_required"],
                  acct["paths_using_synthetic_joins"], args.output))
    elif args.command == "build-section-corridors":
        acct = result["accounting"]
        print("build-section-corridors: sections=%d corridor=%d branched=%d "
              "disconnected=%d review=%d edges=%d once=%d multiple=%d "
              "unassigned=%d shared_conflicts=%d output=%s geojson=%s" % (
                  acct["sections_total"], acct["by_status"]["corridor"],
                  acct["by_status"]["branched_corridor"],
                  acct["by_status"]["disconnected"],
                  acct["by_status"]["anchor_review_required"],
                  acct["effective_edges_total"],
                  acct["edge_classification"]["assigned_once"],
                  acct["edge_classification"]["assigned_multiple"],
                  acct["edge_classification"]["unassigned"],
                  acct["shared_anchor_conflicts_total"],
                  args.output, args.geojson))
    elif args.command == "build-review-pack":
        oc = result["output_counts"]
        pc = result["review_priority_counts"]["total"]
        unc = result["unresolved_focal_counts"]
        print("build-review-pack: source_edges=%d topology=%d anchors=%d "
              "sections=%d review_items=%d P0=%d P1=%d P2=%d "
              "review_anchors=%d disconnected=%d ambiguous=%d output_dir=%s" % (
                  oc["source_edges_features"], oc["topology_features"],
                  oc["anchors_features"], oc["sections_features"],
                  oc["review_items_total"], pc["P0"], pc["P1"], pc["P2"],
                  unc["review_required_anchors"], unc["disconnected_sections"],
                  unc["ambiguous_sections"], args.output_dir))
    elif args.command == "arukihenro-attribution":
        acct = result["accounting"]
        cc = acct["corridor_crosscheck"]
        print("arukihenro-attribution: layer=%s refs=%d missing=%d edges=%d "
              "assigned=%d ambiguous=%d unattributed=%d corridor_compared=%d "
              "jaccard=%s output=%s" % (
                  acct["edge_layer"],
                  acct["reference_sections_with_lines"],
                  acct["reference_sections_missing"],
                  acct["edges_total"],
                  acct["by_status"].get("assigned_unique", 0),
                  acct["by_status"].get("ambiguous", 0),
                  acct["by_status"].get("unattributed", 0),
                  cc["sections_compared"],
                  ("%.3f" % cc["jaccard"]) if cc["jaccard"] is not None else "n/a",
                  args.output))
    elif args.command == "plan":
        path = result["path"]
        elev = result["elevation"]
        time_est = result.get("time_estimate") or {}
        print("plan: status=%s length_km=%s gain_m=%s loss_m=%s "
              "min_m=%s max_m=%s naismith_h=%s output=%s" % (
                  path["status"], path.get("length_km"),
                  elev.get("gain_m"), elev.get("loss_m"),
                  elev.get("min_m"), elev.get("max_m"),
                  time_est.get("hours_naismith"), args.output))
    elif args.command == "export-plan-graph":
        print("export-plan-graph: nodes=%d traversal_edges=%d synthetic_joins=%d "
              "output=%s" % (len(result["nodes"]), len(result["traversal_edges"]),
                             len(result["synthetic_joins"]), args.output))
    else:
        print("archive: files=%d sha256=%s new_snapshot=%s" % (result["files"], result["sha256"], result["new_snapshot"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
