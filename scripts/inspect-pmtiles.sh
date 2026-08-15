#!/usr/bin/env bash
# Show PMTiles metadata for the basemap and henro archives.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"

for f in output/shikoku-basemap.pmtiles output/shikoku-henro.pmtiles; do
  path="$ROOT/$f"
  if [ -f "$path" ]; then
    echo "===== $f ====="
    pmtiles show "$path"
    echo
  else
    echo "===== $f (not built yet) ====="
  fi
done
