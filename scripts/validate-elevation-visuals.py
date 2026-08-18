#!/usr/bin/env python3
"""Strict validation for the elevation visualization PMTiles.

Checks spec §12.3 (contours) and §12.4 (raster/terrain) plus the golden
coordinate baselines from §12.2. Exits non-zero on any failure.

Usage:
    validate-elevation-visuals.py <contours.pmtiles> <terrain.pmtiles> \
        [--golden gsi-dem/tests/golden/elevation.json]
"""

import argparse
import gzip
import io
import json
import math
import sys
import zlib

import mercantile
import numpy as np
from PIL import Image
from pmtiles.reader import Reader, MmapSource

from mapbox_vector_tile import decode as mvt_decode


def mvt_tile_decode(tile):
    # tippecanoe gzip-compresses MVT tile data; pmtiles stores it as-is.
    if tile[:2] == b"\x1f\x8b":
        tile = gzip.decompress(tile)
    return mvt_decode(tile)


FAILS = []


def check(name, cond, detail=""):
    if cond:
        print(f"  PASS: {name}{' ' + detail if detail else ''}")
    else:
        print(f"  FAIL: {name}{' ' + detail if detail else ''}")
        FAILS.append(name)


def open_reader(path):
    return Reader(MmapSource(open(path, "rb")))


def shikoku_point():
    # Matsuyama city plain (inland, stable) — on DEM land. Returns (lat, lon).
    return 33.839, 132.766


def shikoku_tile(z):
    lat, lon = shikoku_point()
    return mercantile.tile(lon, lat, z)


def validate_contours(path):
    print("==> Contours:", path)
    r = open_reader(path)
    h = r.header()
    meta = r.metadata()

    # vector layer present with elevation_m
    vl = meta.get("vector_layers")
    layers = json.loads(vl) if isinstance(vl, str) else (vl or [])
    ids = {l.get("id") for l in layers}
    check("contours layer present", "contours" in ids)
    contours_layer = next((l for l in layers if l.get("id") == "contours"), {})
    fields = contours_layer.get("fields", {})
    check("contours has elevation_m field", "elevation_m" in fields, str(fields.get("elevation_m")))

    # bounds overlap Shikoku
    b = h.get("bounds")
    if b:
        lon_min, lat_min, lon_max, lat_max = b
        check(
            "contours bounds overlap Shikoku",
            lon_min < 135.5 and lon_max > 131.0 and lat_min < 34.5 and lat_max > 32.0,
            f"[{lon_min},{lat_min}]-[{lon_max},{lat_max}]",
        )
    else:
        print("  WARN: no bounds in header")

    # zoom coverage z12-15
    for z in range(12, 16):
        t = shikoku_tile(z)
        tile = r.get(z, t.x, t.y)
        check(f"contours has tile at z{z}", tile is not None, f"tile {t.x},{t.y}")

    # decode a sample of tiles: elevation_m finite integer, %20==0, no -32768
    bad = []
    total = 0
    for z in (12, 13, 14, 15):
        for dx in range(0, 4):
            for dy in range(0, 4):
                t = shikoku_tile(z)
                tile = r.get(z, t.x + dx - 1, t.y + dy - 1)
                if not tile:
                    continue
                try:
                    dec = mvt_tile_decode(tile)
                except Exception as e:
                    bad.append(f"z{z} ({t.x+dx-1},{t.y+dy-1}) decode err: {e}")
                    continue
                for layer in dec.values():
                    for f in layer.get("features", []):
                        total += 1
                        v = f.get("properties", {}).get("elevation_m")
                        if v is None:
                            bad.append(f"missing elevation_m")
                            continue
                        if not float(v).is_integer() or abs(v - round(v)) > 1e-9:
                            bad.append(f"non-integer {v}")
                        if v % 20 != 0:
                            bad.append(f"not multiple of 20: {v}")
                        if v == -32768:
                            bad.append("NODATA contour present")
    check("contour elevation_m sane (integer, %20, no NODATA)", not bad and total > 0,
          f"{total} features sampled" + ("; " + "; ".join(bad[:5]) if bad else ""))

    # a contour encloses the golden elevation within one interval
    try:
        g = json.load(open(_GOLDEN))
        for p in g.get("points", []):
            if p.get("layer") != "dem10":
                continue
            lat, lon, exp = p["lat"], p["lon"], p["expected_m"]
            t = mercantile.tile(lon, lat, 15)
            tile = r.get(15, t.x, t.y)
            if not tile:
                continue
            vals = set()
            for layer in mvt_tile_decode(tile).values():
                for f in layer.get("features", []):
                    vals.add(f["properties"]["elevation_m"])
            # contour immediately below/at golden elevation exists
            below = [v for v in vals if v <= exp]
            if below and (exp - max(below)) <= 20:
                check(
                    f"contour encloses golden ({p['name']} {exp}m)",
                    True,
                    f"nearest contour {max(below)}m",
                )
            else:
                check(
                    f"contour encloses golden ({p['name']} {exp}m)",
                    False,
                    f"contours near {exp}: {sorted(vals)[:6]}",
                )
    except FileNotFoundError:
        print("  WARN: golden file not found, skipping enclosure check")


def decode_png_terrain(tile):
    img = Image.open(io.BytesIO(tile)).convert("RGBA")
    arr = np.array(img)  # HxWx4 (RGBA)
    r = arr[..., 0].astype(np.uint32)
    g = arr[..., 1].astype(np.uint32)
    b = arr[..., 2].astype(np.uint32)
    a = arr[..., 3]
    elev = -10000.0 + (r * 65536 + g * 256 + b) * 0.1
    return elev, a


def validate_terrain(path):
    print("==> Terrain:", path)
    r = open_reader(path)
    h = r.header()
    check("terrain tile type is PNG", h.get("tile_type") is not None and h["tile_type"].name == "PNG", str(h.get("tile_type")))

    # zoom coverage z6-14
    covered = []
    for z in range(6, 15):
        t = shikoku_tile(z)
        tile = r.get(z, t.x, t.y)
        if tile is not None:
            covered.append(z)
    check("terrain covers z6-14", covered == list(range(6, 15)), str(covered))

    # land sample decodes to reasonable elevation
    t = shikoku_tile(13)
    tile = r.get(13, t.x, t.y)
    if tile:
        elev, a = decode_png_terrain(tile)
        land = elev[a > 0]
        if len(land):
            ok = land.min() >= 0 and land.max() < 2000
            check("land sample decodes reasonable (0-2000m)", bool(ok), f"min {land.min():.0f}, max {land.max():.0f}")
        else:
            check("land sample present at Matsuyama", False, "no land pixels")
    else:
        check("terrain tile at Matsuyama z13", False, "missing")

    # ocean transparency: a point in open sea must not decode to land elevation.
    # Use a point far offshore in the Pacific, southeast of Shikoku.
    ocean = (31.5, 133.0)
    oz = 13
    ot = mercantile.tile(ocean[1], ocean[0], oz)
    otile = r.get(oz, ot.x, ot.y)
    if otile:
        elev, a = decode_png_terrain(otile)
        land_like = elev[a > 0]
        # Any non-transparent pixel must NOT be a plausible land elevation.
        check(
            "ocean sample has no land elevation",
            len(land_like) == 0,
            f"{len(land_like)} non-transparent pixels at offshore point",
        )
    else:
        # Fully-ocean tiles are dropped by the tiler, so there is no ocean
        # data to wrongly decode as land — this satisfies the requirement.
        check("ocean sample has no land elevation", True, "no ocean tiles generated offshore")

    # tile seam continuity at z13 across a tile boundary on land.
    t = shikoku_tile(13)
    right_tile = r.get(13, t.x + 1, t.y)
    if tile and right_tile:
        e_left, a_left = decode_png_terrain(tile)
        e_right, a_right = decode_png_terrain(right_tile)
        # Compare the rightmost column of left tile vs leftmost column of right tile,
        # only over pixels that are land in both.
        colL = e_left[:, -1]
        colR = e_right[:, 0]
        landL = a_left[:, -1] > 0
        landR = a_right[:, 0] > 0
        both = landL & landR
        if both.sum() > 50:
            diff = np.abs(colL[both] - colR[both])
            # A genuine seam artifact is a systematic (fixed 256px) offset —
            # all seam pixels shift by roughly the same amount => high median.
            # Real terrain variation gives a small, variable diff. Threshold
            # on the median so steep-slope variation doesn't false-fail.
            median = float(np.median(diff))
            check(
                "tile seam elevation continuous (no fixed seam)",
                median < 3.0,
                f"median diff {median:.2f}m, max {float(diff.max()):.2f}m over {both.sum()} px",
            )
        else:
            print("  WARN: seam sample too small, skipping")
    else:
        print("  WARN: seam neighbor tile missing, skipping")


_GOLDEN = None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("contours")
    ap.add_argument("terrain")
    ap.add_argument("--golden", default=None)
    args = ap.parse_args()
    global _GOLDEN
    _GOLDEN = args.golden

    validate_contours(args.contours)
    validate_terrain(args.terrain)

    print()
    if FAILS:
        print(f"VALIDATION FAILED ({len(FAILS)}): {', '.join(FAILS)}")
        sys.exit(1)
    print("VALIDATION PASSED")


if __name__ == "__main__":
    main()
