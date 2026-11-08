#!/usr/bin/env bash
# Build and validate all consolidated POI outputs from selected local inputs.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$ROOT"
exec python3 -m datasets.info_pois build "$@"
