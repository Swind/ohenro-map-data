#!/usr/bin/env bash
# Build official shikoku-nature-trail.com routes and POIs into one PMTiles archive.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"
ARCHIVE="$ROOT/source/shikoku-nature-trail"
NORMALIZED="$ROOT/output/shikoku-nature-trail.json"
ROUTES="$ROOT/output/shikoku-nature-trail.geojson"
POIS="$ROOT/output/shikoku-nature-trail-pois.geojson"
REPORT="$ROOT/output/shikoku-nature-trail-report.json"
OUTPUT="$ROOT/output/shikoku-nature-trail.pmtiles"
WORK_DIR="$ROOT/work/shikoku-nature-trail"
REPORTS="$ROOT/reports"
IMAGE="${TRAIL_IMAGE:-ohenro-elevation-visuals:latest}"
LOG="$REPORTS/shikoku-nature-trail-build.log"

die() { echo "ERROR: $*" >&2; exit 1; }
dockerrun() {
  docker run --rm --user "$(id -u):$(id -g)" -v "$ROOT:$ROOT" "$IMAGE" "$@"
}

command -v python3 >/dev/null 2>&1 || die "python3 not found"
command -v pmtiles >/dev/null 2>&1 || die "pmtiles CLI not found"
command -v docker >/dev/null 2>&1 || die "docker not found"
docker image inspect "$IMAGE" >/dev/null 2>&1 || die "docker image '$IMAGE' not found"
[ -s "$ARCHIVE/course-index.json" ] || die "official archive index not found: $ARCHIVE/course-index.json"
[ -d "$ARCHIVE/courses" ] || die "official archive courses not found: $ARCHIVE/courses"

mkdir -p "$ROOT/output" "$WORK_DIR" "$REPORTS"

{
echo "==> shikoku-nature-trail build $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "==> normalize official archive"
python3 -m shikoku_nature_trail --data-dir "$ARCHIVE" normalize --output "$NORMALIZED"

echo "==> export routes and POIs"
python3 -m shikoku_nature_trail export-map \
  --input "$NORMALIZED" --routes "$ROUTES" --pois "$POIS" --report "$REPORT"

python3 - "$NORMALIZED" "$REPORT" <<'PY'
import json, sys
normalized, report = (json.load(open(path, encoding="utf-8")) for path in sys.argv[1:])
if normalized["summary"]["warning_count"] != 0:
    raise SystemExit("normalized archive has warnings")
totals = report["totals"]
summary = normalized["summary"]
if totals["courses"] != summary["course_count"] or totals["route_ids"] != totals["courses"]:
    raise SystemExit("course/route accounting mismatch")
if totals["route_segments"] < totals["route_ids"]:
    raise SystemExit("route segment accounting mismatch")
if totals["route_coordinate_points"] < totals["route_segments"] * 2:
    raise SystemExit("route coordinate accounting mismatch")
if totals["photo_points"] != summary["photo_point_count"]:
    raise SystemExit("photo point accounting mismatch")
if totals["linked_tourism_spots"] + totals["unmatched_tourism_spots"] != summary["tourism_spot_count"]:
    raise SystemExit("tourism spot accounting mismatch")
PY

echo "==> tippecanoe"
dockerrun tippecanoe --quiet --force --output "$WORK_DIR/trail.mbtiles" \
  --minimum-zoom 0 --maximum-zoom 14 --drop-densest-as-needed \
  --no-line-simplification \
  -L "shikoku_nature_trail:$ROUTES" -L "shikoku_nature_trail_pois:$POIS"

echo "==> pmtiles convert"
pmtiles convert "$WORK_DIR/trail.mbtiles" "$OUTPUT"

ATTRIBUTION='Shikoku Nature Trail (四国自然歩道) © shikoku-nature-trail.com'
pmtiles show --metadata "$OUTPUT" > "$WORK_DIR/trail.meta.json" 2>/dev/null
python3 - "$WORK_DIR/trail.meta.json" "$ATTRIBUTION" <<'PY'
import json, sys
path, attribution = sys.argv[1], sys.argv[2]
with open(path, encoding="utf-8") as file:
    metadata = json.load(file)
metadata["attribution"] = attribution
with open(path, "w", encoding="utf-8") as file:
    json.dump(metadata, file, ensure_ascii=False)
PY
pmtiles edit --metadata "$WORK_DIR/trail.meta.json" "$OUTPUT" 2>/dev/null

metadata="$(pmtiles show --metadata "$OUTPUT" 2>/dev/null)"
header="$(pmtiles show --header-json "$OUTPUT" 2>/dev/null)"
python3 - "$metadata" "$header" <<'PY'
import json, sys
metadata, header = map(json.loads, sys.argv[1:])
layers = metadata["vector_layers"]
if isinstance(layers, str):
    layers = json.loads(layers)
ids = {layer["id"] for layer in layers}
required = {"shikoku_nature_trail", "shikoku_nature_trail_pois"}
if not required <= ids:
    raise SystemExit("missing PMTiles layers: %s" % sorted(required - ids))
west, south, east, north = header["bounds"]
if not (131 < west < east < 136 and 31.5 < south < north < 35.5):
    raise SystemExit("PMTiles bounds outside Shikoku: %r" % header["bounds"])
PY
pmtiles show "$OUTPUT" > "$REPORTS/shikoku-nature-trail-metadata.txt"
echo "==> Done: $OUTPUT"
} 2>&1 | tr '\r' '\n' | sed 's/[[:space:]]*$//' | tee "$LOG"
