import { PMTiles } from "pmtiles";

/**
 * Browser elevation sampler over the existing Terrain-RGB PMTiles archive
 * (`shikoku-terrain.pmtiles`, z6-14, mapbox encoding). Mirrors the Python
 * planner's GSI DEM sampling at DEM10 resolution (~12m grid), which is the
 * same underlying data as the color-relief / terrain overlays.
 */

export function tileXY(
  lon: number,
  lat: number,
  z: number,
): { x: number; y: number } {
  const n = 2 ** z;
  const x = Math.floor(((lon + 180) / 360) * n);
  const latRad = (lat * Math.PI) / 180;
  const y = Math.floor(
    ((1 - Math.log(Math.tan(latRad) + 1 / Math.cos(latRad)) / Math.PI) / 2) * n,
  );
  return { x, y };
}

/** Mapbox Terrain-RGB decode: height = -10000 + ((R*256+G)*256+B) * 0.1. */
export function decodeTerrainRgb(r: number, g: number, b: number): number {
  return -10000 + ((r * 256 + g) * 256 + b) * 0.1;
}

/**
 * Sample elevation at a decoded RGBA pixel. NODATA cells are encoded with
 * alpha=0 (sea / DEM-missing) per scripts/rgbify_dem.py; the opaque decode
 * would read as -10000 m, so transparent pixels report null instead.
 */
export function elevationFromRgba(
  r: number,
  g: number,
  b: number,
  a: number,
): number | null {
  if (a === 0) return null;
  return decodeTerrainRgb(r, g, b);
}

export class TerrainElevationSampler {
  private source: PMTiles;
  private zoom = 14;
  private cache = new Map<string, Promise<ImageData | null>>();

  constructor(url: string) {
    this.source = new PMTiles(url);
  }

  async sample(lat: number, lon: number): Promise<number | null> {
    const z = this.zoom;
    const { x, y } = tileXY(lon, lat, z);
    const key = `${z}/${x}/${y}`;
    let data = this.cache.get(key);
    if (!data) {
      data = this.loadTile(z, x, y);
      this.cache.set(key, data);
    }
    const image = await data;
    if (!image) return null;
    const n = 256;
    const nTiles = 2 ** z;
    const px = Math.min(
      n - 1,
      Math.max(0, Math.floor(((lon + 180) / 360) * nTiles - x) * n),
    );
    const latRad = (lat * Math.PI) / 180;
    const fy =
      (1 - Math.log(Math.tan(latRad) + 1 / Math.cos(latRad)) / Math.PI) / 2;
    const py = Math.min(n - 1, Math.max(0, Math.floor((fy * nTiles - y) * n)));
    const idx = (py * n + px) * 4;
    return elevationFromRgba(
      image.data[idx],
      image.data[idx + 1],
      image.data[idx + 2],
      image.data[idx + 3],
    );
  }

  private async loadTile(
    z: number,
    x: number,
    y: number,
  ): Promise<ImageData | null> {
    try {
      const resp = await this.source.getZxy(z, x, y);
      if (!resp) return null;
      const buf = resp.data;
      if (!buf) return null;
      const bitmap = await createImageBitmap(
        new Blob([buf], { type: "image/png" }),
      );
      const canvas = new OffscreenCanvas(bitmap.width, bitmap.height);
      const ctx = canvas.getContext("2d", { willReadFrequently: true });
      if (!ctx) return null;
      ctx.drawImage(bitmap, 0, 0);
      const image = ctx.getImageData(0, 0, canvas.width, canvas.height);
      bitmap.close();
      return image;
    } catch {
      return null;
    }
  }
}