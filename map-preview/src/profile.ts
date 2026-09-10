import type { FeatureCollection, Position } from "geojson";

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
  gainM: number;
  lossM: number;
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
    // Reject missing/non-finite values and physically impossible heights
    // (e.g. a Terrain-RGB no-data decode of -10000 leaking into the profile
    // from a source that did not flag it). A single bad vertex must never
    // turn the whole gain/loss into a fake cliff.
    if (
      typeof elev !== "number" ||
      !Number.isFinite(elev) ||
      elev < -1000 ||
      elev > 5000
    ) continue;
    if (prev) total += metresBetween(prev, c);
    prev = c;
    points.push({ d: total, e: elev });
  }
  if (points.length < 2) return null;
  let minM = Infinity;
  let maxM = -Infinity;
  let gainM = 0;
  let lossM = 0;
  for (let i = 0; i < points.length; i++) {
    const e = points[i].e;
    if (e < minM) minM = e;
    if (e > maxM) maxM = e;
    if (i > 0) {
      const delta = e - points[i - 1].e;
      if (delta > 0) gainM += delta;
      else lossM += -delta;
    }
  }
  return { points, totalM: total, minM, maxM, gainM, lossM };
}

/**
 * Render an SVG elevation profile for a FeatureCollection carrying a
 * `planned_route` LineString with per-vertex elevation. Stats prefer the
 * feature properties (Python-computed) and fall back to the locally computed
 * values. Returns true when rendered.
 */
export function renderElevationProfile(
  container: HTMLElement,
  fc: FeatureCollection,
): boolean {
  const route = fc.features.find(
    (f) => f.geometry?.type === "LineString" && f.properties?.kind === "planned_route",
  );
  if (!route || route.geometry.type !== "LineString") {
    container.textContent = "no planned route";
    return false;
  }
  const profile = buildElevationProfile(route.geometry.coordinates);
  if (!profile) {
    container.textContent = "insufficient elevation data";
    return false;
  }
  const props = (route.properties ?? {}) as Record<string, number | undefined>;
  const span = Math.max(profile.maxM - profile.minM, 1);
  const W = 260;
  const H = 90;
  const PAD = 6;
  const x = (d: number): number => PAD + (d / profile.totalM) * (W - 2 * PAD);
  const y = (e: number): number =>
    PAD + (1 - (e - profile.minM) / span) * (H - 2 * PAD);
  const pts = profile.points
    .map((p) => `${x(p.d).toFixed(1)},${y(p.e).toFixed(1)}`)
    .join(" ");
  const base = y(profile.minM);
  const area = `${x(0).toFixed(1)},${base} ${pts} ${x(profile.totalM).toFixed(1)},${base}`;
  const lengthKm = (profile.totalM / 1000).toFixed(1);
  const minM = props.min_m ?? profile.minM;
  const maxM = props.max_m ?? profile.maxM;
  const gainM = props.gain_m ?? Math.round(profile.gainM);
  const lossM = props.loss_m ?? Math.round(profile.lossM);
  const stats = [
    `${lengthKm} km`,
    `↑${gainM} m`,
    `↓${lossM} m`,
    `min ${minM.toFixed(0)} m`,
    `max ${maxM.toFixed(0)} m`,
  ].join(" · ");
  container.innerHTML =
    `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="elevation profile">` +
    `<polygon points="${area}" fill="#d81b60" opacity="0.18"/>` +
    `<polyline points="${pts}" fill="none" stroke="#d81b60" stroke-width="1.8" ` +
    `stroke-linejoin="round" stroke-linecap="round"/>` +
    `<text x="${PAD}" y="${H - 3}" font-size="9" fill="#777">${minM.toFixed(0)}m</text>` +
    `<text x="${PAD}" y="${11}" font-size="9" fill="#777">${maxM.toFixed(0)}m</text>` +
    `</svg>` +
    `<div class="plan-profile-stats">${stats}</div>`;
  return true;
}