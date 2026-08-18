#!/usr/bin/env python3
"""Masked Terrain-RGB tiler (minimal wrapper over rio-rgbify's encoder).

rio-rgbify 1.4.4 cannot (a) accept a projected (EPSG:3857) input — its tile
enumeration warps the bbox to EPSG:4326 with densify_pts=0, which fails when
the source is projected — and (b) preserve NODATA transparency: its plain
`data_to_rgb` encodes NODATA (sea) as RGB(0,0,0) => -10000 m, a valid-looking
extreme low elevation instead of missing.

Per docs/elevation_visualization_pipeline.md §9 this is a minimal wrapper that
reuses rio-rgbify's RGB encoder (`data_to_rgb`) but drives the tiling itself.
The input is the *already warped* EPSG:3857 COG (gdalwarp step), so each Web
Mercator tile is an axis-aligned scale: we read only the needed source window
(windowed read — never the whole 25600x17152 raster) and reproject it to the
512x512 tile. Output PNGs are RGBA with alpha=0 over NODATA, so MapLibre's
raster-dem treats sea/missing cells as no-data.

Usage:
    rgbify_dem.py <input-3857.tif> <out.mbtiles> --min-z 6 --max-z 14
                  [--workers 4] [--base-val -10000] [--interval 0.1]
"""

import argparse
import math
import os
import sqlite3
import sys
from multiprocessing import Pool

from affine import Affine
import mercantile
import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling
from rasterio.io import MemoryFile

from rio_rgbify.encoders import data_to_rgb


def _worker(args):
    tile, inpath, base_val, interval = args
    x, y, z = tile

    # Web Mercator world bounds of this tile (EPSG:3857 metres):
    # ul = (west, south), lr = (east, north).
    ul = mercantile.xy(*mercantile.ul(x, y + 1, z))
    lr = mercantile.xy(*mercantile.ul(x + 1, y, z))
    west, south, east, north = ul[0], ul[1], lr[0], lr[1]
    toaffine = rasterio.transform.from_bounds(west, south, east, north, 512, 512)

    with rasterio.open(inpath) as src:
        gt = src.transform
        # Source pixel window covering this tile. Both src and tile are in
        # EPSG:3857, so the reproject below is a pure scale. from_bounds
        # handles the north-up (negative y) transform correctly.
        win = rasterio.windows.from_bounds(west, south, east, north, transform=gt)
        col_min = max(int(math.floor(win.col_off)), 0)
        row_min = max(int(math.floor(win.row_off)), 0)
        col_max = min(int(math.ceil(win.col_off + win.width)), src.width)
        row_max = min(int(math.ceil(win.row_off + win.height)), src.height)
        if col_max <= col_min or row_max <= row_min:
            # Tile is entirely outside the dataset.
            return x, y, z, None

        elev = src.read(
            1, window=((row_min, row_max), (col_min, col_max)), masked=True
        ).astype("float64")
        filled = elev.filled(np.nan)

        # Transform of the read sub-window (full transform shifted to the
        # window's top-left pixel). The source array corresponds to this
        # window, so we pass its own transform (no src_window).
        win_transform = gt * Affine.translation(col_min, row_min)

        out = np.empty((512, 512), dtype="float64")
        reproject(
            filled,
            out,
            src_transform=win_transform,
            src_crs="EPSG:3857",
            dst_transform=toaffine,
            dst_crs="EPSG:3857",
            resampling=Resampling.bilinear,
        )

    valid = ~np.isnan(out)
    if not valid.any():
        return x, y, z, None  # empty tile (all ocean/missing)
    rgb = data_to_rgb(np.where(valid, out, 0.0), base_val, interval)
    alpha = np.where(valid, 255, 0).astype("uint8")
    rgba = np.concatenate([rgb, alpha[np.newaxis, :, :]], axis=0)
    png = _encode_png(rgba, toaffine)
    return x, y, z, png


def _encode_png(rgba, affine):
    profile = {
        "driver": "PNG",
        "width": 512,
        "height": 512,
        "count": 4,
        "dtype": "uint8",
        "transform": affine,
    }
    with MemoryFile() as memfile:
        with memfile.open(**profile) as dst:
            dst.write(rgba)
        return memfile.read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--min-z", type=int, default=6)
    ap.add_argument("--max-z", type=int, default=14)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--base-val", type=float, default=-10000)
    ap.add_argument("--interval", type=float, default=0.1)
    args = ap.parse_args()

    if os.path.exists(args.output):
        os.remove(args.output)

    with rasterio.open(args.input) as src:
        # mercantile.tiles() expects lat/lon degrees, so convert the 3857
        # raster bounds to WGS84 for tile enumeration.
        lonlat = rasterio.warp.transform_bounds(
            "EPSG:3857", "EPSG:4326", *src.bounds, densify_pts=21
        )
        bounds = list(lonlat)

    tiles = _tiles_for_bounds(bounds, args.min_z, args.max_z)
    print(
        f"rgbify_dem: {len(tiles)} tiles z{args.min_z}-{args.max_z}",
        file=sys.stderr,
    )

    work = [(t, args.input, args.base_val, args.interval) for t in tiles]
    results = []
    with Pool(args.workers) as pool:
        results = pool.map(_worker, work)
    # Drop fully-empty tiles (all ocean / outside data) — worker returns
    # (x, y, z, None) for those. Only tiles with actual elevation are stored.
    results = [r for r in results if r is not None and r[3] is not None]

    conn = sqlite3.connect(args.output)
    conn.executescript(
        """
        CREATE TABLE metadata (name TEXT, value TEXT);
        CREATE TABLE tiles (
            zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB
        );
        """
    )
    conn.executemany(
        "INSERT INTO metadata (name, value) VALUES (?, ?)",
        [
            ("format", "png"),
            ("name", ""),
            ("description", ""),
            ("version", "1"),
            ("type", "baselayer"),
            ("minzoom", str(args.min_z)),
            ("maxzoom", str(args.max_z)),
        ],
    )
    conn.executemany(
        "INSERT INTO tiles (zoom_level, tile_column, tile_row, tile_data) VALUES (?, ?, ?, ?)",
        [
            (z, x, (1 << z) - 1 - y, png)
            for (x, y, z, png) in results
        ],
    )
    conn.commit()
    conn.close()
    print(f"rgbify_dem: wrote {len(results)} tiles -> {args.output}", file=sys.stderr)


def _tiles_for_bounds(bounds, min_z, max_z):
    west, south, east, north = bounds
    tiles = []
    for z in range(min_z, max_z + 1):
        for t in mercantile.tiles(west, south, east, north, [z]):
            tiles.append(t)
    return tiles


if __name__ == "__main__":
    main()
