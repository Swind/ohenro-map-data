"""Refresh, stage, validate and publish the consolidated information POIs."""

from __future__ import annotations

import argparse
from collections import Counter
import fcntl
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from datasets import _pipeline as common

DATASET = Path(__file__).resolve().parent
DATASETS = DATASET.parent
BUILDER = DATASET / "scripts/build-info-pois.py"
GEOJSON = "pois.geojson"
REPORT = "pois-report.json"
TILES = "shikoku-info-pois.pmtiles"
OUTPUTS = (GEOJSON, REPORT, TILES)
SOURCES = {
    "temples": "seichijunrei/output/temples.geojson",
    "sekaiisan": "sekaiisan_henro/output/sekaiisan-henro-normalized.json",
    "mizutani": "mizutani_henro_map/output/mizutani-henro-pois.geojson",
    "nature_trail": "shikoku_nature_trail/output/shikoku-nature-trail-pois.geojson",
    "arukihenro": "arukihenro_routes/output/arukihenro-routes.json",
}
UPSTREAM = ("seichijunrei", "sekaiisan_henro", "mizutani_henro_map",
            "shikoku_nature_trail", "arukihenro_routes")
FIELDS = {"poi_id", "category", "source", "source_category", "name"}


def builder():
    spec = importlib.util.spec_from_file_location("info_pois_builder", BUILDER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def settings(image, skip_osm):
    return {"code": common.code_hash(DATASET), "image": image,
            "min_zoom": 0, "max_zoom": 14, "drop_densest": True,
            "no_line_simplification": True, "skip_osm": skip_osm}


def source_inputs(datasets_dir, basemap=None):
    datasets_dir = Path(datasets_dir).resolve()
    return {"datasets_dir": str(datasets_dir),
            "sources": {name: common.digest(datasets_dir / relative)
                        for name, relative in SOURCES.items()},
            "osm": ({"path": str(Path(basemap).resolve()), "sha256": common.digest(basemap)}
                    if basemap is not None else None)}


def point(geometry, label):
    if not isinstance(geometry, dict) or geometry.get("type") != "Point":
        raise ValueError(f"{label}: expected Point geometry")
    coordinates = geometry.get("coordinates")
    if (not isinstance(coordinates, list) or len(coordinates) not in (2, 3)
            or any(isinstance(value, bool) or not isinstance(value, (int, float))
                   or not math.isfinite(value) for value in coordinates)
            or not (131 < coordinates[0] < 136 and 31.5 < coordinates[1] < 35.5)):
        raise ValueError(f"{label}: invalid Point coordinates outside Shikoku")


def _feature_collection(data, label):
    if (not isinstance(data, dict) or data.get("type") != "FeatureCollection"
            or not isinstance(data.get("features"), list) or not data["features"]):
        raise ValueError(f"{label}: expected nonempty FeatureCollection")
    for feature in data["features"]:
        if (not isinstance(feature, dict) or feature.get("type") != "Feature"
                or not isinstance(feature.get("properties"), dict)):
            raise ValueError(f"{label}: malformed feature")
        point(feature.get("geometry"), label)
    return data["features"]


def expected_data(datasets_dir, basemap=None):
    """Reuse the builder's loaders and taxonomy; account for every retained point."""
    module = builder()
    documents = {name: common.read_json(Path(datasets_dir) / relative)
                 for name, relative in SOURCES.items()}
    temples = _feature_collection(documents["temples"], "temples")
    numbers = [feature["properties"].get("number") for feature in temples]
    if (len(numbers) != 88 or any(type(number) is not int for number in numbers)
            or set(numbers) != set(range(1, 89))):
        raise ValueError("Canonical temples must contain numbers 1 through 88 exactly once")
    sekaiisan = documents["sekaiisan"]
    for bucket in ("temples", "toilets"):
        rows = sekaiisan.get(bucket) if isinstance(sekaiisan, dict) else None
        if not isinstance(rows, list) or not rows:
            raise ValueError(f"sekaiisan: nonempty {bucket} input required")
        for row in rows:
            point(row.get("geometry") if isinstance(row, dict) else None, f"sekaiisan {bucket}")
    mizutani = _feature_collection(documents["mizutani"], "mizutani")
    nature = _feature_collection(documents["nature_trail"], "nature_trail")
    arukihenro = documents["arukihenro"]
    routes = arukihenro.get("routes") if isinstance(arukihenro, dict) else None
    if not isinstance(routes, list) or not routes:
        raise ValueError("arukihenro: nonempty routes input required")
    points = 0
    for route in routes:
        if not isinstance(route, dict) or not isinstance(route.get("maps"), list):
            raise ValueError("arukihenro: malformed route maps")
        for map_ in route["maps"]:
            if not isinstance(map_, dict) or not isinstance(map_.get("points"), list):
                raise ValueError("arukihenro: malformed map points")
            for row in map_["points"]:
                coordinates = row.get("coordinates") if isinstance(row, dict) else None
                point({"type": "Point", "coordinates": coordinates}, "arukihenro")
                points += 1
    if not points:
        raise ValueError("arukihenro: nonempty point input required")
    loaded = {
        "temples": module.load_temples(temples),
        "sekaiisan": module.load_sekaiisan(sekaiisan),
        "mizutani": module.load_mizutani(mizutani),
        "nature_trail": module.load_nature_trail(nature),
        "arukihenro": module.load_arukihenro(documents["arukihenro"]),
    }
    if basemap is not None:
        loaded["osm"] = module.load_osm_basemap(str(basemap))
    features, report = [], {"categories": {}}
    for name, (items, accounting) in loaded.items():
        if not items:
            raise ValueError(f"{name}: source contributed no information POIs")
        features.extend(items)
        report[name] = accounting
    features.sort(key=lambda feature: feature["id"])
    categories = Counter(feature["properties"]["category"] for feature in features)
    report["categories"] = {category: categories[category] for category in module.CATEGORIES}
    report["categories"]["total"] = report["feature_count"] = len(features)
    return features, report, module.CATEGORIES


def validate_data(datasets_dir, output, basemap=None, *, tiles=True):
    output = Path(output)
    expected, accounting, categories = expected_data(datasets_dir, basemap)
    features = _feature_collection(common.read_json(output / GEOJSON), "info_pois")
    identifiers = set()
    for feature in features:
        props = feature["properties"]
        if not FIELDS.issubset(props) or any(not isinstance(props[key], str) for key in FIELDS):
            raise ValueError("Missing or malformed consumer POI fields")
        identifier = props["poi_id"]
        if not identifier or feature.get("id") != identifier or identifier in identifiers:
            raise ValueError("Duplicate or inconsistent POI IDs")
        identifiers.add(identifier)
        if props["category"] not in categories:
            raise ValueError("Unknown information POI category")
        if props["source"] not in SOURCES and not (basemap is not None and props["source"] == "osm"):
            raise ValueError("Unknown information POI source")
        if not props["source_category"]:
            raise ValueError("Missing source category")
        if props["category"] == "lodging" and props["source"] != "osm":
            raise ValueError("Dedicated lodging is excluded from information POIs")
    if features != expected:
        raise ValueError("POI source/category accounting or features differ from published inputs")
    report = common.read_json(output / REPORT)
    if report != accounting:
        raise ValueError("POI report source/category accounting differs from retained features")
    if tiles:
        metadata = common.validate_pmtiles(output / TILES, {"info_pois"}, tile_metadata(report))
        layers = metadata["vector_layers"]
        if isinstance(layers, str):
            layers = json.loads(layers)
        if len(layers) != 1 or not FIELDS.issubset(layers[0].get("fields", {})):
            raise ValueError("Information PMTiles missing required consumer fields")
    return {"feature_count": len(features),
            "sources": dict(sorted(Counter(feature["properties"]["source"] for feature in features).items())),
            "categories": accounting["categories"]}


def tile_metadata(report):
    return {"name": "Information POIs", "dataset_id": "info-pois", "usage": "personal-use",
            "description": "Consolidated information POIs with source and unified category fields",
            "attribution": "聖地巡礼; 88sekaiisan; Mizutani Henro Guide Map; 四国自然歩道; arukihenro"
                           + ("; © OpenStreetMap contributors (ODbL)" if "osm" in report else ""),
            "feature_count": report["feature_count"]}


def validate(datasets_dir, output, reports, *, basemap=None, skip_osm=None):
    report = common.verify_report(output, reports, OUTPUTS)
    inputs = report["inputs"]
    recorded = inputs["osm"]
    selected = Path(recorded["path"]) if recorded is not None else None
    if basemap is not None and Path(basemap).resolve() != selected:
        raise ValueError("Selected OSM input differs from pipeline report")
    if skip_osm is not None and skip_osm != (selected is None):
        raise ValueError("Selected OSM mode differs from pipeline report")
    if source_inputs(datasets_dir, selected) != inputs:
        raise ValueError("Published source inputs changed since information POI build")
    config = report["build_config"]
    if config != settings(config["image"], selected is None):
        raise ValueError("Information POI build settings changed")
    summary = validate_data(datasets_dir, output, selected)
    if summary != report["summary"]:
        raise ValueError("Published validation summary mismatch")
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return summary


def _preflight(output, reports):
    for directory, names in ((Path(output), OUTPUTS), (Path(reports), ("pipeline.json",))):
        directory.mkdir(parents=True, exist_ok=True)
        if not os.access(directory, os.W_OK | os.X_OK):
            raise ValueError(f"Publication directory is not writable: {directory}")
        for name in names:
            target = directory / name
            if target.is_symlink() or (target.exists() and not target.is_file()):
                raise ValueError(f"Invalid publication target: {target}")


def build(datasets_dir, raw, output, reports, *, force=False, basemap=None, skip_osm=False,
          refresh=False, image=common.IMAGE):
    datasets_dir, raw, output, reports = map(Path, (datasets_dir, raw, output, reports))
    if skip_osm and basemap is not None:
        raise ValueError("--basemap and --skip-osm cannot be combined")
    if not skip_osm and basemap is None:
        from .osm_input import resolve
        basemap = resolve(raw, datasets_dir, refresh=refresh)
    if basemap is not None:
        basemap = Path(basemap).resolve()
    inputs = source_inputs(datasets_dir, basemap)
    config = settings(image, skip_osm)
    if not force and common.is_current(output, reports, inputs, config, OUTPUTS):
        validate(datasets_dir, output, reports, basemap=basemap, skip_osm=skip_osm)
        print("Inputs, settings and output hashes unchanged; skipping build", flush=True)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".info-pois-build-", dir=output.parent) as directory:
        staged = Path(directory)
        # Fail on malformed input before the builder can silently omit a point.
        expected_data(datasets_dir, basemap)
        command = [sys.executable, BUILDER, "--datasets-dir", datasets_dir, "--output-dir", staged]
        command += ["--skip-osm"] if skip_osm else ["--basemap", basemap]
        common.run(command)
        validate_data(datasets_dir, staged, basemap, tiles=False)
        common.build_pmtiles({"info_pois": staged / GEOJSON}, staged / TILES,
                             tile_metadata(common.read_json(staged / REPORT)), image=image)
        summary = validate_data(datasets_dir, staged, basemap)
        _preflight(output, reports)
        if source_inputs(datasets_dir, basemap) != inputs or settings(image, skip_osm) != config:
            raise ValueError("Source inputs or build settings changed during build; not published")
        return common.publish(staged, output, reports, OUTPUTS, inputs, config, summary)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", default="run", choices=("run", "build", "validate"))
    parser.add_argument("--local", action="store_true", help="run: use current published source inputs")
    parser.add_argument("--force", action="store_true", help="run/build: rebuild unchanged inputs")
    parser.add_argument("--datasets-dir", type=Path, default=DATASETS)
    parser.add_argument("--raw-dir", type=Path, default=DATASET / "raw")
    parser.add_argument("--output-dir", type=Path, default=DATASET / "output")
    parser.add_argument("--reports-dir", type=Path, default=DATASET / "reports")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--basemap", type=Path, help="explicit OSM pois PMTiles input; do not refresh OSM")
    selection.add_argument("--skip-osm", action="store_true", help="explicitly omit only OSM POIs")
    parser.add_argument("--image", default=os.environ.get("INFO_POIS_IMAGE", common.IMAGE))
    args = parser.parse_args(argv)
    if args.local and args.command != "run":
        parser.error("--local applies only to run")
    if args.force and args.command == "validate":
        parser.error("--force applies only to run/build")
    refresh = args.command == "run" and not args.local
    if refresh and args.datasets_dir.resolve() != DATASETS:
        parser.error("Remote refresh requires the default --datasets-dir; use --local or build")
    try:
        with (DATASET / ".pipeline.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if args.command == "validate":
                validate(args.datasets_dir, args.output_dir, args.reports_dir,
                         basemap=args.basemap, skip_osm=True if args.skip_osm else None)
            else:
                if refresh:
                    for source in UPSTREAM:
                        common.run([sys.executable, "-m", f"datasets.{source}", "run"])
                build(args.datasets_dir, args.raw_dir, args.output_dir, args.reports_dir,
                      force=args.force, basemap=args.basemap, skip_osm=args.skip_osm,
                      refresh=refresh, image=args.image)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0
