import type { Position } from "geojson";

/**
 * Elevation profile built from a GeoJSON LineString whose coordinates carry
 * an elevation as the third element ([lon, lat, elev]). Cumulative distance
 * uses the same fixed equirectangular projection as sekaiisan_henro/planner.py
 * (R = 6371008.8, lat0 = 33.65), so distances match the Python report.
 */
export interface ElevationPoint {
  d: number; // cumulative metres along the path
  e: number; // elevation metres
}

export interface ElevationProfile {
  points: ElevationPoint[];
  totalM: number;
  minM: number;
  maxM: number;
}

const R = 6371008.8;
const COS_LAT0 = Math.cos((33.65 * Math.PI) / 180);

function metresBetween(a: Position, b: Position): number {
  const rad = Math.PI / 180;
  return Math.hypot(
    R * COS_LAT0 * (b[0] - a[0]) * rad,
    R * (b[1] - a[1]) * rad,
  );
}

export function buildElevationProfile(
  coordinates: Position[],
): ElevationProfile | null {
  const points: ElevationPoint[] = [];
  let total = 0;
  let prev: Position | null = null;
  for (const c of coordinates) {
    const elev = c[2];
    if (typeof elev !== "number" || !Number.isFinite(elev)) continue;
    if (prev) total += metresBetween(prev, c);
    prev = c;
    points.push({ d: total, e: elev });
  }
  if (points.length < 2) return null;
  let minM = Infinity;
  let maxM = -Infinity;
  for (const p of points) {
    if (p.e < minM) minM = p.e;
    if (p.e > maxM) maxM = p.e;
  }
  return { points, totalM: total, minM, maxM };
}