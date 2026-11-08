#!/usr/bin/env bash
# Publish the complete validated derivative set from the selected source snapshot.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$ROOT"
exec python3 -m datasets.henrohub build "$@"
