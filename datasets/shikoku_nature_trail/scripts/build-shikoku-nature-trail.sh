#!/usr/bin/env bash
# Offline compatibility wrapper; all publication/validation lives in the pipeline.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$ROOT"
exec python3 -m datasets.shikoku_nature_trail build "$@"
