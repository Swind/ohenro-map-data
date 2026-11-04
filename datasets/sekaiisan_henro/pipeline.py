"""Source-local orchestration; all stages run in a fresh directory before publication."""

import fcntl
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import tempfile

from . import anchors, arukihenro_attribution, corridors, graph, normalize, planner, proximity, review, sections, topology

DATASET = Path(__file__).resolve().parent
FILES = {
    "normalized": "sekaiisan-henro-normalized.json",
    "inventory": "sekaiisan-henro-topology-inventory.json",
    "graph": "sekaiisan-henro-graph.json",
    "proximity": "sekaiisan-henro-graph-proximity.json",
    "anchored": "sekaiisan-henro-graph-anchors.json",
    "sections": "sekaiisan-henro-temple-sections.json",
    "corridors": "sekaiisan-henro-section-corridors.json",
    "corridor_geojson": "sekaiisan-henro-section-corridor-edges.geojson",
    "plan": "sekaiisan-henro-plan-graph.json",
}
REVIEW = "sekaiisan-henro-review"
REVIEW_FILES = ("source-edges.geojson", "topology.geojson", "anchors.geojson", "sections.geojson", "review-items.json", "report.json")
ATTRIBUTION = {"source": "sekaiisan-henro-arukihenro-attribution.json",
               "traversal": "sekaiisan-henro-arukihenro-attribution-traversal.json"}


def read(path):
    return json.loads(Path(path).read_text())


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def snapshot_inputs(raw):
    from .__main__ import FILES as sources
    directory, sha = normalize.resolve_snapshot(str(raw), "current")
    directory = Path(directory)
    metadata = read(directory / "metadata.json")
    entries = metadata["files"]
    by_path = {entry["local_path"]: entry for entry in entries}
    if len(entries) != len(sources) or set(by_path) != {path for path, _ in sources}:
        raise ValueError("Snapshot must contain exactly the 12 declared KML files")
    combined = hashlib.sha256()
    for path, _ in sources:
        actual = digest(directory / path)
        if actual != by_path[path]["sha256"]:
            raise ValueError(f"Snapshot hash mismatch: {path}")
        combined.update(path.encode() + b"\0" + bytes.fromhex(actual))
    if combined.hexdigest() != sha or metadata["sha256"] != sha:
        raise ValueError("Snapshot group hash mismatch")
    return {"snapshot_sha256": sha, "metadata_sha256": digest(directory / "metadata.json")}


def settings(bridge_m, reference):
    if not math.isfinite(bridge_m) or bridge_m < 0:
        raise ValueError("--bridge-m must be finite and nonnegative")
    return {"bridge_m": bridge_m, "arukihenro_sha256": digest(reference) if reference else None,
            "shapely_version": importlib.metadata.version("shapely"),
            "source_sha256": {p.name: digest(p) for p in sorted(DATASET.glob("*.py"))}}


def managed_files(with_attribution):
    return sorted([*FILES.values(), *(f"{REVIEW}/{name}" for name in REVIEW_FILES),
                   *(ATTRIBUTION.values() if with_attribution else [])])


def check_outputs(output, report):
    expected = managed_files(report["build_config"]["arukihenro_sha256"] is not None)
    if sorted(report["outputs"]) != expected:
        raise ValueError("Pipeline report has an incomplete output list")
    for name in expected:
        path = output / name
        info = report["outputs"][name]
        if path.stat().st_size != info["size"] or digest(path) != info["sha256"]:
            raise ValueError(f"Output changed or incomplete: {name}")


def current(output, reports, inputs, config):
    try:
        report = read(reports / "pipeline.json")
        if report["inputs"] != inputs or report["build_config"] != config:
            return False
        check_outputs(output, report)
        return True
    except (OSError, ValueError, KeyError, TypeError):
        return False


def validate(output):
    docs = {key: read(output / name) for key, name in FILES.items()}
    norm, inv, exact, prox, anchored, sec, corridor, geo, plan = (docs[key] for key in FILES)
    graph.validate_normalized(norm)
    graph.validate_inventory(inv)
    proximity.validate_exact_graph(exact)
    anchors.validate_proximity_graph(prox)
    sections.validate_anchored_graph(anchored)
    corridors.validate_anchored_graph(anchored)
    for key in ("inventory", "graph", "proximity", "anchored", "sections", "corridors", "plan"):
        for field in ("snapshot_sha256", "dataset_id"):
            if docs[key][field] != norm[field]:
                raise ValueError(f"{key}: {field} mismatch")
    for field in ("nodes", "edges", "route_sources"):
        if exact[field] != prox[field]:
            raise ValueError(f"Proximity changed source {field}")
    for key in ("temples", "toilets", "toilet_defects"):
        if len(norm[key]) != norm["accounting"][key]:
            raise ValueError(f"Normalized accounting mismatch: {key}")
    expected_sections = [f"SEC_{i}_{i+1}" for i in range(1, 88)]
    if [s["id"] for s in corridor["sections"]] != expected_sections:
        raise ValueError("Corridors must cover 87 adjacent temple pairs")
    if geo != corridors.build_corridor_geojson(anchored, corridor):
        raise ValueError("Corridor GeoJSON differs from graph/assignments")
    # Reconstruct the small QA pack to check geometry, lengths, accounting and preservation.
    pack = review.build_review_pack(norm, inv, prox, anchored, sec)
    for name, payload in pack["files"].items():
        if read(output / REVIEW / name) != payload:
            raise ValueError(f"Review pack mismatch: {name}")
    nodes = {n["id"] for n in plan["nodes"]}
    edges = plan["traversal_edges"] + plan["synthetic_joins"]
    if len(nodes) != len(plan["nodes"]) or len({e["id"] for e in edges}) != len(edges):
        raise ValueError("Duplicate plan node/edge IDs")
    if set(plan["edge_geometry"]) != {e["id"] for e in edges}:
        raise ValueError("Plan geometry lookup mismatch")
    for edge in edges:
        weight = edge.get("length_m", edge.get("distance_m"))
        coords = plan["edge_geometry"][edge["id"]]
        if edge["from"] not in nodes or edge["to"] not in nodes or len(coords) < 2:
            raise ValueError("Invalid plan edge endpoints/geometry")
        if weight is None or not math.isfinite(weight) or weight < 0:
            raise ValueError("Invalid plan edge weight")
    return {"snapshot_sha256": norm["snapshot_sha256"], "source": norm["accounting"],
            "sections": sec["accounting"]["by_status"], "corridors": corridor["accounting"]["by_status"],
            "plan_nodes": len(nodes), "plan_edges": len(edges)}


def build(raw, output, reports, bridge_m=5.0, reference=None, force=False):
    inputs, config = snapshot_inputs(raw), settings(bridge_m, reference)
    if not force and current(output, reports, inputs, config):
        return {"status": "unchanged", "snapshot_sha256": inputs["snapshot_sha256"]}
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".sekaiisan-build-", dir=output.parent) as temporary:
        staged = Path(temporary)
        paths = {key: str(staged / name) for key, name in FILES.items()}

        def stage(label, function, *args):
            print(f"==> {label}", flush=True)
            function(*args)

        stage("normalize", normalize.run_normalize, str(raw), inputs["snapshot_sha256"], paths["normalized"])
        stage("topology-inventory", topology.run_inventory, paths["normalized"], paths["inventory"])
        stage("build-graph", graph.run_graph, paths["normalized"], paths["inventory"], paths["graph"])
        stage("apply-proximity", proximity.run_proximity, paths["graph"], paths["inventory"], paths["normalized"], paths["proximity"])
        stage("build-anchors", anchors.run_anchors, paths["proximity"], paths["normalized"], paths["anchored"])
        stage("build-sections", sections.run_sections, paths["anchored"], paths["sections"])
        stage("build-section-corridors", corridors.run_corridors, paths["anchored"], paths["corridors"], paths["corridor_geojson"])
        stage("export-plan-graph", planner.run_export_plan_graph, paths["anchored"], paths["plan"], bridge_m)
        stage("build-review-pack", review.run_review, paths["normalized"], paths["inventory"], paths["proximity"], paths["anchored"], paths["sections"], str(staged / REVIEW))
        if reference:
            for layer, name in ATTRIBUTION.items():
                stage(f"arukihenro-attribution {layer}", arukihenro_attribution.run_attribution,
                      str(reference), paths["graph" if layer == "source" else "anchored"], paths["corridors"], 500.0, str(staged / name), layer)
        summary = validate(staged)
        if snapshot_inputs(raw) != inputs or settings(bridge_m, reference) != config:
            raise ValueError("Inputs or code changed during build; outputs not published")
        names = managed_files(reference is not None)
        report = {"inputs": inputs, "build_config": config, "validation": summary,
                  "outputs": {name: {"size": (staged / name).stat().st_size, "sha256": digest(staged / name)} for name in names}}
        for name in names:
            target = output / name
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged / name, target)
        normalize.write_atomic(str(reports / "pipeline.json"), report)
    return {"status": "published", "files": len(names), **summary}


def execute(args, fetcher):
    raw, output, reports = (Path(p).resolve() for p in (args.data_dir, args.output_dir, args.reports_dir))
    with (DATASET / ".pipeline.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.command == "validate":
            report = read(reports / "pipeline.json")
            check_outputs(output, report)
            summary = validate(output)
            if summary != report["validation"]:
                raise ValueError("Validation summary differs from published report")
            return {"status": "validated", **summary}
        reference = Path(args.arukihenro).resolve() if args.arukihenro else None
        # Check configuration before any network request or source-pointer update.
        settings(args.bridge_m, reference)
        if args.command == "run" and not args.local:
            print("==> checking all 12 official KML files", flush=True)
            print(fetcher(str(raw), args.timeout, validate_snapshot=True), flush=True)
        return build(raw, output, reports, args.bridge_m, reference, args.force)
