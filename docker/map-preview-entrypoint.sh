#!/bin/sh
# map-preview container entrypoint.
#
# The Vite build bakes /data/* asset URLs into the bundle, but the actual map
# data lives on the host (datasets/, output/ + the public/data symlink layout). At
# startup we recreate that symlink layout inside the served html dir, pointing
# into the read-only /srv/output volume, so the app sees the current data
# without rebuilding the image.
#
# Mounts expected:
#   $PWD/output                -> /srv/output:ro
#   $PWD/datasets              -> /srv/datasets:ro
#   $PWD/map-preview/public/data -> /data-ref:ro   (host symlink layout)
set -eu

DATA_DIR=/usr/share/nginx/html/data
mkdir -p "$DATA_DIR"

if [ -d /data-ref ]; then
    for f in /data-ref/*; do
        # Skip glob literal when the dir is empty.
        [ -e "$f" ] || [ -L "$f" ] || continue
        name=$(basename "$f")
        if [ -L "$f" ]; then
            target=$(readlink "$f")
            case "$target" in
                ../../../datasets/*)
                    ln -sfn "/srv/datasets/${target#../../../datasets/}" "$DATA_DIR/$name"
                    continue
                    ;;
            esac
            # Shared app assets still live in output/.
            rel=${target##*output/}
            if [ "$rel" != "$target" ] && [ -n "$rel" ]; then
                ln -sfn "/srv/output/$rel" "$DATA_DIR/$name"
                continue
            fi
        fi
        # Plain file/dir in the layout (or a link we could not map): copy it.
        ln -sfn "$f" "$DATA_DIR/$name"
    done
fi

exec nginx -g 'daemon off;'
