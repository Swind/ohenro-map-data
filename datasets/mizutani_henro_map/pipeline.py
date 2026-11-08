"""Stage and publish the complete, personal-use Mizutani dataset."""

from __future__ import annotations

import gzip
import json
import os
from pathlib import Path
import re
import tempfile

from datasets import _pipeline as common
from . import config
from .diff import generate_update_report
from .export_map import export_map
from .normalize import _snapshot, normalize
from .parser import validate_source
from .verify import verify

DATASET = Path(__file__).resolve().parent
NORMALIZED = "mizutani-henro-map.json"
ROUTES = "mizutani-henro-routes.geojson"
POIS = "mizutani-henro-pois.geojson"
EXPORT_REPORT = "mizutani-henro-report.json"
DIFF = "mizutani-henro-update-report.json"
OVERLAY = "shikoku-mizutani-henro.pmtiles"
PROVIDER = "mizutani-henro-routes.pmtiles"
OUTPUTS = (NORMALIZED, ROUTES, POIS, EXPORT_REPORT, DIFF, OVERLAY, PROVIDER)


def source(raw, snapshot=None):
    raw = Path(raw)
    if snapshot is None:
        snapshot = common.read_json(raw / "current.json")["sha256"]
    if not isinstance(snapshot, str) or not re.fullmatch(r"[0-9a-f]{64}", snapshot):
        raise ValueError("Invalid snapshot SHA-256")
    selected, metadata, body = _snapshot(str(raw), snapshot)
    directory = raw / "snapshots" / selected
    if (common.digest(directory / "map.kml") != selected or metadata["sha256"] != selected or
            metadata["size"] != len(body) or metadata["map_id"] != config.MAP_ID or
            metadata["dataset_id"] != config.DATASET_ID):
        raise ValueError("Snapshot integrity or source identity mismatch")
    validate_source(body)
    return {"snapshot_sha256": selected,
            "metadata_sha256": common.digest(directory / "metadata.json")}


def settings(image):
    return {"code": common.code_hash(DATASET), "image": image, "min_zoom": 0, "max_zoom": 14,
            "no_line_simplification": True, "overlay_drop_densest": True,
            "provider_drop_densest": False}


def tile_metadata(normalized, provider=False):
    origin = normalized["source"]
    return {
        "name": "Mizutani Henro Route Pack (routes)" if provider else "Mizutani Henro Guide Map",
        "description": ("Offline route geometry for personal use of お遍路のルート" if provider else
                        "Offline derivative for personal use of お遍路のルート・おすすめ宿・お店・道しるべ・経験談"),
        "attribution": "水谷遍路導覽圖 / Original map by 水谷卓也; source: https://min88.jp/photo/558/",
        "dataset_id": config.DATASET_ID,
        "source_map_id": origin["map_id"], "source_sha256": origin["snapshot_sha256"],
        "source_url": origin["map_url"], "usage": "personal-use",
    }


def _tile_samples(path, samples):
    import mapbox_vector_tile
    import mercantile
    from pmtiles.reader import MmapSource, Reader

    with Path(path).open("rb") as stream:
        reader = Reader(MmapSource(stream))
        tiles = {}
        for layer, feature in samples:
            coordinate = feature["geometry"]["coordinates"]
            if feature["geometry"]["type"] == "LineString":
                coordinate = coordinate[0]
            tile = mercantile.tile(coordinate[0], coordinate[1], 14)
            key = (14, tile.x, tile.y)
            if key not in tiles:
                data = reader.get(*key)
                if not data:
                    raise ValueError(f"Missing representative z14 tile in {path.name}")
                if data.startswith(b"\x1f\x8b"):
                    data = gzip.decompress(data)
                tiles[key] = mapbox_vector_tile.decode(data)
            candidates = tiles[key].get(layer, {}).get("features", [])
            props = feature["properties"]
            found = [row for row in candidates if row["properties"].get("feature_id") == props["feature_id"]]
            if not found:
                raise ValueError(f"Missing representative {layer} feature {props['feature_id']}")
            allowed = {"Point"} if feature["geometry"]["type"] == "Point" else {"LineString", "MultiLineString"}
            if any(row["geometry"]["type"] not in allowed or not row["geometry"]["coordinates"] for row in found):
                raise ValueError(f"Incorrect consumer geometry in {path.name}")
            required = ("route_id", "segment_id") if layer != "mizutani_henro_pois" else ("category",)
            if any(row["properties"].get(name) != props[name] for row in found for name in required):
                raise ValueError(f"Incorrect consumer properties in {path.name}")


def validate_data(raw, output, inputs):
    output = Path(output)
    current = source(raw, inputs["snapshot_sha256"])
    if any(inputs[key] != value for key, value in current.items()):
        raise ValueError("Source metadata changed since build")
    checked = verify(str(raw), snapshot=inputs["snapshot_sha256"],
                     normalized_path=output / NORMALIZED, routes_path=output / ROUTES,
                     pois_path=output / POIS, report_path=output / EXPORT_REPORT)
    if not checked["ok"]:
        raise ValueError("; ".join(checked["errors"]))
    normalized = common.read_json(output / NORMALIZED)
    routes = common.read_json(output / ROUTES)["features"]
    pois = common.read_json(output / POIS)["features"]
    for provider, filename, layers in (
            (False, OVERLAY, {"mizutani_henro_routes", "mizutani_henro_pois"}),
            (True, PROVIDER, {"routes"})):
        info = common.validate_pmtiles(output / filename, layers, tile_metadata(normalized, provider))
        vectors = info["vector_layers"]
        if isinstance(vectors, str):
            vectors = json.loads(vectors)
        for layer in vectors:
            fields = layer.get("fields", {})
            required = ({"feature_id", "category"} if layer["id"] == "mizutani_henro_pois" else
                        {"feature_id", "route_id", "segment_id"})
            if not required.issubset(fields):
                raise ValueError(f"Missing consumer fields in {filename}: {layer['id']}")
    categories = {}
    for feature in pois:
        categories.setdefault(feature["properties"]["category"], feature)
    _tile_samples(output / OVERLAY, [("mizutani_henro_routes", routes[0])] +
                  [("mizutani_henro_pois", feature) for feature in categories.values()])
    _tile_samples(output / PROVIDER, [("routes", routes[0])])
    source(raw, inputs["diff_base_sha256"])
    with tempfile.TemporaryDirectory(prefix="mizutani-diff-") as directory:
        expected = generate_update_report(str(raw), inputs["diff_base_sha256"],
                                          inputs["snapshot_sha256"], str(Path(directory) / DIFF))
    if common.read_json(output / DIFF) != expected:
        raise ValueError("Snapshot diff does not match its immutable sources")
    return checked


def validate(raw, output, reports):
    report = common.verify_report(output, reports, OUTPUTS)
    summary = validate_data(raw, output, report["inputs"])
    if summary != report["summary"]:
        raise ValueError("Published validation summary mismatch")
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return summary


def build(raw, output, reports, *, force=False, image=None, previous_snapshot=None):
    raw, output, reports = map(Path, (raw, output, reports))
    image = image or os.environ.get("MIZUTANI_IMAGE", common.IMAGE)
    inputs = source(raw)
    previous = None
    try:
        candidate = common.read_json(reports / "pipeline.json")["inputs"]
        if isinstance(candidate, dict) and {"snapshot_sha256", "diff_base_sha256"} <= candidate.keys():
            previous = candidate
    except (OSError, ValueError, KeyError, TypeError):
        pass
    if previous and previous["snapshot_sha256"] == inputs["snapshot_sha256"]:
        baseline = previous["diff_base_sha256"]
    elif previous:
        baseline = previous["snapshot_sha256"]
    else:
        baseline = previous_snapshot or inputs["snapshot_sha256"]
        # Preserve a legacy diff's baseline when migrating its current source.
        if (output / DIFF).exists():
            try:
                legacy = common.read_json(output / DIFF)
                if legacy["new"]["sha256"] == inputs["snapshot_sha256"]:
                    candidate = legacy["old"]["sha256"]
                    source(raw, candidate)
                    baseline = candidate
            except (OSError, ValueError, KeyError, TypeError):
                print("Legacy diff is unusable; regenerating it from the selected source baseline", flush=True)
    source(raw, baseline)
    inputs["diff_base_sha256"] = baseline
    config_hashes = settings(image)
    if not force and common.is_current(output, reports, inputs, config_hashes, OUTPUTS):
        print("Inputs, settings and all output hashes unchanged; skipping build", flush=True)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".mizutani-build-", dir=output.parent) as directory:
        staged = Path(directory)
        normalized = normalize(str(raw), snapshot=inputs["snapshot_sha256"], output=staged / NORMALIZED)
        export_map(staged / NORMALIZED, routes_path=staged / ROUTES,
                   pois_path=staged / POIS, report_path=staged / EXPORT_REPORT)
        generate_update_report(str(raw), baseline, inputs["snapshot_sha256"], str(staged / DIFF))
        common.build_pmtiles({"mizutani_henro_routes": staged / ROUTES,
                              "mizutani_henro_pois": staged / POIS}, staged / OVERLAY,
                             tile_metadata(normalized), image=image)
        common.build_pmtiles({"routes": staged / ROUTES}, staged / PROVIDER,
                             tile_metadata(normalized, True), drop_densest=False, image=image)
        summary = validate_data(raw, staged, inputs)
        if settings(image) != config_hashes or source(raw) != {
                key: inputs[key] for key in ("snapshot_sha256", "metadata_sha256")}:
            raise ValueError("Source or build configuration changed during build; not published")
        common.publish(staged, output, reports, OUTPUTS, inputs, config_hashes, summary)
