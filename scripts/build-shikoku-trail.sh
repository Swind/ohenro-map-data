#!/usr/bin/env bash
# Build shikoku-trail.pmtiles from the official Shikoku Nature Trail KML/GPX
# files in source/shikoku_trail. Pipeline: KML -> GeoJSON (Python) ->
# tippecanoe (Docker ohenro-elevation-visuals, which bundles tippecanoe) ->
# PMTiles. Each <rte>/Placemark becomes a LineString feature with route_id /
# name / pref / kind / seg so the app can show or hide individual routes.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"

SRC_DIR="$ROOT/source/shikoku_trail"
GEOJSON="$ROOT/output/shikoku-trail.geojson"
REPORT="$ROOT/output/shikoku-trail-report.json"
OUTPUT="$ROOT/output/shikoku-trail.pmtiles"
WORK_DIR="$ROOT/work/shikoku-trail"
IMAGE="${TRAIL_IMAGE:-ohenro-elevation-visuals}"
LOG="$ROOT/reports/shikoku-trail-build.log"
REPORTS="$ROOT/reports"

die() { echo "ERROR: $*" >&2; exit 1; }

# Run a tool inside the elevation-visuals image (bundles tippecanoe), mounting
# the repo at the same absolute path and writing as the invoking user.
dockerrun() {
  docker run --rm --user "$(id -u):$(id -g)" -v "$ROOT:$ROOT" "$IMAGE" "$@"
}

command -v python3 >/dev/null 2>&1 || die "python3 not found"
command -v pmtiles >/dev/null 2>&1 || die "pmtiles CLI not found"
command -v docker >/dev/null 2>&1 || die "docker not found"
docker image inspect "$IMAGE" >/dev/null 2>&1 || \
  die "docker image '$IMAGE' not found; build it with: docker build -t $IMAGE -f docker/Dockerfile.elevation ."
[ -d "$SRC_DIR" ] || die "source dir not found: $SRC_DIR"
ls "$SRC_DIR"/*.kml >/dev/null 2>&1 || die "no KML files in $SRC_DIR"

mkdir -p "$WORK_DIR" "$REPORTS"

{
echo "==> shikoku-trail build $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo

# ---- 1. KML -> GeoJSON ----
echo "==> extract (KML -> GeoJSON)"
python3 "$ROOT/henro/scripts/extract_shikoku_trail.py" "$GEOJSON" "$REPORT"
echo

# ---- 2. tippecanoe -> MBTiles ----
# --no-line-simplification keeps the official geometry exact. z0-14 matches
# the henro overlay. --drop-densest-as-needed protects tile size limits.
echo "==> tippecanoe"
dockerrun tippecanoe \
  --force \
  --output "$WORK_DIR/trail.mbtiles" \
  --layer shikoku_trail \
  --minimum-zoom 0 \
  --maximum-zoom 14 \
  --drop-densest-as-needed \
  --no-line-simplification \
  "$GEOJSON"

# ---- 3. MBTiles -> PMTiles ----
echo "==> pmtiles convert"
pmtiles convert "$WORK_DIR/trail.mbtiles" "$OUTPUT"

# ---- 4. Attribution + metadata report ----
ATTRIBUTION='Shikoku Nature Trail (四国自然歩道) data (c) ranger-k.eco.coocan.jp, 2022'
pmtiles show --metadata "$OUTPUT" > "$WORK_DIR/trail.meta.json" 2>/dev/null
python3 - "$WORK_DIR/trail.meta.json" "$ATTRIBUTION" <<'PY'
import json, sys
path, attribution = sys.argv[1], sys.argv[2]
meta = json.load(open(path))
meta["attribution"] = attribution
json.dump(meta, open(path, "w"))
PY
pmtiles edit --metadata "$WORK_DIR/trail.meta.json" "$OUTPUT" 2>/dev/null

pmtiles show "$OUTPUT" > "$REPORTS/shikoku-trail-metadata.txt"

echo "==> Done: $OUTPUT"
} 2>&1 | tee "$LOG"
