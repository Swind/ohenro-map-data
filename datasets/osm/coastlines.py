"""Prepare the official coastline archives, with a pinned RRZE backup."""

import argparse
import json
import os
from pathlib import Path
import re
import struct
import tempfile
import zipfile
import zlib

from datasets._pipeline import atomic_json
from datasets.osm.__main__ import DATASET, ROOT, digest, download

OFFICIAL = "https://osmdata.openstreetmap.de/download/"
MIRROR_DATE = "2026-10-31"
MIRROR = f"https://ftp.rrze.uni-erlangen.de/pub/openstreetmapdata.com-archive/{MIRROR_DATE}/"
ARCHIVES = {f"{kind}-polygons-split-3857.zip": f"{kind}_polygons" for kind in ("water", "land")}
ERRORS = (OSError, ValueError, RuntimeError, zipfile.BadZipFile, zlib.error)


def validate_archive(path, layer):
    folder = path.name.removesuffix(".zip")
    with zipfile.ZipFile(path) as archive:
        required = {f"{folder}/{layer}.{suffix}" for suffix in ("shp", "shx", "dbf", "prj")}
        required.add(f"{folder}/README.txt")
        names = archive.namelist()
        if len(names) != len(set(names)) or not required.issubset(names):
            raise ValueError(f"Missing or duplicate coastline archive members: {path.name}")
        for name in (f"{folder}/README.txt", f"{folder}/{layer}.prj"):
            if archive.getinfo(name).file_size > 65536:
                raise ValueError("Unexpectedly large coastline metadata")
        readme = archive.read(f"{folder}/README.txt").decode("utf-8")
        projection = archive.read(f"{folder}/{layer}.prj").decode("utf-8")
        date = re.search(r"Date of the data used is (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)", readme)
        if not date or "EPSG: 3857" not in readme or "Open Database License" not in readme:
            raise ValueError("Missing coastline date, EPSG:3857 or ODbL metadata")
        if "Mercator" not in projection or "6378137" not in projection:
            raise ValueError("Unexpected coastline projection")
        for suffix in ("shp", "shx"):
            member = f"{folder}/{layer}.{suffix}"
            with archive.open(member) as stream:
                header = stream.read(100)
            if (len(header) != 100 or struct.unpack_from(">I", header)[0] != 9994
                    or struct.unpack_from("<II", header, 28) != (1000, 5)
                    or struct.unpack_from(">I", header, 24)[0] * 2 != archive.getinfo(member).file_size):
                raise ValueError(f"Invalid polygon shapefile header: {member}")
        broken = archive.testzip()
        if broken is not None:
            raise ValueError(f"Coastline ZIP CRC failure: {broken}")
    return {"data_date": date[1], "size": path.stat().st_size, "sha256": digest(path)}


def prepare(sources, reports):
    sources, reports = Path(sources), Path(reports)
    sources.mkdir(parents=True, exist_ok=True)
    report_path = reports / "coastlines.json"
    try:
        previous = json.loads(report_path.read_text())
        previous = previous.get("archives", {}) if isinstance(previous, dict) else {}
        if not isinstance(previous, dict):
            previous = {}
    except (OSError, ValueError):
        previous = {}
    records = {}
    for name, layer in ARCHIVES.items():
        target = sources / name
        try:
            metadata = validate_archive(target, layer)
            old = previous.get(name)
            if isinstance(old, dict) and old.get("sha256") == metadata["sha256"]:
                records[name] = {**old, **metadata}
            else:
                records[name] = {**metadata, "source": "existing_cache", "url": None}
            print(f"Coastline cache valid: {name} ({metadata['data_date']})", flush=True)
            continue
        except ERRORS as error:
            print(f"Coastline cache unavailable: {name}: {error}", flush=True)
        failures = []
        with tempfile.TemporaryDirectory(prefix=".coastlines-", dir=sources) as temporary:
            candidate = Path(temporary) / name
            for source, base in (("official", OFFICIAL), ("rrze", MIRROR)):
                url = base + name
                try:
                    print(f"Downloading coastline ({source}): {url}", flush=True)
                    download(url, candidate)
                    metadata = validate_archive(candidate, layer)
                    if source == "rrze" and metadata["data_date"][:10] != MIRROR_DATE:
                        raise ValueError("RRZE archive does not match the pinned snapshot date")
                except ERRORS as error:
                    failures.append(f"{url}: {error}")
                    print(f"Coastline download rejected: {failures[-1]}", flush=True)
                    continue
                os.replace(candidate, target)
                records[name] = {**metadata, "source": source, "url": url}
                if source == "rrze":
                    records[name]["mirror_snapshot"] = MIRROR_DATE
                break
            else:
                raise ValueError("No valid coastline archive; existing cache kept: " + "; ".join(failures))
    report = {"archives": records}
    if records != previous or not report_path.is_file():
        atomic_json(report_path, report)
    return records


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources-dir", type=Path, default=ROOT / "basemaps/tiles/data/sources")
    parser.add_argument("--reports-dir", type=Path, default=DATASET / "reports")
    args = parser.parse_args(argv)
    try:
        prepare(args.sources_dir, args.reports_dir)
    except ERRORS as error:
        parser.exit(1, f"ERROR: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
