"""Small shared helpers for source-local, validated dataset publication."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "ohenro-elevation-visuals:latest"


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def code_hash(dataset):
    dataset = Path(dataset)
    excluded = {"raw", "output", "reports", "tests", "__pycache__", "docs"}
    paths = [p for p in dataset.rglob("*") if p.is_file()
             and p.suffix in (".py", ".sh", ".json")
             and not excluded.intersection(p.relative_to(dataset).parts)
             and not any(part.startswith(".") for part in p.relative_to(dataset).parts)]
    return {"shared": digest(__file__), **{str(p.relative_to(dataset)): digest(p) for p in sorted(paths)}}


def run(command, **kwargs):
    command = list(map(str, command))
    print("+ " + " ".join(command), flush=True)
    return subprocess.run(command, cwd=ROOT, check=True, **kwargs)


def _files(files):
    names = list(files)
    if not names or len(names) != len(set(names)) or any(
            not isinstance(name, str) or Path(name).is_absolute() or ".." in Path(name).parts for name in names):
        raise ValueError("Invalid managed output list")
    return names


def output_hashes(output, files):
    output = Path(output)
    return {name: {"size": (output / name).stat().st_size, "sha256": digest(output / name)}
            for name in _files(files)}


def verify_report(output, reports, files):
    report = read_json(Path(reports) / "pipeline.json")
    if report["outputs"] != output_hashes(output, files):
        raise ValueError("Published output list, size or hash differs from pipeline report")
    return report


def is_current(output, reports, inputs, settings, files):
    try:
        report = verify_report(output, reports, files)
        return report["inputs"] == inputs and report["build_config"] == settings
    except (OSError, ValueError, KeyError, TypeError):
        return False


def publish(staged, output, reports, files, inputs, settings, summary):
    """Publish only a fully validated stage; report last allows rerun recovery."""
    staged, output, reports = map(Path, (staged, output, reports))
    names = _files(files)
    report = {"inputs": inputs, "build_config": settings, "summary": summary,
              "outputs": output_hashes(staged, names)}
    output.mkdir(parents=True, exist_ok=True)
    for name in names:
        (output / name).parent.mkdir(parents=True, exist_ok=True)
        os.replace(staged / name, output / name)
    atomic_json(reports / "pipeline.json", report)
    print(f"Published: {output}", flush=True)
    return report


def pmtiles_cli():
    tool = shutil.which("pmtiles") or shutil.which("go-pmtiles")
    if not tool:
        raise ValueError("Install pmtiles/go-pmtiles CLI before building offline tiles")
    return tool


def _tippecanoe(arguments, image):
    local = shutil.which("tippecanoe")
    if local:
        run([local, *arguments])
        return
    if not shutil.which("docker"):
        raise ValueError("tippecanoe or a working Docker daemon is required")
    run(["docker", "info"], stdout=subprocess.DEVNULL)
    if subprocess.run(["docker", "image", "inspect", image], stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL).returncode:
        run(["docker", "build", "-t", image, "-f", ROOT / "docker/Dockerfile.elevation", ROOT])
    paths = {str(Path(arguments[index + 1]).resolve().parent) for index, value in enumerate(arguments[:-1])
             if value == "--output"}
    # Input layer arguments are constructed by build_pmtiles below, not untrusted shell text.
    paths.update(str(Path(value.split(":", 1)[1]).resolve().parent)
                 for value in arguments if ":" in value and not value.startswith("--"))
    mounts = [part for path in sorted(paths) for part in ("-v", f"{path}:{path}")]
    run(["docker", "run", "--rm", "--user", f"{os.getuid()}:{os.getgid()}",
         *mounts, image, "tippecanoe", *arguments])


def validate_pmtiles(path, layers, metadata=None):
    tool = pmtiles_cli()
    run([tool, "verify", path], stdout=subprocess.DEVNULL)
    info = json.loads(run([tool, "show", "--metadata", path], capture_output=True, text=True).stdout)
    vectors = info.get("vector_layers", [])
    if isinstance(vectors, str):
        vectors = json.loads(vectors)
    if {item["id"] for item in vectors} != set(layers):
        raise ValueError("Unexpected PMTiles vector layers")
    header = json.loads(run([tool, "show", "--header-json", path], capture_output=True, text=True).stdout)
    west, south, east, north = header["bounds"]
    if not (131 < west <= east < 136 and 31.5 < south <= north < 35.5):
        raise ValueError("PMTiles bounds outside Shikoku")
    if metadata and any(info.get(key) != value for key, value in metadata.items()):
        raise ValueError("PMTiles source metadata mismatch")
    return info


def build_pmtiles(layers, destination, metadata, *, min_zoom=0, max_zoom=14,
                  no_line_simplification=True, drop_densest=True, image=IMAGE):
    destination = Path(destination).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    tool = pmtiles_cli()
    with tempfile.TemporaryDirectory(prefix=".tiles-", dir=destination.parent) as directory:
        work = Path(directory)
        mbtiles = work / "tiles.mbtiles"
        arguments = ["--quiet", "--force", "--output", str(mbtiles),
                     "--minimum-zoom", str(min_zoom), "--maximum-zoom", str(max_zoom)]
        if no_line_simplification:
            arguments.append("--no-line-simplification")
        if drop_densest:
            arguments.append("--drop-densest-as-needed")
        for layer, path in layers.items():
            arguments.extend(["-L", f"{layer}:{Path(path).resolve()}"])
        _tippecanoe(arguments, image)
        run([tool, "convert", mbtiles, destination])
        data = json.loads(run([tool, "show", "--metadata", destination], capture_output=True, text=True).stdout)
        data.update(metadata)
        atomic_json(work / "metadata.json", data)
        run([tool, "edit", "--metadata", work / "metadata.json", destination])
        validate_pmtiles(destination, layers, metadata)
    return destination
