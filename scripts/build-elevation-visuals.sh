#!/usr/bin/env bash
# Build elevation visualization artifacts (contours + terrain RGB) from the
# DEM10-only SQLite database, following docs/elevation_visualization_pipeline.md.
#
# All GDAL / tippecanoe / rio-rgbify steps run inside the Docker image
# ohenro-elevation-visuals (see docker/Dockerfile.elevation) so nothing is
# installed on the host. The Rust exporter (cargo run -- export-vrt) and the
# pmtiles CLI run natively.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"

ELEVATION_DB="${ELEVATION_DB:-$ROOT/output/shikoku-elevation-dem10.sqlite}"
WORK_DIR="${WORK_DIR:-$ROOT/work/elevation}"
CONTOUR_INTERVAL="${CONTOUR_INTERVAL:-20}"
TERRAIN_MIN_ZOOM="${TERRAIN_MIN_ZOOM:-6}"
TERRAIN_MAX_ZOOM="${TERRAIN_MAX_ZOOM:-14}"
RGBIFY_WORKERS="${RGBIFY_WORKERS:-4}"
IMAGE="${ELEVATION_IMAGE:-ohenro-elevation-visuals}"
OUTPUT="$ROOT/output"
REPORTS="$ROOT/reports"
LOG="$REPORTS/elevation-visuals-build.log"

# SRS for the exported geographic raster (JGD2024 geographic 2D = EPSG:6668).
SRS="EPSG:6668"

die() { echo "ERROR: $*" >&2; exit 1; }

# Run a tool inside the elevation-visuals image, mounting the repo at the same
# absolute path (so paths inside the container match the host) and writing as
# the invoking user (no root-owned artifacts).
dockerrun() {
  docker run --rm --user "$(id -u):$(id -g)" -v "$ROOT:$ROOT" "$IMAGE" "$@"
}

# ---- Preflight ----
command -v cargo >/dev/null 2>&1 || die "cargo not found"
command -v pmtiles >/dev/null 2>&1 || die "pmtiles CLI not found"
command -v docker >/dev/null 2>&1 || die "docker not found"
docker image inspect "$IMAGE" >/dev/null 2>&1 || \
  die "docker image '$IMAGE' not found; build it with: docker build -t $IMAGE -f docker/Dockerfile.elevation ."

[ -f "$ELEVATION_DB" ] || die "DEM10-only SQLite not found: $ELEVATION_DB"
[ -s "$ELEVATION_DB" ] || die "DEM10-only SQLite is empty: $ELEVATION_DB"

mkdir -p "$WORK_DIR" "$OUTPUT" "$REPORTS"

{
echo "==> elevation-visuals build $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "==> DB: $ELEVATION_DB"
echo "==> contour interval: $CONTOUR_INTERVAL, terrain zoom ${TERRAIN_MIN_ZOOM}-${TERRAIN_MAX_ZOOM}"
echo

# ---- 1. Export raw + VRT from SQLite (Rust) ----
echo "==> export-vrt: $ELEVATION_DB -> $WORK_DIR/dem10.vrt"
cargo run --manifest-path "$ROOT/gsi-dem/Cargo.toml" --release -- export-vrt \
  "$ELEVATION_DB" --layer 10 --output "$WORK_DIR/dem10.vrt" --srs "$SRS" --force

# ---- 2. GeoTIFF / COG ----
echo "==> gdal_translate COG"
dockerrun gdal_translate \
  -of COG \
  -ot Int16 \
  -a_nodata -32768 \
  -co COMPRESS=ZSTD \
  -co BLOCKSIZE=256 \
  -co BIGTIFF=IF_SAFER \
  "$WORK_DIR/dem10.vrt" \
  "$WORK_DIR/dem10.tif"

# ---- 3. Validate COG (spec §7) ----
echo "==> gdalinfo COG validation"
dockerrun gdalinfo -json "$WORK_DIR/dem10.tif" > "$WORK_DIR/dem10-info.json"
python3 - "$WORK_DIR/dem10-info.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
band = d["bands"][0]
assert band["type"] == "Int16", band["type"]
gt = d["geoTransform"]
assert gt[5] < 0, "pixel Y size must be negative (north-up)"
coords = d["wgs84Extent"]["coordinates"][0]
lons = [c[0] for c in coords]
lats = [c[1] for c in coords]
lon_min, lon_max = min(lons), max(lons)
lat_min, lat_max = min(lats), max(lats)
assert lon_min < 135.5 and lon_max > 131.0 and lat_min < 34.5 and lat_max > 32.0, (lon_min, lat_min, lon_max, lat_max)
print(f"  COG ok: Int16, north-up, bounds cover Shikoku ({lon_min},{lat_min})-({lon_max},{lat_max})")
PY

# ---- 4. Contours ----
echo "==> gdal_contour"
dockerrun gdal_contour \
  -f GeoJSONSeq \
  -i "$CONTOUR_INTERVAL" \
  -a elevation_m \
  -snodata -32768 \
  "$WORK_DIR/dem10.tif" \
  "$WORK_DIR/contours.geojsonseq"

# ---- 5. Tippecanoe contours ----
echo "==> tippecanoe contours"
dockerrun tippecanoe \
  --force \
  --output "$WORK_DIR/contours.mbtiles" \
  --layer contours \
  --minimum-zoom 12 \
  --maximum-zoom 15 \
  --drop-densest-as-needed \
  --extend-zooms-if-still-dropping \
  "$WORK_DIR/contours.geojsonseq"

# ---- 6. Warp to Web Mercator for the terrain tiler ----
# rio-rgbify 1.4.4 rejects projected input and drops NODATA transparency, so
# scripts/rgbify_dem.py reuses rio-rgbify's RGB encoder but tiles the warped
# EPSG:3857 COG with windowed reads and writes RGBA (alpha=0 over NODATA).
echo "==> gdalwarp EPSG:3857"
dockerrun gdalwarp \
  -overwrite \
  -t_srs EPSG:3857 \
  -r bilinear \
  -srcnodata -32768 \
  -dstnodata -32768 \
  -multi \
  -wo NUM_THREADS=ALL_CPUS \
  -co TILED=YES \
  -co COMPRESS=ZSTD \
  -co BIGTIFF=IF_SAFER \
  "$WORK_DIR/dem10.tif" \
  "$WORK_DIR/dem10-3857.tif"

# ---- 7. Terrain-RGB (masked wrapper over rio-rgbify's encoder) ----
echo "==> rgbify_dem (terrain RGB, z${TERRAIN_MIN_ZOOM}-${TERRAIN_MAX_ZOOM})"
dockerrun python3 "$ROOT/scripts/rgbify_dem.py" \
  "$WORK_DIR/dem10-3857.tif" \
  "$WORK_DIR/terrain.mbtiles" \
  --min-z "$TERRAIN_MIN_ZOOM" \
  --max-z "$TERRAIN_MAX_ZOOM" \
  --base-val -10000 \
  --interval 0.1 \
  --workers "$RGBIFY_WORKERS"

# ---- 8. Convert MBTiles -> PMTiles ----
echo "==> pmtiles convert contours"
pmtiles convert \
  "$WORK_DIR/contours.mbtiles" \
  "$OUTPUT/shikoku-contours.pmtiles"

echo "==> pmtiles convert terrain"
pmtiles convert \
  "$WORK_DIR/terrain.mbtiles" \
  "$OUTPUT/shikoku-terrain.pmtiles"

# ---- 9. Metadata reports + attribution ----
echo "==> metadata reports"
pmtiles show "$OUTPUT/shikoku-contours.pmtiles" > "$REPORTS/contours-metadata.txt"
pmtiles show "$OUTPUT/shikoku-terrain.pmtiles" > "$REPORTS/terrain-metadata.txt"

# Write GSI attribution into both PMTiles metadata (spec §13: not only README).
ATTRIBUTION='<a href="https://maps.gsi.go.jp">国土地理院</a> (GSI)'
for f in shikoku-contours shikoku-terrain; do
  pmtiles show --metadata "$OUTPUT/$f.pmtiles" > "$WORK_DIR/$f.meta.json" 2>/dev/null
  python3 - "$WORK_DIR/$f.meta.json" "$ATTRIBUTION" <<'PY'
import json, sys
path, attribution = sys.argv[1], sys.argv[2]
meta = json.load(open(path))
meta["attribution"] = attribution
json.dump(meta, open(path, "w"))
PY
  pmtiles edit --metadata "$WORK_DIR/$f.meta.json" "$OUTPUT/$f.pmtiles" 2>/dev/null
done

# ---- 10. Strict validation (spec §12) ----
echo "==> validating elevation visualization artifacts"
"$SCRIPT_DIR/validate-elevation-visuals.sh" \
  "$OUTPUT/shikoku-contours.pmtiles" \
  "$OUTPUT/shikoku-terrain.pmtiles"

# ---- 11. Web preview build ----
if [ -f "$ROOT/map-preview/package.json" ]; then
  echo "==> npm build (map-preview)"
  npm --prefix "$ROOT/map-preview" run build
else
  echo "WARN: map-preview not present, skipping web build"
fi

echo "==> Done"
echo "  $OUTPUT/shikoku-contours.pmtiles"
echo "  $OUTPUT/shikoku-terrain.pmtiles"
} 2>&1 | tee "$LOG"
