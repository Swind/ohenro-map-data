"""Fetch the 88 temples and build JSON, GeoJSON, SQLite and PMTiles."""

import argparse
import fcntl
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
DATASET = Path(__file__).resolve().parent
SCRIPTS = DATASET / "scripts"
URL = "https://www.seichijunrei-shikokuhenro.jp/map/all"
OUTPUTS = ("temples.json", "temples.geojson", "content.sqlite", "shikoku-temples.pmtiles")
IMAGE = "ohenro-elevation-visuals"


def content_module():
    spec = importlib.util.spec_from_file_location("temple_content", SCRIPTS / "build-content-sqlite.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def run(command, **kwargs):
    print("+ " + " ".join(map(str, command)), flush=True)
    subprocess.run(list(map(str, command)), cwd=ROOT, check=True, **kwargs)


def script(name, *args):
    run([sys.executable, SCRIPTS / name, *args])


def records(path):
    data = json.loads(path.read_text())
    content_module().validate_records(data)
    if any(not (131 < t["location"]["longitude"] < 136 and 32 < t["location"]["latitude"] < 35) for t in data):
        raise ValueError("Temple coordinates outside Shikoku")
    return data


def fetch(raw):
    raw.mkdir(parents=True, exist_ok=True)
    destination = raw / "spots.json"
    with tempfile.TemporaryDirectory(prefix=".fetch-", dir=raw) as directory:
        work = Path(directory)
        candidate = work / "spots.json"
        script("extract_henro.py", URL, candidate)
        script("normalize_henro.py", candidate, work / "temples.json")
        records(work / "temples.json")
        if destination.exists() and digest(candidate) == digest(destination):
            print("Source unchanged", flush=True)
            return
        if destination.exists():
            snapshots = raw / "snapshots"
            snapshots.mkdir(exist_ok=True)
            previous = snapshots / f"{digest(destination)}.json"
            if not previous.exists():
                os.link(destination, previous)
        os.replace(candidate, destination)
    print(f"Updated: {destination}", flush=True)


def config():
    paths = [Path(__file__), ROOT / "docker/Dockerfile.elevation", *SCRIPTS.glob("*.py")]
    return {"image": IMAGE, "layer": "temples", "zoom": [0, 14],
            "source_sha256": {str(p.relative_to(ROOT)): digest(p) for p in sorted(paths)}}


def current(raw_hash, settings, output, reports):
    try:
        report = json.loads((reports / "pipeline.json").read_text())
        return report["input_sha256"] == raw_hash and report["build_config"] == settings and all(
            (output / name).stat().st_size == report["outputs"][name]["size"]
            and digest(output / name) == report["outputs"][name]["sha256"] for name in OUTPUTS)
    except (OSError, ValueError, KeyError, TypeError):
        return False


def validate(output):
    data = records(output / "temples.json")
    expected = {t["id"]: t for t in data}
    geo = json.loads((output / "temples.geojson").read_text())
    if geo["type"] != "FeatureCollection" or len(geo["features"]) != 88:
        raise ValueError("Expected 88 GeoJSON features")
    seen = set()
    for feature in geo["features"]:
        ident = feature["id"]
        t = expected[ident]
        props = feature["properties"]
        if ident in seen or props != {"id": ident, "type": "temple", "number": t["number"],
                "name_ja": t["name"]["ja"], "name_en": t["name"]["en"], "name_kana": t["name"]["kana"]}:
            raise ValueError("GeoJSON properties mismatch")
        if feature["geometry"] != {"type": "Point", "coordinates": [t["location"]["longitude"], t["location"]["latitude"]]}:
            raise ValueError("GeoJSON coordinates mismatch")
        seen.add(ident)
    with sqlite3.connect((output / "content.sqlite").as_uri() + "?mode=ro", uri=True) as db:
        if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("SQLite integrity failed")
        rows = db.execute("SELECT id, provider, kind, name, latitude, longitude, payload_json FROM features ORDER BY id").fetchall()
        if rows != list(content_module().ordered_rows(data)):
            raise ValueError("SQLite content differs from canonical JSON")
    from pmtiles.reader import MmapSource, Reader, all_tiles
    from mapbox_vector_tile import decode

    path = output / OUTPUTS[3]
    run(["pmtiles", "verify", path])
    with path.open("rb") as handle:
        source = MmapSource(handle)
        reader = Reader(source)
        if "seichijunrei-shikokuhenro.jp" not in reader.metadata().get("attribution", ""):
            raise ValueError("Missing source attribution")
        header = reader.header()
        if (header["min_zoom"], header["max_zoom"]) != (0, 14):
            raise ValueError("Unexpected PMTiles zoom range")
        ids = set()
        for (z, _x, _y), tile in all_tiles(source):
            if z != 14:
                continue
            layers = decode(gzip.decompress(tile) if tile[:2] == b"\x1f\x8b" else tile)
            for feature in layers["temples"]["features"]:
                props = feature["properties"]
                t = expected[props["id"]]
                if props["number"] != t["number"] or props["name_ja"] != t["name"]["ja"] or feature["geometry"]["type"] != "Point":
                    raise ValueError("PMTiles temple mismatch")
                ids.add(props["id"])
        if ids != set(expected):
            raise ValueError("PMTiles must contain all 88 temple IDs at z14")
    print("Validation passed: 88 temples in JSON / GeoJSON / SQLite / PMTiles", flush=True)


def build(raw, output, reports, force=False):
    source = raw / "spots.json"
    raw_hash, settings = digest(source), config()
    if not force and current(raw_hash, settings, output, reports):
        print("Inputs, settings and outputs unchanged; skipping build", flush=True)
        return
    for tool in ("docker", "pmtiles"):
        if not shutil.which(tool):
            raise ValueError(f"Missing {tool}; see datasets/seichijunrei/README.md")
    for package in ("pmtiles", "mapbox_vector_tile"):
        if importlib.util.find_spec(package) is None:
            raise ValueError(f"Missing {package}; install datasets/seichijunrei/requirements.txt")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".temples-build-", dir=output.parent) as directory:
        staged = Path(directory)
        script("normalize_henro.py", source, staged / "temples.json")
        data = records(staged / "temples.json")
        script("generate_geojson.py", staged / "temples.json", staged / "temples.geojson")
        content_module().build_sqlite(data, staged / "content.sqlite")
        run(["docker", "info"], stdout=subprocess.DEVNULL)
        if subprocess.run(["docker", "image", "inspect", IMAGE], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
            run(["docker", "build", "-t", IMAGE, "-f", ROOT / "docker/Dockerfile.elevation", ROOT])
        run(["docker", "run", "--rm", "--user", f"{os.getuid()}:{os.getgid()}", "-v", f"{staged}:{staged}", IMAGE,
             "tippecanoe", "-o", staged / "temples.mbtiles", "-l", "temples", "-Z0", "-z14", "-r1",
             "--no-feature-limit", "--no-tile-size-limit", "--attribution",
             '<a href="https://www.seichijunrei-shikokuhenro.jp/">聖地巡礼 四国遍路</a>', staged / "temples.geojson"])
        run(["pmtiles", "convert", staged / "temples.mbtiles", staged / OUTPUTS[3]])
        validate(staged)
        if digest(source) != raw_hash:
            raise ValueError("Source changed during build; not published")
        report = {"source_url": URL, "input_sha256": raw_hash, "build_config": settings, "temple_count": 88,
                  "outputs": {name: {"size": (staged / name).stat().st_size, "sha256": digest(staged / name)} for name in OUTPUTS}}
        output.mkdir(parents=True, exist_ok=True)
        reports.mkdir(parents=True, exist_ok=True)
        for name in OUTPUTS:
            os.replace(staged / name, output / name)
        with tempfile.NamedTemporaryFile(mode="w", dir=reports, delete=False) as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
            temporary = f.name
        os.replace(temporary, reports / "pipeline.json")
    print(f"Published: {output}", flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", default="run", choices=("run", "fetch", "build", "validate"))
    parser.add_argument("--local", action="store_true", help="run: use local spots.json without fetching")
    parser.add_argument("--force", action="store_true", help="run/build: force rebuilding")
    parser.add_argument("--raw-dir", type=Path, default=DATASET / "raw")
    parser.add_argument("--output-dir", type=Path, default=DATASET / "output")
    parser.add_argument("--reports-dir", type=Path, default=DATASET / "reports")
    args = parser.parse_args(argv)
    if args.local and args.command != "run":
        parser.error("--local applies only to run")
    if args.force and args.command not in ("run", "build"):
        parser.error("--force applies only to run/build")
    raw, output, reports = (p.resolve() for p in (args.raw_dir, args.output_dir, args.reports_dir))
    try:
        with (DATASET / ".pipeline.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if args.command == "fetch" or (args.command == "run" and not args.local):
                fetch(raw)
            if args.command in ("run", "build"):
                build(raw, output, reports, force=args.force)
            if args.command == "validate":
                validate(output)
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error, subprocess.CalledProcessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
