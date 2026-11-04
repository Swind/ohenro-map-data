#!/bin/bash
# Start the cloudflared tunnel for https://ohenro-map.code-life.info via
# docker compose. Joins the `ohenro-map` docker network (shared with the
# ohenro-map-preview service) so it can resolve the map-preview container at
# http://ohenro-map-preview:5173. The tunnel token is read from .env
# (CLOUDFLARED_TOKEN, gitignored).
set -euo pipefail

exec docker compose up cloudflared