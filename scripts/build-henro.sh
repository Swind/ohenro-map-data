#!/usr/bin/env bash
# Build shikoku-henro.pmtiles from the local immutable source PBF
# using the custom Henro Planetiler profile.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"

HENRO_DIR="$ROOT/henro"
SOURCE_PBF="$ROOT/source/shikoku-latest.osm.pbf"
OUTPUT="$ROOT/output/shikoku-henro.pmtiles"
JAVA_MEM="${JAVA_MEM:--Xmx4g}"
LOG="$ROOT/reports/henro-build.log"

die() { echo "ERROR: $*" >&2; exit 1; }

command -v java >/dev/null 2>&1 || die "java not found (Java 21+ required)"
java -version 2>&1 | head -n1 | grep -q 'version "21' || die "Java 21+ required"
command -v mvn >/dev/null 2>&1 || die "mvn not found"
[ -f "$SOURCE_PBF" ] || die "source PBF not found: $SOURCE_PBF"

echo "==> Building Henro profile jar"
(cd "$HENRO_DIR" && mvn -q clean package)

JARS=("$HENRO_DIR"/target/*-with-deps.jar)
[ "${#JARS[@]}" -eq 1 ] && [ -f "${JARS[0]}" ] || die "expected exactly one *-with-deps.jar in $HENRO_DIR/target (found ${#JARS[@]})"
JAR="${JARS[0]}"

mkdir -p "$ROOT/output" "$ROOT/reports"

echo "==> Running Henro profile"
(cd "$HENRO_DIR" && java "$JAVA_MEM" -jar "$JAR" \
  --osm-path="$SOURCE_PBF" \
  --output="$OUTPUT") 2>&1 | tee "$LOG"

echo "==> Running smoke test (relation 13653654)"
python3 "$SCRIPT_DIR/smoke-test-henro.py" "$OUTPUT"

echo "==> Saving metadata report"
pmtiles show "$OUTPUT" > "$ROOT/reports/henro-metadata.txt"

echo "==> Done: $OUTPUT"
