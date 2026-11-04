#!/usr/bin/env bash
# Build shikoku-henro.pmtiles from the local immutable source PBF
# using the custom Henro Planetiler profile.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$ROOT"

HENRO_DIR="$ROOT/datasets/osm/henro"
SOURCE_PBF="${1:-$ROOT/datasets/osm/raw/shikoku-latest.osm.pbf}"
OUTPUT_DIR="${2:-$ROOT/datasets/osm/output}"
OUTPUT="$OUTPUT_DIR/shikoku-henro.pmtiles"
JAVA_MEM="${JAVA_MEM:--Xmx4g}"
REPORTS="${OSM_REPORTS_DIR:-$ROOT/datasets/osm/reports}"
LOG="$REPORTS/henro-build.log"

die() { echo "ERROR: $*" >&2; exit 1; }

command -v java >/dev/null 2>&1 || die "java not found (Java 21+ required)"
command -v mvn >/dev/null 2>&1 || die "mvn not found"
PMTILES="$(command -v pmtiles || command -v go-pmtiles || true)"
[ -n "$PMTILES" ] || die "pmtiles/go-pmtiles CLI not found"
[ -f "$SOURCE_PBF" ] || die "source PBF not found: $SOURCE_PBF"

echo "==> Building Henro profile jar"
(cd "$HENRO_DIR" && mvn -q package)

JARS=("$HENRO_DIR"/target/*-with-deps.jar)
[ "${#JARS[@]}" -eq 1 ] && [ -f "${JARS[0]}" ] || die "expected exactly one *-with-deps.jar in $HENRO_DIR/target (found ${#JARS[@]})"
JAR="${JARS[0]}"

mkdir -p "$OUTPUT_DIR" "$REPORTS"

echo "==> Running Henro profile"
(cd "$HENRO_DIR" && java "$JAVA_MEM" -jar "$JAR" \
  --osm-path="$SOURCE_PBF" \
  --output="$OUTPUT" --force) 2>&1 | tee "$LOG"

echo "==> Running smoke test (relation 13653654)"
"${PYTHON:-python3}" "$ROOT/datasets/osm/scripts/smoke-test-henro.py" "$OUTPUT"

echo "==> Saving metadata report"
"$PMTILES" show "$OUTPUT" > "$REPORTS/henro-metadata.txt"

echo "==> Done: $OUTPUT"
