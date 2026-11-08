#!/usr/bin/env bash
# Rebuild selected lodging sources through their validated source pipelines.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
TARGET="${1:-all}"
if [ "$#" -gt 0 ]; then shift; fi
case "$TARGET" in
  all|henroyado|min88) ;;
  *) echo "usage: $0 [all|henroyado|min88] [build options]" >&2; exit 2 ;;
esac
if [ "$TARGET" = all ] || [ "$TARGET" = henroyado ]; then
  python3 -m datasets.henroyado build "$@"
fi
if [ "$TARGET" = all ] || [ "$TARGET" = min88 ]; then
  python3 -m datasets.min88_lodging build "$@"
fi
