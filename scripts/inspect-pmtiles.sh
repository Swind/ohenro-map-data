#!/usr/bin/env bash
# Show PMTiles metadata for the basemap, henro, and elevation archives.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"

for f in datasets/osm/output/shikoku-basemap.pmtiles datasets/osm/output/shikoku-henro.pmtiles datasets/gsi/output/shikoku-contours.pmtiles datasets/gsi/output/shikoku-terrain.pmtiles datasets/shikoku_nature_trail/output/shikoku-nature-trail.pmtiles datasets/henroyado/output/shikoku-henroyado-lodging.pmtiles datasets/min88_lodging/output/shikoku-min88-lodging.pmtiles; do
  path="$ROOT/$f"
  if [ -f "$path" ]; then
    echo "===== $f ====="
    pmtiles show "$path"
    echo
  else
    echo "===== $f (not built yet / skipped) ====="
  fi
done
