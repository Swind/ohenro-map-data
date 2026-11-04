#!/bin/bash
# Build and run the Ohenro map-preview web app via docker compose.
#
# The container joins the `ohenro-map` docker network under the name
# `ohenro-map-preview` and listens on :5173, so the cloudflared tunnel
# (cloudflared service / start-cloudflared.sh) can reach it at
# http://ohenro-map-preview:5173.
#
# Map data is served live from host `datasets/` and `output/` volumes (read-only) via the
# entrypoint's data symlinks; no data is baked into the image.
set -euo pipefail

exec docker compose up -d --build ohenro-map-preview
