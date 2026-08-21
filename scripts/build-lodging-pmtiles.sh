#!/usr/bin/env bash
# Build separate Henroyado and min88 lodging point PMTiles archives offline.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"
WORK_DIR="$ROOT/work/lodging-pmtiles"
REPORTS="$ROOT/reports"
IMAGE="${LODGING_IMAGE:-ohenro-elevation-visuals:latest}"
TARGET="${1:-all}"

die() { echo "ERROR: $*" >&2; exit 1; }
dockerrun() { docker run --rm --user "$(id -u):$(id -g)" -v "$ROOT:$ROOT" "$IMAGE" "$@"; }

case "$TARGET" in all|henroyado|min88) ;; *) die "usage: $0 [all|henroyado|min88]" ;; esac
command -v python3 >/dev/null 2>&1 || die "python3 not found"
command -v pmtiles >/dev/null 2>&1 || die "pmtiles CLI not found"
command -v docker >/dev/null 2>&1 || die "docker not found"
docker image inspect "$IMAGE" >/dev/null 2>&1 || die "docker image '$IMAGE' not found"
mkdir -p "$ROOT/output" "$WORK_DIR" "$REPORTS"

build() {
  local provider="$1" geojson="$2" output="$3" attribution="$4"
  local mbtiles="$WORK_DIR/$provider.mbtiles" metadata="$WORK_DIR/$provider.metadata.json"
  [ -s "$geojson" ] || die "$provider GeoJSON is empty: $geojson"
  echo "==> tippecanoe $provider"
  dockerrun tippecanoe --quiet --force --output "$mbtiles" --minimum-zoom 6 --maximum-zoom 14 \
    --drop-densest-as-needed -L "lodging:$geojson"
  pmtiles convert "$mbtiles" "$output"
  pmtiles show --metadata "$output" > "$metadata" 2>/dev/null
  python3 - "$metadata" "$attribution" <<'PY'
import json, sys
path, attribution = sys.argv[1:]
with open(path, encoding="utf-8") as handle:
    metadata = json.load(handle)
metadata["attribution"] = attribution
with open(path, "w", encoding="utf-8") as handle:
    json.dump(metadata, handle, ensure_ascii=False)
PY
  pmtiles edit --metadata "$metadata" "$output" 2>/dev/null
  python3 - "$(pmtiles show --metadata "$output" 2>/dev/null)" "$(pmtiles show --header-json "$output" 2>/dev/null)" <<'PY'
import json, sys
metadata, header = map(json.loads, sys.argv[1:])
layers = metadata["vector_layers"]
if isinstance(layers, str):
    layers = json.loads(layers)
if {layer["id"] for layer in layers} != {"lodging"}:
    raise SystemExit("expected one lodging layer")
west, south, east, north = header["bounds"]
if not (131 < west < east < 136 and 31.5 < south < north < 35.5):
    raise SystemExit("PMTiles bounds outside Shikoku: %r" % header["bounds"])
PY
  pmtiles show "$output" > "$REPORTS/$provider-lodging-metadata.txt"
  echo "==> Done: $output"
}

{
  echo "==> lodging PMTiles build $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  if [ "$TARGET" = all ] || [ "$TARGET" = henroyado ]; then
    HENROYADO_GEOJSON="$ROOT/output/henroyado/map.geojson"
    python3 -m henroyado export-map "$ROOT/output/henroyado/v1-geocoded.jsonl" --output "$HENROYADO_GEOJSON"
    build henroyado "$HENROYADO_GEOJSON" "$ROOT/output/shikoku-henroyado-lodging.pmtiles" \
      "Henroyado lodging data © henroyado.com"
  fi
  if [ "$TARGET" = all ] || [ "$TARGET" = min88 ]; then
    MIN88_GEOJSON="$ROOT/output/min88-lodging/map.geojson"
    python3 -m min88_lodging export-map "$ROOT/output/min88-lodging/v1-geocoded.jsonl" --output "$MIN88_GEOJSON"
    build min88 "$MIN88_GEOJSON" "$ROOT/output/shikoku-min88-lodging.pmtiles" \
      "min88 lodging data © min88.jp"
  fi
} 2>&1 | tr '\r' '\n' | sed 's/[[:space:]]*$//' | tee "$REPORTS/lodging-pmtiles-build.log"
