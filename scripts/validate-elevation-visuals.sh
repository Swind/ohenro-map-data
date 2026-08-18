#!/usr/bin/env bash
# Strict validation for the elevation visualization PMTiles (spec §12).
# Exits 1 on any failure so the build pipeline never silently succeeds with
# broken artifacts. Used at the end of build-elevation-visuals.sh and by
# validate.sh when the artifacts exist.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"

CONTOURS="${1:-$ROOT/output/shikoku-contours.pmtiles}"
TERRAIN="${2:-$ROOT/output/shikoku-terrain.pmtiles}"
GOLDEN="${3:-$ROOT/gsi-dem/tests/golden/elevation.json}"

die() { echo "ERROR: $*" >&2; exit 1; }

[ -f "$CONTOURS" ] || die "contours PMTiles not found: $CONTOURS"
[ -f "$TERRAIN" ] || die "terrain PMTiles not found: $TERRAIN"

python3 "$SCRIPT_DIR/validate-elevation-visuals.py" \
  "$CONTOURS" "$TERRAIN" --golden "$GOLDEN"
