"""Update OHenro 88's static app assets, route references and browser PlanGraph.

Usage: python3 -m datasets.ohenro88 [run|fetch|build|validate]
Offline: run --local, or run --archive /path/to/authentic.apk (also .xapk).
The app's bundled geometry is not official guidance or a navigation guarantee;
source licensing is unchanged. No APK code is executed and no Blutter is needed.
"""
import argparse
from collections import Counter
import fcntl
import importlib.util
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

from datasets import _pipeline as pipeline
from datasets.henro_helper import downloader as apk
from . import downloader
from .reference import build_reference as reference

DATASET = Path(__file__).resolve().parent
FILES = ("ohenro88-routes.geojson", "ohenro88-sections.json", "ohenro88-plan-graph.json")
_spec = importlib.util.spec_from_file_location("ohenro88_plan_graph", DATASET / "scripts/build-ohenro88-plan-graph.py")
graph_builder = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(graph_builder)


def config():
    return {"source_sha256": pipeline.code_hash(DATASET),
            "apk_reader_sha256": pipeline.digest(apk.__file__),
            "proximity_m": 3.0, "join_m": 90.0}


def source(snapshot):
    metadata = downloader.validate_snapshot(snapshot, snapshot.name)
    assets = {name: pipeline.read_json(snapshot / "data" / name) for name in downloader.ASSETS}
    downloader.validate_assets(assets)
    return metadata, assets


def validate_graph(graph, features):
    if graph.get("schema_version") != 2 or graph.get("kind") != "plan_graph" or graph.get("dataset_id") != "ohenro88":
        raise ValueError("Invalid OHenro 88 PlanGraph identity/schema")
    nodes = {node["id"]: node for node in graph["nodes"]}
    if not nodes or len(nodes) != len(graph["nodes"]):
        raise ValueError("Empty or duplicate graph nodes")
    for node in nodes.values():
        downloader.validate_geometry({"type": "Point", "coordinates": [node["lon"], node["lat"]]})
    traversal, joins = graph["traversal_edges"], graph["synthetic_joins"]
    edges = traversal + joins
    ids = [edge["id"] for edge in edges]
    if not traversal or len(ids) != len(set(ids)) or set(graph["edge_geometry"]) != set(ids):
        raise ValueError("Missing/duplicate graph edge geometry")
    parent = {node: node for node in nodes}
    referenced = set()

    def root(node):
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for index, edge in enumerate(edges):
        is_join = index >= len(traversal)
        a, b = edge["from"], edge["to"]
        length = edge["distance_m" if is_join else "length_m"]
        if (a not in nodes or b not in nodes or a == b or isinstance(length, bool)
                or not isinstance(length, (int, float)) or not math.isfinite(length)
                or length < 0 or (not is_join and length == 0) or (is_join and length > 90.0)):
            raise ValueError("Invalid graph topology/weight")
        coordinates = graph["edge_geometry"][edge["id"]]
        downloader.validate_geometry({"type": "LineString", "coordinates": coordinates})
        # A proximity-merged node may differ from the digitised edge endpoint.
        # Edge weight must still describe that edge's actual metric polyline.
        metric = [graph_builder.project(*point[:2]) for point in coordinates]
        measured = sum(math.dist(a, b) for a, b in zip(metric, metric[1:]))
        if not is_join and not math.isclose(length, measured, rel_tol=0.002, abs_tol=0.1):
            raise ValueError("Graph weight differs from geometry")
        referenced.update((a, b))
        parent[root(a)] = root(b)
    if referenced != set(nodes):
        raise ValueError("Graph contains orphan nodes")
    components = Counter(root(node) for node in nodes)
    accounting = graph["accounting"]
    expected = {"segments": len(graph_builder._line_parts(features)), "nodes": len(nodes),
                "edges": len(traversal), "synthetic_joins": len(joins),
                "geometry_points": sum(map(len, graph["edge_geometry"].values())),
                "components": len(components), "largest_component_nodes": max(components.values())}
    if accounting != expected:
        raise ValueError("Graph accounting differs from topology/geometry")
    return expected


def validate_data(output, snapshot):
    metadata, assets = source(snapshot)
    expected_routes, expected_sections = reference.build_data(assets["trails_all.geojson"], assets["merged.json"], metadata)
    routes = pipeline.read_json(output / FILES[0])
    sections = pipeline.read_json(output / FILES[1])
    if routes != expected_routes or sections != expected_sections:
        raise ValueError("Published routes/sections differ from source assets and provenance")
    features = routes["features"]
    ids = [feature["properties"]["route_id"] for feature in features]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate output route/point ID")
    for feature in features:
        downloader.validate_geometry(feature["geometry"])
    if ([s["id"] for s in sections["sections"]] != [f"SEC_{i}_{i+1}" for i in range(1, 88)]
            or sections["closure_88_1"]["id"] != "SEC_88_1" or not sections["closure_88_1"]["geometry"]):
        raise ValueError("Incomplete adjacent sections/closure")
    graph = validate_graph(pipeline.read_json(output / FILES[2]), features)
    return {"package_name": metadata["package_name"], "version_name": metadata["version_name"],
            "version_code": metadata["version_code"], "source_features": downloader.validate_assets(assets),
            "routes": dict(Counter(f["properties"]["kind"] for f in features)),
            "sections": len(sections["sections"]), "closure_sections": 1, "graph": graph}


def validate(output, reports, snapshot):
    report = pipeline.verify_report(output, reports, FILES)
    metadata, _ = source(snapshot)
    if report["inputs"] != metadata:
        raise ValueError("Published input report differs from selected source snapshot")
    summary = validate_data(output, snapshot)
    if summary != report["summary"]:
        raise ValueError("Published summary differs from output accounting")
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return summary


def build(snapshot, output, reports, force=False):
    metadata, assets = source(snapshot)
    settings = config()
    if not force and pipeline.is_current(output, reports, metadata, settings, FILES):
        validate(output, reports, snapshot)
        print("Inputs, settings and outputs unchanged; skipping build", flush=True)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".ohenro88-build-", dir=output.parent) as directory:
        staged = Path(directory)
        routes, sections = reference.build_data(assets["trails_all.geojson"], assets["merged.json"], metadata)
        pipeline.atomic_json(staged / FILES[0], routes)
        pipeline.atomic_json(staged / FILES[1], sections)
        graph = graph_builder._build(graph_builder._line_parts(routes["features"]), settings["join_m"], settings["proximity_m"])
        pipeline.atomic_json(staged / FILES[2], graph)
        summary = validate_data(staged, snapshot)
        if config() != settings or source(snapshot)[0] != metadata:
            raise ValueError("Source or build code changed during build; not published")
        pipeline.publish(staged, output, reports, FILES, metadata, settings, summary)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", default="run", choices=("run", "fetch", "build", "validate"))
    parser.add_argument("--local", action="store_true", help="run: use validated raw/current.json without network")
    parser.add_argument("--archive", type=Path, help="run/fetch: import a real local APK/XAPK without network")
    parser.add_argument("--force", action="store_true", help="run/build: rebuild unchanged source")
    parser.add_argument("--raw-dir", type=Path, default=DATASET / "raw")
    parser.add_argument("--output-dir", type=Path, default=DATASET / "output")
    parser.add_argument("--reports-dir", type=Path, default=DATASET / "reports")
    args = parser.parse_args(argv)
    if args.local and (args.command != "run" or args.archive):
        parser.error("--local applies only to run and cannot be combined with --archive")
    if args.archive and args.command not in ("run", "fetch"):
        parser.error("--archive applies only to run/fetch")
    if args.force and args.command not in ("run", "build"):
        parser.error("--force applies only to run/build")
    raw, output, reports = (path.resolve() for path in (args.raw_dir, args.output_dir, args.reports_dir))
    try:
        with (DATASET / ".pipeline.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if args.command == "validate":
                validate(output, reports, downloader.resolve(raw))
            else:
                snapshot = (downloader.fetch(raw, args.archive.resolve() if args.archive else None)
                            if args.command == "fetch" or (args.command == "run" and not args.local)
                            else downloader.resolve(raw))
                if args.command != "fetch":
                    build(snapshot, output, reports, args.force)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, zipfile.BadZipFile,
            subprocess.CalledProcessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
