"""Refresh Henro Hub's public planner release and all personal-use derivatives."""

import argparse
import fcntl
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from datasets import _pipeline as pipeline
from . import downloader
from .validation import validate_graph, validate_routes

DATASET = Path(__file__).resolve().parent
OUTPUTS = ("henrohub-routes.geojson", "henrohub-plan-graph.json", "shikoku-henrohub.pmtiles")
METADATA = {"name": "Henro Hub Route Network",
            "description": "Offline derivative for personal use of Henro Hub (henro.app) route network",
            "attribution": "Henro Hub / https://henro.app", "dataset_id": "henrohub-routes",
            "source_url": "https://henro.app", "usage": "personal-use"}


def script(name):
    path = DATASET / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def settings():
    return {"code": pipeline.code_hash(DATASET), "proximity_m": 3.0, "join_m": 30.0,
            "tiles": {"min_zoom": 0, "max_zoom": 14, "no_line_simplification": True,
                      "drop_densest": True}, "metadata": METADATA}


def validate_data(output, inputs, source=None):
    routes = pipeline.read_json(output / OUTPUTS[0])
    route_summary = validate_routes(routes)
    if route_summary != inputs["summary"]:
        raise ValueError("Converted routes differ from source accounting")
    if source is not None:
        source_features = pipeline.read_json(source / "planner.geojson")["features"]
        if len(source_features) != len(routes["features"]):
            raise ValueError("Source routes omitted during conversion")
        for original, converted in zip(source_features, routes["features"]):
            props, result = original["properties"], converted["properties"]
            if (converted["geometry"] != original["geometry"] or
                    result["route_id"] != (props.get("route_feature_id") or original.get("id")) or
                    result["route_role"] != props["route_role"] or
                    result["route_class"] != props["effective_route_class"] or
                    result["route_sets"] != props["route_set_ids"] or
                    any(result.get(key) != props.get(key) for key in
                        ("elevation_min_m", "elevation_max_m", "ascent_m", "descent_m", "length_m"))):
                raise ValueError("Converted route changed source geometry/properties")
    graph_summary = validate_graph(pipeline.read_json(output / OUTPUTS[1]), routes)
    metadata = pipeline.validate_pmtiles(output / OUTPUTS[2], ("henrohub_routes",), METADATA)
    layers = metadata["vector_layers"]
    if isinstance(layers, str):
        layers = json.loads(layers)
    if not {"route_id", "route_role", "route_class"}.issubset(layers[0].get("fields", {})):
        raise ValueError("Henro Hub tiles lost required route fields")
    return {"routes": route_summary, "graph": graph_summary}


def validate(output, reports):
    report = pipeline.verify_report(output, reports, OUTPUTS)
    summary = validate_data(output, report["inputs"])
    if summary != report["summary"]:
        raise ValueError("Published report accounting mismatch")
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return summary


def build(snapshot, output, reports, force=False):
    inputs = downloader.verify_snapshot(snapshot)
    config = settings()
    if not force and pipeline.is_current(output, reports, inputs, config, OUTPUTS):
        validate(output, reports)
        print("Inputs, settings and outputs unchanged; skipping build", flush=True)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".henrohub-build-", dir=output.parent) as directory:
        staged = Path(directory)
        script("build-henrohub-routes.py").convert(str(snapshot / "planner.geojson"), str(staged / OUTPUTS[0]))
        script("build-henrohub-plan-graph.py").main([
            "--input", str(staged / OUTPUTS[0]), "--output", str(staged / OUTPUTS[1]),
            "--proximity-m", str(config["proximity_m"]), "--join-m", str(config["join_m"])])
        pipeline.build_pmtiles({"henrohub_routes": staged / OUTPUTS[0]}, staged / OUTPUTS[2],
                               METADATA, **config["tiles"])
        summary = validate_data(staged, inputs, snapshot)
        if downloader.verify_snapshot(snapshot) != inputs or settings() != config:
            raise ValueError("Source or build settings changed during build; not published")
        pipeline.publish(staged, output, reports, OUTPUTS, inputs, config, summary)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", default="run", choices=("run", "fetch", "build", "validate"))
    parser.add_argument("--source", type=Path, help="run/fetch: import an archived native planner GeoJSON instead of the current public release")
    parser.add_argument("--local", action="store_true", help="run: use the selected verified snapshot without network access")
    parser.add_argument("--force", action="store_true", help="run/build: rebuild unchanged outputs")
    parser.add_argument("--raw-dir", type=Path, default=DATASET / "raw")
    parser.add_argument("--output-dir", type=Path, default=DATASET / "output")
    parser.add_argument("--reports-dir", type=Path, default=DATASET / "reports")
    args = parser.parse_args(argv)
    if args.local and args.command != "run":
        parser.error("--local applies only to run")
    if args.force and args.command not in ("run", "build"):
        parser.error("--force applies only to run/build")
    if args.source and (args.command not in ("run", "fetch") or args.local):
        parser.error("--source applies only to online run/fetch")
    raw, output, reports = (path.resolve() for path in (args.raw_dir, args.output_dir, args.reports_dir))
    try:
        with (DATASET / ".pipeline.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if args.command == "validate":
                validate(output, reports)
            else:
                snapshot = (downloader.fetch(raw, args.source) if args.command == "fetch" or
                            (args.command == "run" and not args.local) else downloader.resolve(raw))
                if args.command != "fetch":
                    build(snapshot, output, reports, args.force)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.CalledProcessError,
            downloader.requests.RequestException) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
