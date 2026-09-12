#!/usr/bin/env bash
# Build the Henro Hub (henro.app) route network overlay into a single PMTiles
# archive for personal use. Not part of the official pipeline.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"
ROUTES="$ROOT/output/henrohub-routes/henrohub-routes.geojson"
OUTPUT="$ROOT/output/shikoku-henrohub.pmtiles"
WORK_DIR="$ROOT/work/henrohub-pmtiles"
REPORTS="$ROOT/reports"
IMAGE="${HENROHUB_IMAGE:-ohenro-elevation-visuals:latest}"
LOG="$REPORTS/henrohub-pmtiles-build.log"

die() { echo "ERROR: $*" >&2; exit 1; }
dockerrun() {
  docker run --rm --user "$(id -u):$(id -g)" -v "$ROOT:$ROOT" "$IMAGE" "$@"
}

command -v python3 >/dev/null 2>&1 || die "python3 not found"
PMTILES="$(command -v pmtiles || command -v go-pmtiles || true)"
[ -n "$PMTILES" ] || die "pmtiles or go-pmtiles CLI not found"
command -v docker >/dev/null 2>&1 || die "docker not found"
docker image inspect "$IMAGE" >/dev/null 2>&1 || die "docker image '$IMAGE' not found"
[ -s "$ROUTES" ] || die "henrohub routes GeoJSON not found: $ROUTES"

mkdir -p "$ROOT/output" "$WORK_DIR" "$REPORTS"

{
  echo "==> Henro Hub route network build $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  TMP="$WORK_DIR/shikoku-henrohub.pmtiles"
  MBTILES="$WORK_DIR/henrohub.mbtiles"
  META="$WORK_DIR/henrohub.metadata.json"
  rm -f "$TMP" "$MBTILES"

  echo "==> tippecanoe"
  dockerrun tippecanoe --quiet --force --output "$MBTILES" \
    --minimum-zoom 0 --maximum-zoom 14 --drop-densest-as-needed \
    --no-line-simplification \
    -L "henrohub_routes:$ROUTES"

  echo "==> PMTiles convert"
  "$PMTILES" convert "$MBTILES" "$TMP"

  "$PMTILES" show --metadata "$TMP" > "$META"
  python3 - "$META" <<'PY'
import json, sys
metadata_path = sys.argv[1]
metadata = json.load(open(metadata_path, encoding="utf-8"))
metadata.update({
    "name": "Henro Hub Route Network",
    "description": "Offline derivative for personal use of Henro Hub (henro.app) route network",
    "attribution": "Henro Hub / https://henro.app",
    "dataset_id": "henrohub-routes",
    "source_url": "https://henro.app",
    "usage": "personal-use",
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
if layer_ids != ["henrohub_routes"]:
    raise SystemExit("henrohub PMTiles must contain exactly one vector layer 'henrohub_routes': %r" % layer_ids)
fields = layers[0].get("fields", {})
for field in ("route_id", "route_role", "route_class"):
    if field not in fields:
        raise SystemExit("henrohub_routes layer missing required field %r" % field)
west, south, east, north = header["bounds"]
if not (131 < west < east < 136 and 31.5 < south < north < 35.5):
    raise SystemExit("PMTiles bounds outside Shikoku: %r" % header["bounds"])
required = {"dataset_id", "source_url", "usage", "attribution"}
if any(not metadata.get(key) for key in required) or metadata["usage"] != "personal-use":
    raise SystemExit("required personal-use metadata missing")
PY

  mv -f "$TMP" "$OUTPUT"
  "$PMTILES" show "$OUTPUT" > "$REPORTS/henrohub-metadata.txt"
  echo "==> Done: $OUTPUT"
} 2>&1 | tee "$LOG"