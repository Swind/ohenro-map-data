"""Build and retain genuine, source-addressed Protomaps OSM POI archives."""

from contextlib import ExitStack
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

from datasets import _pipeline as shared
from datasets.osm import __main__ as osm

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = "shikoku-osm-pois.pmtiles"
AUXILIARY = {
    "qrank.csv.gz": "https://qrank.toolforge.org/download/qrank.csv.gz",
    "pgf-encoding.zip": "https://wipfli.github.io/pgf-encoding/pgf-encoding.zip",
}
# The consumer reads only z15. Building just that zoom also keeps the archive
# header truthful when the POI profile emits no low-zoom features.
ARGUMENTS = ("--area=shikoku", "--layer=pois", "--minzoom=15", "--maxzoom=15",
             "--download", "--force")


def _identity(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _profile_source(tiles):
    files = [tiles / "pom.xml", *sorted((tiles / "src/main").rglob("*"))]
    return {
        "repository": "https://github.com/protomaps/basemaps",
        "commit": subprocess.check_output(
            ["git", "-C", str(tiles.parent), "rev-parse", "HEAD"], text=True).strip(),
        "files": {str(path.relative_to(tiles)): shared.digest(path) for path in files if path.is_file()},
    }


def _profile(tiles, cache):
    if not (tiles / "pom.xml").is_file():
        shared.run(["git", "submodule", "update", "--init", "--", "basemaps"])
    source = _profile_source(tiles)
    record = cache / "profile-build.json"
    jars = sorted((tiles / "target").glob("*-with-deps.jar"))
    try:
        previous = shared.read_json(record)
        if (len(jars) == 1 and previous["source"] == source
                and previous["jar_sha256"] == shared.digest(jars[0])):
            return jars[0], {"source": source, "jar_sha256": previous["jar_sha256"]}
    except (OSError, ValueError, KeyError, TypeError):
        pass
    # Establish the source/binary relationship once; timestamps alone cannot do that.
    subprocess.run(["mvn", "-q", "-DskipTests", "clean", "package"], cwd=tiles, check=True)
    jars = sorted((tiles / "target").glob("*-with-deps.jar"))
    if len(jars) != 1:
        raise ValueError("Expected exactly one Protomaps *-with-deps.jar")
    if _profile_source(tiles) != source:
        raise ValueError("Protomaps source changed during Maven build")
    profile = {"source": source, "jar_sha256": shared.digest(jars[0])}
    shared.atomic_json(record, profile)
    return jars[0], profile


def _auxiliary(tiles):
    sources = tiles / "data/sources"
    sources.mkdir(parents=True, exist_ok=True)
    for name, url in AUXILIARY.items():
        destination = sources / name
        if destination.is_file() and destination.stat().st_size:
            continue
        with tempfile.TemporaryDirectory(prefix=".info-download-", dir=sources) as temporary:
            candidate = Path(temporary) / name
            osm.download(url, candidate)
            if name.endswith(".gz"):
                with gzip.open(candidate, "rt") as stream:
                    if stream.readline().strip() != "Entity,QRank":
                        raise ValueError("Invalid QRank download")
            else:
                with zipfile.ZipFile(candidate) as archive:
                    if not archive.namelist() or archive.testzip() is not None:
                        raise ValueError("Invalid font/encoding download")
            os.replace(candidate, destination)


def _descriptor(pbf, tiles, jar, profile, memory):
    return {
        "format": 1,
        "builder_sha256": shared.digest(__file__),
        "source": {"type": "OpenStreetMap PBF", "path": str(pbf),
                   "upstream_url": osm.URL, "sha256": shared.digest(pbf)},
        "profile": profile,
        "jar_sha256": shared.digest(jar),
        "auxiliary": {name: {"url": url, "sha256": shared.digest(tiles / "data/sources" / name)}
                      for name, url in AUXILIARY.items()},
        "settings": {"java_memory": memory, "arguments": list(ARGUMENTS)},
    }


def _validate(path):
    import mapbox_vector_tile
    from google.protobuf.message import DecodeError
    from pmtiles.reader import MmapSource, Reader, all_tiles
    from pmtiles.tile import Compression, TileType

    shared.validate_pmtiles(path, {"pois"})
    kinds = set()
    count = tiles = maximum_count = 0
    with path.open("rb") as handle:
        source = MmapSource(handle)
        header = Reader(source).header()
        if header["tile_type"] != TileType.MVT:
            raise ValueError("OSM POI archive is not vector tiles")
        if header["min_zoom"] != 15 or header["max_zoom"] != 15:
            raise ValueError("OSM POI extraction requires the complete z15 layer")
        if not (header["min_lon_e7"] < header["max_lon_e7"]
                and header["min_lat_e7"] < header["max_lat_e7"]):
            raise ValueError("OSM POI archive has empty bounds")
        for (zoom, _x, _y), data in all_tiles(source):
            if header["tile_compression"] == Compression.GZIP:
                data = gzip.decompress(data)
            elif header["tile_compression"] != Compression.NONE:
                raise ValueError("Unsupported OSM POI tile compression")
            try:
                decoded = mapbox_vector_tile.decode(data)
            except DecodeError as error:
                raise ValueError("Invalid OSM POI vector tile") from error
            if set(decoded) != {"pois"}:
                raise ValueError("OSM POI tile contains unexpected layers")
            tiles += 1
            for feature in decoded["pois"]["features"]:
                kind = feature["properties"].get("kind")
                if not isinstance(kind, str) or not kind.strip():
                    raise ValueError("OSM POI feature has no kind")
                if feature["geometry"]["type"] not in {"Point", "MultiPoint"}:
                    raise ValueError("OSM POI feature is not a point")
                kinds.add(kind)
                count += 1
                maximum_count += zoom == header["max_zoom"]
    if not tiles or not count or not maximum_count:
        raise ValueError("OSM POI archive is empty at its declared maximum zoom")
    return {"tiles": tiles, "features_with_zoom_duplicates": count, "kinds": sorted(kinds)}


def _cached(directory, descriptor):
    try:
        report = shared.read_json(directory / "provenance.json")
        archive = directory / ARCHIVE
        if report["descriptor"] != descriptor or report["artifact"] != {
                "sha256": shared.digest(archive), "size": archive.stat().st_size}:
            return False
        return report["validation"] == _validate(archive)
    except (OSError, ValueError, KeyError, TypeError, EOFError, RuntimeError,
            subprocess.CalledProcessError):
        return False


def _normalize_center(path):
    # Planetiler chooses an overview zoom from regional bounds, even for a
    # z15-only archive. Keep its location but make the viewing zoom valid.
    cli = shared.pmtiles_cli()
    header = json.loads(shared.run(
        [cli, "show", "--header-json", path], capture_output=True, text=True).stdout)
    header["center"][2] = 15
    with tempfile.TemporaryDirectory(prefix=".header-", dir=path.parent) as temporary:
        selected = Path(temporary) / "header.json"
        shared.atomic_json(selected, header)
        shared.run([cli, "edit", "--header-json", selected, path], capture_output=True, text=True)


def _build(pbf, tiles, jar, destination, memory):
    sources = tiles / "data/sources"
    with tempfile.TemporaryDirectory(prefix=".info-pbf-", dir=sources) as temporary:
        candidate = Path(temporary) / "shikoku.osm.pbf"
        shutil.copyfile(pbf, candidate)
        if shared.digest(candidate) != shared.digest(pbf):
            raise ValueError("OSM PBF changed while copying")
        os.replace(candidate, sources / "shikoku.osm.pbf")
    subprocess.run(["java", memory, "-jar", str(jar), *ARGUMENTS, f"--output={destination}"],
                   cwd=tiles, check=True)
    _normalize_center(destination)


def resolve(raw_dir: Path, datasets_dir: Path, refresh: bool = False) -> Path:
    """Return a validated immutable POI-only archive for the current local OSM PBF.

    Only ``refresh=True`` fetches OSM. It is supported for this repository's
    default datasets root; auxiliary profile downloads may be needed on first use.
    """
    raw_dir, datasets_dir = Path(raw_dir).resolve(), Path(datasets_dir).resolve()
    default_datasets = ROOT / "datasets"
    if refresh and datasets_dir != default_datasets:
        raise ValueError("OSM refresh requires the default datasets root; use local/build for custom inputs")
    cache = raw_dir / "osm-pois"
    cache.mkdir(parents=True, exist_ok=True)
    tiles = ROOT / "basemaps/tiles"
    pbf = datasets_dir / "osm/raw/shikoku-latest.osm.pbf"
    # Both custom PBF publication and the repository-wide Planetiler workspace matter.
    locks = sorted({default_datasets / "osm/.pipeline.lock", datasets_dir / "osm/.pipeline.lock"})
    with ExitStack() as stack:
        for path in locks:
            path.parent.mkdir(parents=True, exist_ok=True)
            lock = stack.enter_context(path.open("a"))
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError("Another OSM pipeline is already running") from None
        if refresh:
            shared.run(["python3", "-m", "datasets.osm", "fetch"])
        osm.validate_pbf(pbf)
        jar, profile = _profile(tiles, cache)
        _auxiliary(tiles)
        memory = os.environ.get("JAVA_MEM", "-Xmx8g")
        descriptor = _descriptor(pbf, tiles, jar, profile, memory)
        destination = cache / _identity(descriptor)
        if _cached(destination, descriptor):
            if (_descriptor(pbf, tiles, jar, profile, memory) != descriptor
                    or _profile_source(tiles) != profile["source"]):
                raise ValueError("OSM source/profile inputs changed while checking cache")
            return destination / ARCHIVE
        with tempfile.TemporaryDirectory(prefix=".build-", dir=cache) as temporary:
            stage = Path(temporary)
            candidate = stage / "candidate"
            candidate.mkdir()
            archive = candidate / ARCHIVE
            _build(pbf, tiles, jar, archive, memory)
            validation = _validate(archive)
            if (_descriptor(pbf, tiles, jar, profile, memory) != descriptor
                    or _profile_source(tiles) != profile["source"]):
                raise ValueError("OSM source/profile inputs changed during build; archive not promoted")
            shared.atomic_json(candidate / "provenance.json", {
                "descriptor": descriptor,
                "artifact": {"sha256": shared.digest(archive), "size": archive.stat().st_size},
                "validation": validation,
            })
            # Never remove a rejected cache until its fully validated replacement exists.
            rejected = stage / "rejected"
            if destination.exists():
                os.replace(destination, rejected)
            try:
                os.replace(candidate, destination)
            except OSError:
                if rejected.exists():
                    os.replace(rejected, destination)
                raise
        return destination / ARCHIVE
