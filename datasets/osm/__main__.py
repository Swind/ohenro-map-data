"""Download/update Shikoku OSM and build all source-specific outputs."""

import argparse
from contextlib import ExitStack
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
DATASET = Path(__file__).resolve().parent
URL = "https://download.geofabrik.de/asia/japan/shikoku-latest.osm.pbf"
OUTPUTS = ("shikoku-basemap.pmtiles", "shikoku-henro.pmtiles", "lodging.geojson", "lodging-report.json")


def digest(path, algorithm="sha256"):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, algorithm).hexdigest()


def download(url, destination):
    for attempt in range(3):
        try:
            with urlopen(url, timeout=60) as response, Path(destination).open("wb") as handle:
                shutil.copyfileobj(response, handle)
                handle.flush()
                os.fsync(handle.fileno())
            return
        except (OSError, ValueError) as error:
            if isinstance(error, HTTPError):
                error.close()
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


def validate_pbf(path):
    import osmium

    if not path.is_file() or not path.stat().st_size:
        raise ValueError(f"PBF missing or empty: {path}. Run fetch, or place a Shikoku .osm.pbf here.")
    with osmium.io.Reader(osmium.io.File(str(path), "pbf")) as reader:
        reader.header()


def fetch(pbf):
    """Use the upstream MD5 to avoid downloading an unchanged ~90MB extract."""
    pbf.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".download-", dir=pbf.parent) as temporary:
        temporary = Path(temporary)
        checksum = temporary / "checksum.md5"
        download(URL + ".md5", checksum)
        match = re.fullmatch(r"([0-9a-fA-F]{32})\s+\*?shikoku-(?:latest|\d{6})\.osm\.pbf\s*", checksum.read_text())
        if not match:
            raise ValueError("Unexpected Geofabrik checksum response")
        expected = match[1].lower()
        if pbf.is_file() and digest(pbf, "md5") == expected:
            validate_pbf(pbf)
            print(f"Source unchanged: {pbf}", flush=True)
            return
        candidate = temporary / "shikoku.osm.pbf"
        print(f"Downloading {URL}", flush=True)
        download(URL, candidate)
        if digest(candidate, "md5") != expected:
            raise ValueError("PBF checksum mismatch; existing input kept. Upstream may be updating; rerun fetch.")
        validate_pbf(candidate)
        if pbf.exists():
            snapshots = pbf.parent / "snapshots"
            snapshots.mkdir(exist_ok=True)
            previous = snapshots / (digest(pbf) + ".osm.pbf")
            if not previous.exists():
                # Both files are on the same filesystem; preserve the old bytes without copying.
                os.link(pbf, previous)
        os.replace(candidate, pbf)
        print(f"Updated source: {pbf} (MD5 {expected})", flush=True)


def run(command, **kwargs):
    print("+ " + " ".join(map(str, command)), flush=True)
    subprocess.run(list(map(str, command)), check=True, cwd=ROOT, **kwargs)


def pmtiles_cli():
    binary = shutil.which("pmtiles") or shutil.which("go-pmtiles")
    if not binary:
        raise ValueError("Install pmtiles/go-pmtiles CLI; see datasets/osm/README.md")
    return binary


def preflight():
    for binary in ("java", "mvn", "git", "bash"):
        if not shutil.which(binary):
            raise ValueError(f"Missing {binary}; see datasets/osm/README.md")
    version = subprocess.run(["java", "-version"], capture_output=True, text=True, check=True)
    match = re.search(r'version "(\d+)', version.stderr + version.stdout)
    if not match or int(match[1]) < 21:
        raise ValueError("Java 21+ is required")
    for package in ("osmium", "shapely", "pmtiles"):
        if importlib.util.find_spec(package) is None:
            raise ValueError(f"Missing {package}: {sys.executable} -m pip install -r datasets/osm/requirements.txt")
    pmtiles_cli()


def validate(output):
    binary = pmtiles_cli()
    for name, required in (
        ("shikoku-basemap.pmtiles", {"roads", "water", "buildings", "places", "pois"}),
        ("shikoku-henro.pmtiles", {"henro_routes"}),
    ):
        path = output / name
        run([binary, "verify", path])
        metadata = json.loads(subprocess.check_output([binary, "show", "--metadata", str(path)]))
        layers = metadata["vector_layers"]
        if isinstance(layers, str):
            layers = json.loads(layers)
        if not required <= {layer["id"] for layer in layers}:
            raise ValueError(f"Missing required layers: {path}")
        header = json.loads(subprocess.check_output([binary, "show", "--header-json", str(path)]))
        west, south, east, north = header["bounds"]
        if not (131 < west < east < 136 and 31.5 < south < north < 35.5):
            raise ValueError(f"Unexpected Shikoku bounds: {path}")
    run([sys.executable, DATASET / "scripts/smoke-test-henro.py", output / "shikoku-henro.pmtiles"])
    geojson = json.loads((output / "lodging.geojson").read_text())
    report = json.loads((output / "lodging-report.json").read_text())
    features = geojson["features"]
    if geojson["type"] != "FeatureCollection" or not features or len(features) != report["total"]:
        raise ValueError("Lodging feature count/report mismatch")
    ids = set()
    for feature in features:
        geometry = feature["geometry"]
        lon, lat = geometry["coordinates"]
        if geometry["type"] != "Point" or not (131 < lon < 136 and 31.5 < lat < 35.5):
            raise ValueError("Invalid lodging point")
        if feature["id"] in ids or feature["id"] != feature["properties"]["id"]:
            raise ValueError("Invalid/duplicate lodging ID")
        ids.add(feature["id"])
    print(f"Validation passed: 2 PMTiles + {len(features)} lodging points", flush=True)


def normalize_zoom_header(path, reports):
    """Planetiler declares z0 even when small overlay lines first produce tiles at z5."""
    from pmtiles.reader import MmapSource, all_tiles

    with path.open("rb") as handle:
        zooms = {zxy[0] for zxy, _data in all_tiles(MmapSource(handle))}
    if not zooms:
        raise ValueError(f"No tiles in {path}")
    binary = pmtiles_cli()
    header = json.loads(subprocess.check_output([binary, "show", "--header-json", str(path)]))
    if (header["minzoom"], header["maxzoom"]) != (min(zooms), max(zooms)):
        header.update(minzoom=min(zooms), maxzoom=max(zooms))
        with tempfile.TemporaryDirectory(dir=path.parent) as temporary:
            header_path = Path(temporary) / "header.json"
            header_path.write_text(json.dumps(header))
            run([binary, "edit", path, "--header-json", header_path])
        with (reports / "henro-metadata.txt").open("wb") as handle:
            subprocess.run([binary, "show", str(path)], stdout=handle, check=True)


def build(pbf, output, reports, source_url=None):
    validate_pbf(pbf)
    if not (ROOT / "basemaps/tiles/pom.xml").is_file():
        run(["git", "submodule", "update", "--init", "--", "basemaps"])
    output.parent.mkdir(parents=True, exist_ok=True)
    reports.mkdir(parents=True, exist_ok=True)
    source_sha = digest(pbf)
    with tempfile.TemporaryDirectory(prefix=".osm-build-", dir=output.parent) as directory:
        staged = Path(directory)
        env = {**os.environ, "OSM_REPORTS_DIR": str(reports), "PYTHON": sys.executable}
        run(["bash", DATASET / "scripts/build-basemap.sh", pbf, staged], env=env)
        run(["bash", DATASET / "scripts/build-henro.sh", pbf, staged], env=env)
        run([sys.executable, DATASET / "henro/scripts/extract_lodging.py", pbf,
             staged / "lodging.geojson", staged / "lodging-report.json"])
        normalize_zoom_header(staged / "shikoku-henro.pmtiles", reports)
        validate(staged)
        if digest(pbf) != source_sha:
            raise ValueError("Source changed during build; outputs not published")
        summary = {
            "source_url": source_url,
            "input_path": str(pbf),
            "input_sha256": source_sha,
            "basemaps_commit": subprocess.check_output(["git", "-C", str(ROOT / "basemaps"), "rev-parse", "HEAD"], text=True).strip(),
            "coastlines": json.loads((reports / "coastlines.json").read_text())["archives"],
            "lodging_count": json.loads((staged / "lodging-report.json").read_text())["total"],
            "outputs": {name: {"size": (staged / name).stat().st_size, "sha256": digest(staged / name)} for name in OUTPUTS},
        }
        output.mkdir(parents=True, exist_ok=True)
        for name in OUTPUTS:
            os.replace(staged / name, output / name)
        summary_path = reports / "pipeline.json"
        with tempfile.NamedTemporaryFile(mode="w", dir=reports, delete=False, encoding="utf-8") as handle:
            json.dump(summary, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            temporary = handle.name
        os.replace(temporary, summary_path)
        print(f"Published {output}; report: {summary_path}", flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", choices=("run", "fetch", "build", "validate"), default="run")
    parser.add_argument("--local", action="store_true", help="run: use the local PBF instead of fetching updates")
    parser.add_argument("--pbf", type=Path, default=DATASET / "raw/shikoku-latest.osm.pbf")
    parser.add_argument("--output-dir", type=Path, default=DATASET / "output")
    parser.add_argument("--reports-dir", type=Path, default=DATASET / "reports")
    args = parser.parse_args(argv)
    if args.local and args.command != "run":
        parser.error("--local applies only to run; build already uses the local PBF")
    try:
        # Planetiler's two projects use shared intermediate directories.
        with ExitStack() as stack:
            if args.command in ("run", "build"):
                lock = stack.enter_context((DATASET / ".pipeline.lock").open("a"))
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise ValueError("Another OSM build is already running") from None
                preflight()
            if args.command == "fetch" or (args.command == "run" and not args.local):
                fetch(args.pbf.resolve())
            if args.command in ("run", "build"):
                build(args.pbf.resolve(), args.output_dir.resolve(), args.reports_dir.resolve(),
                      source_url=URL if args.command == "run" and not args.local else None)
            if args.command == "validate":
                validate(args.output_dir.resolve())
    except (OSError, ValueError, RuntimeError, ImportError, subprocess.CalledProcessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
