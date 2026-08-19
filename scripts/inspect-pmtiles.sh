#!/usr/bin/env bash
# Show PMTiles metadata for the basemap, henro, and elevation archives.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"

for f in output/shikoku-basemap.pmtiles output/shikoku-henro.pmtiles output/shikoku-contours.pmtiles output/shikoku-terrain.pmtiles output/shikoku-nature-trail.pmtiles; do
  path="$ROOT/$f"
  if [ -f "$path" ]; then
    echo "===== $f ====="
    pmtiles show "$path"
    echo
  else
    echo "===== $f (not built yet / skipped) ====="
  fi
done
