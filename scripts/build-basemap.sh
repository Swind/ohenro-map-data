#!/usr/bin/env bash
# Build shikoku-basemap.pmtiles from the local immutable source PBF
# using the Protomaps Basemaps Planetiler profile.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"

TILES_DIR="$ROOT/basemaps/tiles"
SOURCE_PBF="$ROOT/source/shikoku-latest.osm.pbf"
OUTPUT_DIR="$ROOT/output"
OUTPUT="$OUTPUT_DIR/shikoku-basemap.pmtiles"
AREA="${AREA:-shikoku}"
JAVA_MEM="${JAVA_MEM:--Xmx8g}"
REPORT="$ROOT/reports/basemap-metadata.txt"
LOG="$ROOT/reports/basemap-build.log"

die() { echo "ERROR: $*" >&2; exit 1; }

command -v java >/dev/null 2>&1 || die "java not found (Java 21+ required)"
java -version 2>&1 | head -n1 | grep -q 'version "21' || die "Java 21+ required"
command -v pmtiles >/dev/null 2>&1 || die "pmtiles CLI not found"
[ -f "$SOURCE_PBF" ] || die "source PBF not found: $SOURCE_PBF"

JARS=("$TILES_DIR"/target/*-with-deps.jar)
[ "${#JARS[@]}" -eq 1 ] && [ -f "${JARS[0]}" ] || die "expected exactly one *-with-deps.jar in $TILES_DIR/target (found ${#JARS[@]})"
JAR="${JARS[0]}"

mkdir -p "$TILES_DIR/data/sources" "$OUTPUT_DIR" "$ROOT/reports"

# Copy (not symlink) the immutable local PBF so Planetiler's --download
# sees the file as present and does not fetch a fresh copy from Geofabrik.
cp -f "$SOURCE_PBF" "$TILES_DIR/data/sources/$AREA.osm.pbf"

echo "==> Building basemap ($AREA) with $JAR"
(cd "$TILES_DIR" && java "$JAVA_MEM" -jar "$JAR" --area="$AREA" --download --force) 2>&1 | tee "$LOG"

echo "==> Moving result to $OUTPUT"
mv -f "$TILES_DIR/$AREA.pmtiles" "$OUTPUT"

echo "==> Saving metadata report"
pmtiles show "$OUTPUT" > "$REPORT"

echo "==> Done: $OUTPUT"
