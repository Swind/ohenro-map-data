"""Check Shikoku DEM updates and build validated elevation products from local ZIPs."""

import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from urllib.request import urlopen
import zipfile

ROOT = Path(__file__).resolve().parents[2]
DATASET = Path(__file__).resolve().parent
CRATE = DATASET / "gsi-dem"
KINDS = {"DEM5A": "DEM5/5A", "DEM5B": "DEM5/5B", "DEM5C": "DEM5/5C", "DEM10B": "DEM10B"}
CATALOG_URL = "https://service.gsi.go.jp/kiban/app/api/dem/latest?type_codes=DEM5A,DEM5B,DEM5C,DEM10B&region_codes=shikoku"
OUTPUTS = ("shikoku-elevation.sqlite", "shikoku-elevation-dem10.sqlite",
           "shikoku-contours.pmtiles", "shikoku-terrain.pmtiles")
NAME = re.compile(r"FG-GML-(\d{6})-(DEM5A|DEM5B|DEM5C|DEM10B)-(\d{8})\.zip")


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write("\n")
        temporary = f.name
    os.replace(temporary, path)


def inventory(raw, verify=False):
    files, keys = {}, set()
    for path in sorted(raw.rglob("*.zip")):
        match = NAME.fullmatch(path.name)
        if not match:
            raise ValueError(f"Unexpected ZIP: {path}; see datasets/gsi/README.md")
        mesh, kind, _date = match.groups()
        if path.parent != raw / KINDS[kind]:
            raise ValueError(f"Place {path.name} in {raw / KINDS[kind]}")
        key = (mesh, kind)
        if key in keys:
            raise ValueError(f"Multiple versions of {mesh}/{kind}; move old ZIPs outside raw/")
        keys.add(key)
        if verify:
            with zipfile.ZipFile(path) as archive:
                if not archive.namelist() or archive.testzip() is not None:
                    raise ValueError(f"Invalid ZIP: {path}")
        files[path.name] = path
    if not files:
        raise ValueError(f"No DEM ZIPs in {raw}; see datasets/gsi/README.md")
    return files


def check(raw, reports):
    with urlopen(CATALOG_URL, timeout=60) as response:
        payload = json.load(response)
    if payload.get("result", {}).get("status") != "success":
        raise ValueError("GSI catalog request failed")
    records = payload.get("results")
    if not isinstance(records, list) or not records:
        raise ValueError("Empty/invalid GSI catalog")
    expected = {}
    for item in records:
        name = item.get("file_name", "")
        match = NAME.fullmatch(name)
        if not match or match[2] != item.get("type_code") or match[1] != item.get("place_code") or name in expected:
            raise ValueError(f"Unexpected GSI catalog record: {item}")
        expected[name] = {**item, "destination": str(raw / KINDS[match[2]] / name)}
    local = inventory(raw) if any(raw.rglob("*.zip")) else {}
    missing = sorted(expected.keys() - local.keys())
    extra = sorted(local.keys() - expected.keys())
    report = {"catalog_url": CATALOG_URL, "records": list(expected.values()),
              "missing_or_updated": missing, "obsolete_or_extra": extra,
              "comparison": "filenames only; upstream provides no checksum"}
    write_json(reports / "updates.json", report)
    print(f"Official Shikoku catalog: {len(expected)} ZIPs; missing/new: {len(missing)}; obsolete/extra: {len(extra)}", flush=True)
    for name in missing:
        print(f"Download: {name} -> {expected[name]['destination']}")
    for name in extra:
        print(f"Move outside raw/: {local[name]}")
    if missing or extra:
        print("Log in at https://service.gsi.go.jp/kiban/app/map/?search=dem and select 四国. See datasets/gsi/README.md")
        return False
    return True


def digest(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def run(command, **kwargs):
    print("+ " + " ".join(map(str, command)), flush=True)
    subprocess.run(list(map(str, command)), cwd=ROOT, check=True, **kwargs)


def rust(*args):
    run(["cargo", "run", "--manifest-path", CRATE / "Cargo.toml", "--release", "--", *args])


def validate(output, reports):
    for name, layers in ((OUTPUTS[0], {5, 10}), (OUTPUTS[1], {10})):
        with sqlite3.connect((output / name).as_uri() + "?mode=ro", uri=True) as db:
            if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise ValueError(f"SQLite integrity failed: {name}")
            if {r[0] for r in db.execute("SELECT DISTINCT layer FROM elevation_tiles")} != layers:
                raise ValueError(f"Unexpected/empty layers: {name}")
    # The small database must contain exactly the full database's DEM10 tiles.
    with sqlite3.connect((output / OUTPUTS[0]).as_uri() + "?mode=ro", uri=True) as db:
        db.execute("ATTACH DATABASE ? AS small", ((output / OUTPUTS[1]).as_uri() + "?mode=ro",))
        for table in ("elevation_tiles", "source_tiles"):
            for left, right in (("main", "small"), ("small", "main")):
                if db.execute(f"SELECT * FROM {left}.{table} WHERE layer=10 EXCEPT SELECT * FROM {right}.{table} WHERE layer=10 LIMIT 1").fetchone():
                    raise ValueError(f"DEM10 subset mismatch: {table}")
    rust("validate-db", output / OUTPUTS[0], "--golden", CRATE / "tests/golden/elevation.json",
         "--report", reports / "validation.json")
    run(["bash", DATASET / "scripts/validate-elevation-visuals.sh", output / OUTPUTS[2], output / OUTPUTS[3]])
    for name in OUTPUTS[2:]:
        run(["pmtiles", "verify", output / name])


def build_config():
    defaults = {"CONTOUR_INTERVAL": "20", "TERRAIN_MIN_ZOOM": "6", "TERRAIN_MAX_ZOOM": "14",
                "RGBIFY_WORKERS": "4", "ELEVATION_IMAGE": "ohenro-elevation-visuals"}
    # Source changes invalidate the previous build as well as parameter changes.
    sources = [Path(__file__), ROOT / "docker/Dockerfile.elevation", CRATE / "Cargo.toml", CRATE / "Cargo.lock"]
    sources += list((CRATE / "src").rglob("*.rs"))
    sources += list((CRATE / "tests/golden").glob("*.json"))
    sources += [p for p in (DATASET / "scripts").iterdir() if p.suffix in (".py", ".sh")]
    return {"environment": {key: os.environ.get(key) or value for key, value in defaults.items()},
            "source_sha256": {str(p.relative_to(ROOT)): digest(p) for p in sorted(sources)}}


def is_current(output, reports, hashes, config):
    try:
        previous = json.loads((reports / "pipeline.json").read_text())
        if previous["input_sha256"] != hashes or previous["build_config"] != config:
            return False
        for name in OUTPUTS:
            path = output / name
            recorded = previous["outputs"][name]
            if path.stat().st_size != recorded["size"] or digest(path) != recorded["sha256"]:
                return False
        return True
    except (OSError, ValueError, KeyError, TypeError):
        return False


def build(raw, output, reports, force=False):
    files = inventory(raw)
    hashes = {name: digest(path) for name, path in files.items()}
    config = build_config()
    if not force and is_current(output, reports, hashes, config):
        print(f"Inputs, build settings and outputs unchanged; skipping build: {output}", flush=True)
        return
    for tool in ("cargo", "docker", "pmtiles"):
        if not shutil.which(tool):
            raise ValueError(f"Missing {tool}; see datasets/gsi/README.md")
    for package in ("mercantile", "numpy", "PIL", "pmtiles", "mapbox_vector_tile"):
        if importlib.util.find_spec(package) is None:
            raise ValueError(f"Missing {package}; install datasets/gsi/requirements.txt")
    inventory(raw, verify=True)
    image = os.environ.get("ELEVATION_IMAGE", "ohenro-elevation-visuals")
    run(["docker", "info"], stdout=subprocess.DEVNULL)
    if subprocess.run(["docker", "image", "inspect", image], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
        run(["docker", "build", "-t", image, "-f", ROOT / "docker/Dockerfile.elevation", ROOT])
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".gsi-build-", dir=output.parent) as directory:
        work = Path(directory)
        staged, logs = work / "output", work / "reports"
        staged.mkdir()
        logs.mkdir()
        rust("merge", "--input", raw / "DEM5", "--dem10b-input", raw / "DEM10B",
             "--out-dir", work / "merged", "--report", logs / "merge.json")
        rust("tile", "--merged", work / "merged", "--dem10b", raw / "DEM10B",
             "--out", work / "tiles", "--report", logs / "tile.json")
        for name, options in ((OUTPUTS[0], []), (OUTPUTS[1], ["--layer", "10"])):
            rust("build", "--tiles", work / "tiles", "--grid", logs / "tile.json", "--output", staged / name, *options)
        run(["bash", DATASET / "scripts/build-elevation-visuals.sh"], env={**os.environ,
             "ELEVATION_DB": str(staged / OUTPUTS[1]), "WORK_DIR": str(work / "visuals"),
             "GSI_OUTPUT_DIR": str(staged), "GSI_REPORTS_DIR": str(logs)})
        validate(staged, logs)
        if {name: digest(path) for name, path in inventory(raw).items()} != hashes:
            raise ValueError("Inputs changed during build; outputs not published")
        write_json(logs / "pipeline.json", {"input_sha256": hashes, "build_config": config,
                   "outputs": {name: {"sha256": digest(staged / name), "size": (staged / name).stat().st_size} for name in OUTPUTS}})
        output.mkdir(parents=True, exist_ok=True)
        reports.mkdir(parents=True, exist_ok=True)
        for name in OUTPUTS:
            os.replace(staged / name, output / name)
        for path in logs.iterdir():
            os.replace(path, reports / path.name)
    print(f"Published: {output}", flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", choices=("run", "check", "build", "validate"), default="run")
    parser.add_argument("--local", action="store_true", help="run: skip online update check")
    parser.add_argument("--force", action="store_true", help="run/build: rebuild even when inputs, settings and outputs are unchanged")
    parser.add_argument("--raw-dir", type=Path, default=DATASET / "raw")
    parser.add_argument("--output-dir", type=Path, default=DATASET / "output")
    parser.add_argument("--reports-dir", type=Path, default=DATASET / "reports")
    args = parser.parse_args(argv)
    if args.local and args.command != "run":
        parser.error("--local applies only to run; build already uses local inputs")
    if args.force and args.command not in ("run", "build"):
        parser.error("--force applies only to run/build")
    raw, output, reports = (p.resolve() for p in (args.raw_dir, args.output_dir, args.reports_dir))
    try:
        with (DATASET / ".pipeline.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if args.command == "check" or (args.command == "run" and not args.local):
                if not check(raw, reports):
                    return 1
            if args.command in ("run", "build"):
                build(raw, output, reports, force=args.force)
            if args.command == "validate":
                validate(output, reports)
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, sqlite3.Error, subprocess.CalledProcessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
