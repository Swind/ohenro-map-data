#!/usr/bin/env bash
# Build shikoku-basemap.pmtiles from the local immutable source PBF
# using the Protomaps Basemaps Planetiler profile.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$ROOT"

TILES_DIR="$ROOT/basemaps/tiles"
SOURCE_PBF="${1:-$ROOT/datasets/osm/raw/shikoku-latest.osm.pbf}"
OUTPUT_DIR="${2:-$ROOT/datasets/osm/output}"
OUTPUT="$OUTPUT_DIR/shikoku-basemap.pmtiles"
AREA=shikoku
JAVA_MEM="${JAVA_MEM:--Xmx8g}"
REPORTS="${OSM_REPORTS_DIR:-$ROOT/datasets/osm/reports}"
REPORT="$REPORTS/basemap-metadata.txt"
LOG="$REPORTS/basemap-build.log"

die() { echo "ERROR: $*" >&2; exit 1; }

command -v java >/dev/null 2>&1 || die "java not found (Java 21+ required)"
command -v mvn >/dev/null 2>&1 || die "mvn not found"
PMTILES="$(command -v pmtiles || command -v go-pmtiles || true)"
[ -n "$PMTILES" ] || die "pmtiles/go-pmtiles CLI not found"
[ -f "$SOURCE_PBF" ] || die "source PBF not found: $SOURCE_PBF"

if [ ! -f "$TILES_DIR/pom.xml" ]; then
  git submodule update --init -- basemaps
fi
echo "==> Building Protomaps profile jar"
(cd "$TILES_DIR" && mvn -q -DskipTests package)

JARS=("$TILES_DIR"/target/*-with-deps.jar)
[ "${#JARS[@]}" -eq 1 ] && [ -f "${JARS[0]}" ] || die "expected exactly one *-with-deps.jar in $TILES_DIR/target (found ${#JARS[@]})"
JAR="${JARS[0]}"

mkdir -p "$TILES_DIR/data/sources" "$OUTPUT_DIR" "$REPORTS"
"${PYTHON:-python3}" -m datasets.osm.coastlines \
  --sources-dir "$TILES_DIR/data/sources" --reports-dir "$REPORTS"

# Copy (not symlink) the immutable local PBF so Planetiler's --download
# sees the file as present and does not fetch a fresh copy from Geofabrik.
cp -f "$SOURCE_PBF" "$TILES_DIR/data/sources/$AREA.osm.pbf"

echo "==> Building basemap ($AREA) with $JAR"
(cd "$TILES_DIR" && java "$JAVA_MEM" -jar "$JAR" --area="$AREA" --download --force) 2>&1 | tee "$LOG"

echo "==> Moving result to $OUTPUT"
mv -f "$TILES_DIR/$AREA.pmtiles" "$OUTPUT"

echo "==> Saving metadata report"
"$PMTILES" show "$OUTPUT" > "$REPORT"

echo "==> Done: $OUTPUT"
