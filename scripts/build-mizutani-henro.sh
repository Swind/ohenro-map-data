#!/usr/bin/env bash
# Build the personal-use Mizutani Henro Guide Map overlay atomically.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"
DATA_DIR="$ROOT/source/mizutani-henro-map"
NORMALIZED="$ROOT/output/mizutani-henro-map.json"
ROUTES="$ROOT/output/mizutani-henro-routes.geojson"
POIS="$ROOT/output/mizutani-henro-pois.geojson"
REPORT="$ROOT/output/mizutani-henro-report.json"
OUTPUT="$ROOT/output/shikoku-mizutani-henro.pmtiles"
WORK_DIR="$ROOT/work/mizutani-henro-map"
REPORTS="$ROOT/reports"
IMAGE="${MIZUTANI_IMAGE:-ohenro-elevation-visuals:latest}"
LOG="$REPORTS/mizutani-henro-build.log"

die() { echo "ERROR: $*" >&2; exit 1; }
dockerrun() { docker run --rm --user "$(id -u):$(id -g)" -v "$ROOT:$ROOT" "$IMAGE" "$@"; }

command -v python3 >/dev/null 2>&1 || die "python3 not found"
[ -s "$DATA_DIR/current.json" ] || die "current KML snapshot missing; run fetch first"
mkdir -p "$ROOT/output" "$WORK_DIR" "$REPORTS"

case "${1:-}" in
  "") UPDATE=0 ;;
  --update) UPDATE=1 ;;
  *) die "usage: $0 [--update]" ;;
esac

if [ "$UPDATE" -eq 1 ]; then
  OLD_SNAPSHOT="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["sha256"])' "$DATA_DIR/current.json")"
  python3 -m mizutani_henro_map --data-dir "$DATA_DIR" fetch
  NEW_SNAPSHOT="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["sha256"])' "$DATA_DIR/current.json")"
  if [ "$OLD_SNAPSHOT" = "$NEW_SNAPSHOT" ]; then
    printf '==> Mizutani Henro Guide Map update\nsource unchanged: %s\n' "$NEW_SNAPSHOT" | tee "$LOG"
    exit 0
  fi
  python3 -m mizutani_henro_map --data-dir "$DATA_DIR" diff "$OLD_SNAPSHOT" "$NEW_SNAPSHOT" --output "$ROOT/output/mizutani-henro-update-report.json"
fi

PMTILES="$(command -v pmtiles || command -v go-pmtiles || true)"
[ -n "$PMTILES" ] || die "pmtiles or go-pmtiles CLI not found"
command -v docker >/dev/null 2>&1 || die "docker not found"
docker image inspect "$IMAGE" >/dev/null 2>&1 || die "docker image '$IMAGE' not found"

{
  echo "==> Mizutani Henro Guide Map build $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  python3 -m mizutani_henro_map --data-dir "$DATA_DIR" normalize --output "$NORMALIZED"
  python3 -m mizutani_henro_map export-map --input "$NORMALIZED" --routes "$ROUTES" --pois "$POIS" --report "$REPORT"
  python3 -m mizutani_henro_map --data-dir "$DATA_DIR" verify --normalized "$NORMALIZED" --routes "$ROUTES" --pois "$POIS"

  TMP="$WORK_DIR/shikoku-mizutani-henro.pmtiles"
  MBTILES="$WORK_DIR/mizutani-henro.mbtiles"
  META="$WORK_DIR/mizutani-henro.metadata.json"
  rm -f "$TMP" "$MBTILES"
  echo "==> tippecanoe"
  dockerrun tippecanoe --quiet --force --output "$MBTILES" --minimum-zoom 0 --maximum-zoom 14 \
    --drop-densest-as-needed --no-line-simplification \
    -L "mizutani_henro_routes:$ROUTES" -L "mizutani_henro_pois:$POIS"
  echo "==> PMTiles convert"
  "$PMTILES" convert "$MBTILES" "$TMP"
  "$PMTILES" show --metadata "$TMP" > "$META"
  python3 - "$META" "$NORMALIZED" <<'PY'
import json, sys
metadata_path, normalized_path = sys.argv[1:]
metadata = json.load(open(metadata_path, encoding="utf-8"))
source = json.load(open(normalized_path, encoding="utf-8"))["source"]
metadata.update({
    "name": "Mizutani Henro Guide Map",
    "description": "Offline derivative for personal use of お遍路のルート・おすすめ宿・お店・道しるべ・経験談",
    "attribution": "水谷遍路導覽圖 / Original map by 水谷卓也; source: https://min88.jp/photo/558/",
    "dataset_id": "mizutani-henro-map",
    "source_map_id": source["map_id"],
    "source_sha256": source["snapshot_sha256"],
    "source_url": source["map_url"],
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
if {layer["id"] for layer in layers} != {"mizutani_henro_routes", "mizutani_henro_pois"}:
    raise SystemExit("unexpected PMTiles layers")
west, south, east, north = header["bounds"]
if not (131 < west < east < 136 and 31.5 < south < north < 35.5):
    raise SystemExit("PMTiles bounds outside Shikoku: %r" % header["bounds"])
required = {"dataset_id", "source_map_id", "source_sha256", "source_url", "usage", "attribution"}
if any(not metadata.get(key) for key in required) or metadata["usage"] != "personal-use":
    raise SystemExit("required personal-use metadata missing")
PY
  "$SCRIPT_DIR/smoke-test-mizutani-henro.sh" "$TMP" "$ROUTES" "$POIS" "$IMAGE" "$PMTILES"
  mv -f "$TMP" "$OUTPUT"
  "$PMTILES" show "$OUTPUT" > "$REPORTS/mizutani-henro-metadata.txt"
  echo "==> Done: $OUTPUT"
} 2>&1 | tee "$LOG"
