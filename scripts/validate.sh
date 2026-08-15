#!/usr/bin/env bash
# Validate PMTiles outputs. Exit 1 on any failure.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"

BASEMAP="$ROOT/output/shikoku-basemap.pmtiles"
HENRO="$ROOT/output/shikoku-henro.pmtiles"

FAIL=0
fail() { echo "FAIL: $*" >&2; FAIL=1; }

command -v pmtiles >/dev/null 2>&1 || { echo "FAIL: pmtiles CLI not found" >&2; exit 1; }

# ---- Basemap ----
echo "==> Basemap: $BASEMAP"
[ -f "$BASEMAP" ] || fail "basemap pmtiles not found"
[ -s "$BASEMAP" ] || fail "basemap pmtiles is empty"

if [ -f "$BASEMAP" ]; then
  meta=$(pmtiles show --metadata "$BASEMAP" 2>/dev/null) || fail "basemap metadata unreadable"
  header=$(pmtiles show --header-json "$BASEMAP" 2>/dev/null) || fail "basemap header unreadable"

  echo "$header" | grep -q '"bounds"' || fail "basemap header missing bounds"
  b=$(echo "$header" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['bounds'])")
  # bounds must overlap Shikoku (roughly 131-136E, 32-35N)
  echo "$header" | python3 -c "
import json,sys
d=json.load(sys.stdin)
lon_min,lat_min,lon_max,lat_max=d['bounds']
ok = lon_min < 135.5 and lon_max > 131.0 and lat_min < 34.5 and lat_max > 32.0
sys.exit(0 if ok else 1)
" || fail "basemap bounds do not cover Shikoku: $b"

  echo "$meta" | python3 -c "
import json,sys
d=json.load(sys.stdin)
layers=json.loads(d['vector_layers']) if isinstance(d['vector_layers'],str) else d['vector_layers']
ids={l['id'] for l in layers}
required={'roads','water','buildings','places','pois'}
missing=required-ids
sys.exit(0 if not missing else 1)
" || fail "basemap missing required layers"
fi

# ---- Henro ----
echo "==> Henro: $HENRO"
if [ -f "$HENRO" ]; then
  [ -s "$HENRO" ] || fail "henro pmtiles is empty"

  meta=$(pmtiles show --metadata "$HENRO" 2>/dev/null) || fail "henro metadata unreadable"

  echo "$meta" | python3 -c "
import json,sys
d=json.load(sys.stdin)
layers=json.loads(d['vector_layers']) if isinstance(d['vector_layers'],str) else d['vector_layers']
ids={l['id'] for l in layers}
sys.exit(0 if 'henro_routes' in ids else 1)
" || fail "henro_routes layer missing"

  # TEMPORARY smoke-test rule: relation 13653654 must appear with metadata
  python3 "$SCRIPT_DIR/smoke-test-henro.py" "$HENRO" >/dev/null || fail "henro smoke test failed (relation 13653654)"
else
  echo "WARN: henro pmtiles not built yet, skipping henro checks"
fi

if [ "$FAIL" -eq 1 ]; then
  echo "==> VALIDATION FAILED"
  exit 1
fi
echo "==> VALIDATION PASSED"
