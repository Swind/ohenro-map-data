#!/usr/bin/env bash
# Preserve the local-build entry point; --update refreshes even on first use.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$ROOT"
COMMAND=build
if [ "${1:-}" = "--update" ]; then
  COMMAND=run
  shift
fi
exec python3 -m datasets.mizutani_henro_map "$COMMAND" "$@"
