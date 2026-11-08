"""Download Henro Helper and publish validated route and POI GeoJSON."""

import argparse
from collections import Counter
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from . import downloader, tooling
from .reference import extract_routes as extractor

ROOT = Path(__file__).resolve().parents[2]
DATASET = Path(__file__).resolve().parent
GROUPS = {
    "routes": [row[1] for row in extractor.LAYERS],
    "pois": [row[2] for row in extractor.POI_CLASSES],
}
OUTPUTS = tuple(f"{layer}.geojson" for layers in GROUPS.values() for layer in layers) + (
    "henro-helper-routes.geojson", "henro-helper-pois.geojson", "extraction-report.json")


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def config():
    paths = sorted(DATASET.glob("*.py")) + [Path(extractor.__file__)]
    return {"blutter_revision": tooling.BLUTTER_REVISION,
            "source_sha256": {str(p.relative_to(DATASET)): digest(p) for p in paths}}


def validate_data(output):
    accounting = read_json(output / "extraction-report.json")
    summary = {}
    for group, layers in GROUPS.items():
        combined = []
        nonspatial_count = 0
        singleton_count = 0
        for layer in layers:
            data = read_json(output / f"{layer}.geojson")
            if data.get("type") != "FeatureCollection" or data.get("name") != layer:
                raise ValueError(f"Invalid collection: {layer}")
            features = data["features"]
            counts = accounting[group][layer]
            if counts["features"] != len(features):
                raise ValueError(f"Feature accounting mismatch: {layer}")
            if group == "pois":
                nonspatial = counts["nonspatial_records"]
                nonspatial_count += len(nonspatial)
                if counts["unresolved_coordinates"] or counts["records"] != len(features) + len(nonspatial):
                    raise ValueError(f"Unresolved/dropped POI coordinates: {layer}")
                indices = [f["properties"]["index"] for f in features] + [r["index"] for r in nonspatial]
                if sorted(indices) != list(range(counts["records"])):
                    raise ValueError(f"POI record index accounting mismatch: {layer}")
                for record in nonspatial:
                    if (not record["fields"] or not all(len(v) == 2 and v[0] == "str" and isinstance(v[1], str)
                                                       for v in record["fields"].values())):
                        raise ValueError(f"Invalid nonspatial source record: {layer}")
            points = 0
            for feature in features:
                props, geometry = feature["properties"], feature["geometry"]
                expected = "Point" if group == "pois" or layer == "connection" or props["num_points"] == 1 else "LineString"
                if feature.get("type") != "Feature" or props["layer"] != layer or geometry["type"] != expected:
                    raise ValueError(f"Unexpected feature: {layer}")
                coordinates = [geometry["coordinates"]] if expected == "Point" else geometry["coordinates"]
                if expected == "LineString" and len(coordinates) < 2:
                    raise ValueError(f"Degenerate route: {props['id']}")
                for coordinate in coordinates:
                    if (len(coordinate) not in (2, 3) or
                            not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in coordinate) or
                            not (131 < coordinate[0] < 136 and 32 < coordinate[1] < 35)):
                        raise ValueError(f"Invalid Shikoku coordinate: {props['id']}")
                if props["num_points"] != len(coordinates):
                    raise ValueError(f"Point accounting mismatch: {props['id']}")
                points += len(coordinates)
                if group == "routes" and layer != "connection" and expected == "Point":
                    singleton_count += 1
            if group == "routes" and counts["points"] != points:
                raise ValueError(f"Route accounting mismatch: {layer}")
            if group == "routes":
                actual_singletons = sum(f["geometry"]["type"] == "Point" for f in features) if layer != "connection" else 0
                if counts["singleton_path_count"] != actual_singletons:
                    raise ValueError(f"Singleton path accounting mismatch: {layer}")
            combined.extend(features)
        data = read_json(output / f"henro-helper-{group}.geojson")
        if data.get("type") != "FeatureCollection" or data.get("features") != combined:
            raise ValueError(f"Combined {group} differs from layers")
        ids = [f["properties"]["id"] for f in combined]
        if not combined or len(ids) != len(set(ids)):
            raise ValueError(f"Empty/duplicate {group}")
        summary[group] = {"feature_count": len(combined),
                          "point_count": sum(f["properties"]["num_points"] for f in combined),
                          "by_layer": dict(Counter(f["properties"]["layer"] for f in combined))}
        if group == "pois":
            summary[group]["nonspatial_record_count"] = nonspatial_count
            temples = [f["properties"].get("temple_number") for f in combined if f["properties"]["kind"] == "temple"]
            if sorted(temples) != list(range(1, 89)):
                raise ValueError("Expected exactly temples 1–88")
        else:
            summary[group]["singleton_path_count"] = singleton_count
    return summary


def validate(output, reports):
    report = read_json(reports / "pipeline.json")
    if set(report["outputs"]) != set(OUTPUTS):
        raise ValueError("Published output list mismatch")
    for name in OUTPUTS:
        path = output / name
        if path.stat().st_size != report["outputs"][name]["size"] or digest(path) != report["outputs"][name]["sha256"]:
            raise ValueError(f"Published output hash/size mismatch: {name}")
    summary = validate_data(output)
    if report["summary"] != summary:
        raise ValueError("Published report summary mismatch")
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return summary


def build(snapshot, output, reports, tools, force=False):
    metadata = read_json(snapshot / "metadata.json")
    settings = config()
    identity = metadata["archive_sha256"]
    if not force:
        try:
            previous = read_json(reports / "pipeline.json")
            if previous["input_sha256"] == identity and previous["build_config"] == settings:
                validate(output, reports)
                print("Inputs, settings and outputs unchanged; skipping build", flush=True)
                return
        except (OSError, ValueError, KeyError, TypeError):
            pass
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".henro-helper-build-", dir=output.parent) as directory:
        staged = Path(directory)
        blutter = staged / "blutter"
        tool_metadata = tooling.disassemble(snapshot / "lib/arm64-v8a", blutter, tools)
        candidates = sorted(blutter.glob("asm/**/BlackLines.dart"))
        if len(candidates) != 1:
            raise ValueError(f"Expected one Henro Helper assembly directory, found {len(candidates)}")
        generated = staged / "output"
        command = [sys.executable, "-m", "datasets.henro_helper.reference.extract_routes",
                   "--asm-dir", str(candidates[0].parent),
                   "--pp-file", str(blutter / "pp.txt"), "--out-dir", str(generated)]
        print("+ " + " ".join(command), flush=True)
        subprocess.run(command, cwd=ROOT, check=True)
        summary = validate_data(generated)
        if (config() != settings or read_json(snapshot / "metadata.json") != metadata or
                digest(snapshot / metadata["archive"]) != identity or
                any(digest(snapshot / "lib/arm64-v8a" / name) != checksum
                    for name, checksum in metadata["libraries"].items())):
            raise ValueError("Source or extractor changed during build; not published")
        report = {"package_name": downloader.PACKAGE, "version_name": metadata["version_name"],
                  "version_code": metadata["version_code"], "input_sha256": identity,
                  "build_config": settings, "tooling": tool_metadata, "summary": summary,
                  "outputs": {name: {"size": (generated / name).stat().st_size,
                                     "sha256": digest(generated / name)} for name in OUTPUTS}}
        output.mkdir(parents=True, exist_ok=True)
        for name in OUTPUTS:
            os.replace(generated / name, output / name)
        atomic_json(reports / "pipeline.json", report)
    print(f"Published: {output}", flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", default="run", choices=("run", "fetch", "build", "validate"))
    parser.add_argument("--local", action="store_true", help="run: use the validated local snapshot")
    parser.add_argument("--force", action="store_true", help="run/build: rebuild unchanged data")
    parser.add_argument("--raw-dir", type=Path, default=DATASET / "raw")
    parser.add_argument("--output-dir", type=Path, default=DATASET / "output")
    parser.add_argument("--reports-dir", type=Path, default=DATASET / "reports")
    parser.add_argument("--tools-dir", type=Path, default=ROOT / "work/henro-helper-tools")
    args = parser.parse_args(argv)
    if args.local and args.command != "run":
        parser.error("--local applies only to run")
    if args.force and args.command not in ("run", "build"):
        parser.error("--force applies only to run/build")
    raw, output, reports, tools = (p.resolve() for p in (args.raw_dir, args.output_dir, args.reports_dir, args.tools_dir))
    try:
        with (DATASET / ".pipeline.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if args.command == "validate":
                validate(output, reports)
            else:
                snapshot = (downloader.fetch(raw) if args.command == "fetch" or
                            (args.command == "run" and not args.local) else downloader.resolve(raw))
                if args.command != "fetch":
                    build(snapshot, output, reports, tools, args.force)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
