#!/usr/bin/env bash
# Build the consolidated information-POI layer into a single PMTiles archive.
# The single `info_pois` layer carries `category` / `source` / `source_category`
# so the app can filter by point kind. Not part of the official pipeline.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$ROOT"
POIS="$ROOT/datasets/info_pois/output/pois.geojson"
REPORT="$ROOT/datasets/info_pois/output/pois-report.json"
OUTPUT="$ROOT/datasets/info_pois/output/shikoku-info-pois.pmtiles"
WORK_DIR="$ROOT/work/info-pois"
REPORTS="$ROOT/datasets/info_pois/reports"
IMAGE="${INFO_POIS_IMAGE:-ohenro-elevation-visuals:latest}"
LOG="$REPORTS/info-pois-build.log"

die() { echo "ERROR: $*" >&2; exit 1; }
dockerrun() {
  docker run --rm --user "$(id -u):$(id -g)" -v "$ROOT:$ROOT" "$IMAGE" "$@"
}

command -v python3 >/dev/null 2>&1 || die "python3 not found"
PMTILES="$(command -v pmtiles || command -v go-pmtiles || true)"
[ -n "$PMTILES" ] || die "pmtiles or go-pmtiles CLI not found"
command -v docker >/dev/null 2>&1 || die "docker not found"
docker image inspect "$IMAGE" >/dev/null 2>&1 || die "docker image '$IMAGE' not found"
[ -s "$POIS" ] || die "consolidated POIs GeoJSON not found: $POIS (run datasets/info_pois/scripts/build-info-pois.py first)"

mkdir -p "$ROOT/datasets/info_pois/output" "$WORK_DIR" "$REPORTS"

{
  echo "==> info-POI build $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  TMP="$WORK_DIR/shikoku-info-pois.pmtiles"
  MBTILES="$WORK_DIR/info-pois.mbtiles"
  META="$WORK_DIR/info-pois.metadata.json"
  rm -f "$TMP" "$MBTILES"

  echo "==> tippecanoe"
  dockerrun tippecanoe --quiet --force --output "$MBTILES" \
    --minimum-zoom 0 --maximum-zoom 14 --drop-densest-as-needed \
    -L "info_pois:$POIS"

  echo "==> PMTiles convert"
  "$PMTILES" convert "$MBTILES" "$TMP"

  "$PMTILES" show --metadata "$TMP" > "$META"
  python3 - "$META" "$REPORT" <<'PY'
import json, sys
metadata_path, report_path = sys.argv[1:]
metadata = json.load(open(metadata_path, encoding="utf-8"))
report = json.load(open(report_path, encoding="utf-8"))
metadata.update({
    "name": "Information POIs",
    "description": "Consolidated information POIs (temples/toilets/food/shops/transport/onsen/sights/wayfinding) with a unified category field",
    "attribution": "Multiple sources: Mizutani Henro Guide Map, 四国自然歩道, 88sekaiisan, arukihenro, OpenStreetMap (ODbL)",
    "dataset_id": "info-pois",
    "usage": "personal-use",
    "feature_count": report.get("feature_count"),
})
json.dump(metadata, open(metadata_path, "w", encoding="utf-8"), ensure_ascii=False)
PY
  "$PMTILES" edit --metadata="$META" "$TMP"
  "$PMTILES" verify "$TMP"

  python3 - "$("$PMTILES" show --metadata "$TMP")" "$("$PMTILES" show --header-json "$TMP")" <<'PY'
import json, sys
metadata, header = map(json.loads, sys.argv[1:])
layers = metadata["vector_layers"]
if isinstance(layers, str):
    layers = json.loads(layers)
layer_ids = [layer["id"] for layer in layers]
if layer_ids != ["info_pois"]:
    raise SystemExit("info-POI PMTiles must contain exactly one vector layer 'info_pois': %r" % layer_ids)
fields = layers[0].get("fields", {})
for field in ("poi_id", "category", "source", "source_category", "name"):
    if field not in fields:
        raise SystemExit("info_pois layer missing required field %r" % field)
if not metadata.get("feature_count"):
    raise SystemExit("missing feature_count metadata")
if metadata.get("usage") != "personal-use" or not metadata.get("attribution"):
    raise SystemExit("required personal-use metadata missing")
PY

  mv -f "$TMP" "$OUTPUT"
  "$PMTILES" show "$OUTPUT" > "$REPORTS/info-pois-metadata.txt"
  echo "==> Done: $OUTPUT"
} 2>&1 | tee "$LOG"