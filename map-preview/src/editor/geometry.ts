/**
 * Local equirectangular metric geometry for the route editor core.
 *
 * Constants and math are replicated exactly from the Python pipeline
 * (`sekaiisan_henro/projection.py`): a fixed, deterministic local metric
 * projection centred near Shikoku used only for relative distances and
 * topology. WGS84 lon/lat remains authoritative; every function accepts and
 * returns WGS84 coordinates, and nothing here is navigation-grade.
 */

import type { GeoJSONGeometry, Position } from "./model";

/** Mean Earth radius in metres and the fixed reference point (Shikoku central). */
export const R = 6371008.8;
export const LON0 = 133.75;
export const LAT0 = 33.65;

const COS_LAT0 = Math.cos((LAT0 * Math.PI) / 180);

/** Fraction epsilon for treating a projection as effectively an endpoint. */
export const EPSILON = 1e-9;

/** Project one WGS84 [lon, lat] pair to local metric [x, y] metres. */
export function projectPoint([lon, lat]: Position): [number, number] {
  const x = R * ((lon - LON0) * Math.PI) / 180 * COS_LAT0;
  const y = R * ((lat - LAT0) * Math.PI) / 180;
  return [x, y];
}

/** Inverse of {@link projectPoint}: local metric [x, y] -> [lon, lat]. */
export function unprojectPoint([x, y]: [number, number]): Position {
  const lon = LON0 + (x / (R * COS_LAT0)) * (180 / Math.PI);
  const lat = LAT0 + (y / R) * (180 / Math.PI);
  return [lon, lat];
}

/**
 * Validate a WGS84 coordinate: a finite [lon, lat] pair within bounds.
 * Returns `true` for a valid coordinate, `false` otherwise.
 */
export function isValidPosition(value: unknown): value is Position {
  if (!Array.isArray(value) || value.length !== 2) return false;
  const [lon, lat] = value as unknown[];
  return (
    typeof lon === "number" && Number.isFinite(lon) && lon >= -180 && lon <= 180 &&
    typeof lat === "number" && Number.isFinite(lat) && lat >= -90 && lat <= 90
  );
}

/** Euclidean distance (metres) between two coordinates in the metric projection. */
export function distanceM(a: Position, b: Position): number {
  const [ax, ay] = projectPoint(a);
  const [bx, by] = projectPoint(b);
  const dx = ax - bx;
  const dy = ay - by;
  return Math.sqrt(dx * dx + dy * dy);
}

/** Total metric length (metres) of an ordered coordinate sequence. */
export function lineLengthM(coords: Position[]): number {
  let total = 0;
  for (let i = 0; i < coords.length - 1; i++) {
    total += distanceM(coords[i], coords[i + 1]);
  }
  return total;
}

/** Interpolate between two coordinates at fraction `f` (0..1) in metric space. */
function interpolatePosition(a: Position, b: Position, f: number): Position {
  const [ax, ay] = projectPoint(a);
  const [bx, by] = projectPoint(b);
  return unprojectPoint([ax + (bx - ax) * f, ay + (by - ay) * f]);
}

/** The resolved coordinate for a segment/fraction ref over a coordinate part. */
function pointAt(coords: Position[], segmentIndex: number, fraction: number): Position {
  if (fraction <= EPSILON) return coords[segmentIndex];
  if (fraction >= 1 - EPSILON) return coords[segmentIndex + 1];
  return interpolatePosition(coords[segmentIndex], coords[segmentIndex + 1], fraction);
}

/** Result of {@link nearestPointOnLine}. */
export interface NearestOnLine {
  /** Index of the closest segment ([segmentIndex, segmentIndex + 1] vertices). */
  segmentIndex: number;
  /** Fraction along that segment (clamped to 0..1). */
  fraction: number;
  /** The exact snapped coordinate (a source vertex when fraction is ~0 or ~1). */
  coordinate: Position;
  /** Metric distance from the query point to the snapped coordinate. */
  distanceM: number;
}

/**
 * Snap a point to the nearest position on an authoritative LineString part.
 * The fraction is clamped to [0, 1]; when it is effectively 0 or 1 the
 * returned coordinate is the exact source endpoint vertex. Ties resolve to
 * the lowest segment index.
 */
export function nearestPointOnLine(
  coords: Position[],
  point: Position,
): NearestOnLine {
  if (coords.length < 2) {
    throw new Error("nearestPointOnLine requires a part with at least 2 coordinates");
  }
  const [qx, qy] = projectPoint(point);
  let best: NearestOnLine | null = null;
  for (let i = 0; i < coords.length - 1; i++) {
    const [ax, ay] = projectPoint(coords[i]);
    const [bx, by] = projectPoint(coords[i + 1]);
    const dx = bx - ax;
    const dy = by - ay;
    const len2 = dx * dx + dy * dy;
    let t = 0;
    if (len2 > 0) {
      t = ((qx - ax) * dx + (qy - ay) * dy) / len2;
    }
    let fraction: number;
    let coordinate: Position;
    if (t <= EPSILON) {
      fraction = 0;
      coordinate = coords[i];
    } else if (t >= 1 - EPSILON) {
      fraction = 1;
      coordinate = coords[i + 1];
    } else {
      fraction = t;
      coordinate = unprojectPoint([ax + t * dx, ay + t * dy]);
    }
    const d = distanceM(point, coordinate);
    if (best === null || d < best.distanceM) {
      best = { segmentIndex: i, fraction, coordinate, distanceM: d };
    }
  }
  return best as NearestOnLine;
}

/** A segment/fraction reference used to delimit a range along a line part. */
export interface LineRef {
  segmentIndex: number;
  fraction: number;
}

/** Result of {@link extractLineRange}. */
export interface LineRange {
  /** Ordered coordinates from `from` to `to`, preserving every intervening vertex. */
  coordinates: Position[];
  /** Direction of travel along the source part. */
  direction: "forward" | "reverse";
}

/**
 * Validate a segment/fraction ref against a part's coordinate count at the
 * trust boundary: the segment index must be a non-negative integer pointing
 * at an existing segment, and the fraction must be a finite value in [0, 1].
 */
function assertValidRef(ref: LineRef, partLength: number, label: string): void {
  if (
    !Number.isInteger(ref.segmentIndex) ||
    ref.segmentIndex < 0 ||
    ref.segmentIndex >= partLength - 1
  ) {
    throw new Error(
      `extractLineRange ${label} ref has out-of-range segmentIndex ${String(ref.segmentIndex)}`,
    );
  }
  if (!Number.isFinite(ref.fraction) || ref.fraction < 0 || ref.fraction > 1) {
    throw new Error(
      `extractLineRange ${label} ref has invalid fraction ${String(ref.fraction)}`,
    );
  }
}

/**
 * Extract the ordered line range between two segment/fraction refs on the
 * same authoritative line part. Every intervening source vertex is preserved
 * verbatim; no simplification or resampling is performed. Consecutive exact
 * duplicates are removed so an endpoint/vertex boundary never yields a
 * repeated point (distinct source vertices are always kept). The direction
 * is `"forward"` when `to` lies at or after `from` along the part, otherwise
 * `"reverse"`. Invalid refs (non-integer or out-of-range segment index,
 * non-finite fraction) throw.
 */
export function extractLineRange(
  coords: Position[],
  from: LineRef,
  to: LineRef,
): LineRange {
  if (coords.length < 2) {
    throw new Error("extractLineRange requires a part with at least 2 coordinates");
  }
  assertValidRef(from, coords.length, "from");
  assertValidRef(to, coords.length, "to");
  const { segmentIndex: sf, fraction: ff } = from;
  const { segmentIndex: st, fraction: ft } = to;

  let raw: Position[];
  if (sf === st) {
    // Same segment: single point when identical, otherwise two ordered points.
    const a = pointAt(coords, sf, ff);
    const b = pointAt(coords, st, ft);
    raw = ft === ff ? [a] : [a, b];
  } else if (sf < st) {
    // Forward: from point, then coords[sf+1]..coords[st], then to point.
    raw = [pointAt(coords, sf, ff)];
    for (let i = sf + 1; i <= st; i++) raw.push(coords[i]);
    raw.push(pointAt(coords, st, ft));
  } else {
    // Reverse: from point, then coords[sf]..coords[st+1], then to point.
    raw = [pointAt(coords, sf, ff)];
    for (let i = sf; i > st; i--) raw.push(coords[i]);
    raw.push(pointAt(coords, st, ft));
  }

  const direction: "forward" | "reverse" =
    sf < st ? "forward" : sf > st ? "reverse" : ft >= ff ? "forward" : "reverse";

  return { coordinates: dedupeConsecutive(raw), direction };
}

/**
 * Recursively enumerate the discrete point coordinates from a geometry
 * (Point / MultiPoint, and their contents inside a GeometryCollection).
 */
export function enumeratePointParts(geometry: GeoJSONGeometry): Position[] {
  switch (geometry.type) {
    case "Point":
      return [geometry.coordinates];
    case "MultiPoint":
      return geometry.coordinates.slice();
    case "GeometryCollection": {
      const out: Position[] = [];
      for (const child of geometry.geometries) out.push(...enumeratePointParts(child));
      return out;
    }
    default:
      return [];
  }
}

/**
 * Recursively enumerate the linear parts from a geometry, each as an ordered
 * coordinate sequence (LineString, MultiLineString parts, and their contents
 * inside a GeometryCollection). The array index is the `partIndex` used by
 * line references.
 */
export function enumerateLineParts(geometry: GeoJSONGeometry): Position[][] {
  switch (geometry.type) {
    case "LineString":
      return [geometry.coordinates];
    case "MultiLineString":
      return geometry.coordinates.slice();
    case "GeometryCollection": {
      const out: Position[][] = [];
      for (const child of geometry.geometries) out.push(...enumerateLineParts(child));
      return out;
    }
    default:
      return [];
  }
}

/**
 * Remove consecutive exact-duplicate coordinates (in-place values preserved,
 * returns a new array). Only exact equality collapses a pair; no tolerance.
 */
export function dedupeConsecutive(coords: Position[]): Position[] {
  const out: Position[] = [];
  for (const c of coords) {
    const last = out[out.length - 1];
    if (!last || last[0] !== c[0] || last[1] !== c[1]) out.push(c);
  }
  return out;
}