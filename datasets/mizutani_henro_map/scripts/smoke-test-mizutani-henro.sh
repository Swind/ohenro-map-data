#!/usr/bin/env bash
# Confirm one route and one POI from every category can be decoded from PMTiles.
set -euo pipefail

PMTILES_ARCHIVE="${1:?PMTiles path required}"
ROUTES="${2:?routes GeoJSON path required}"
POIS="${3:?POIs GeoJSON path required}"
IMAGE="${4:?Docker image required}"
PMTILES="${5:?pmtiles CLI required}"
WORK_DIR="$(dirname "$PMTILES_ARCHIVE")"
TMP_DIR="$(mktemp -d "$WORK_DIR/.smoke.XXXXXX")"
trap 'rm -rf "$TMP_DIR"' EXIT

check_feature() {
  local layer="$1" category="$2" feature_id="$3" lon="$4" lat="$5" tile z x y decoded
  read -r z x y < <(python3 -c '
import math, sys
lon, lat = map(float, sys.argv[1:])
z = 14
n = 2 ** z
print(z, int((lon + 180) / 360 * n), int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n))
' "$lon" "$lat")
  tile="$TMP_DIR/$layer-$feature_id.mvt"
  "$PMTILES" tile "$PMTILES_ARCHIVE" "$z" "$x" "$y" > "$tile"
  decoded="$(docker run --rm -v "$TMP_DIR:$TMP_DIR:ro" "$IMAGE" ogrinfo -ro -al -geom=no "$tile")"
  case "$decoded" in *"Layer name: $layer"*"feature_id (String) = $feature_id"*) ;; *)
    echo "missing $layer feature_id=$feature_id in z$z/$x/$y" >&2; return 1 ;;
  esac
  if [ -n "$category" ]; then
    case "$decoded" in *"category (String) = $category"*) ;; *)
      echo "missing category=$category for feature_id=$feature_id" >&2; return 1 ;;
    esac
  fi
}

read -r route_id route_lon route_lat < <(jq -r '.features[0] | [.properties.feature_id, .geometry.coordinates[0][0], .geometry.coordinates[0][1]] | @tsv' "$ROUTES")
check_feature "mizutani_henro_routes" "" "$route_id" "$route_lon" "$route_lat"

while IFS=$'\t' read -r category feature_id lon lat; do
  check_feature "mizutani_henro_pois" "$category" "$feature_id" "$lon" "$lat"
done < <(jq -r '.features | group_by(.properties.category) | .[] | .[0] | [.properties.category, .properties.feature_id, .geometry.coordinates[0], .geometry.coordinates[1]] | @tsv' "$POIS")
