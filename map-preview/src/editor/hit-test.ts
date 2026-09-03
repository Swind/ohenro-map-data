/**
 * Authoritative hit-testing for the route editor.
 *
 * MapLibre's `queryRenderedFeatures` is used only for candidate discovery on
 * the registered transparent line hitbox and POI circle layers of visible,
 * selectable sources. Every candidate is then resolved back to its
 * authoritative EditorSource feature by exact feature id, and the nearest
 * line/point parts are recomputed from the authoritative source geometry —
 * never from the candidate's possibly tiled or simplified geometry.
 *
 * For each authoritative candidate feature, the nearest line part (when the
 * candidate came from a line hitbox layer) and the nearest point coordinate
 * (when it came from a POI layer) are recomputed recursively from the
 * authoritative source geometry — never from the candidate's possibly tiled
 * or simplified geometry, and never every distant part of a Multi* feature.
 * Ties resolve to the lowest part/point index. All overlapping candidates
 * across distinct features/sources are returned in deterministic order
 * (distance, then stable refs); the UI must choose or refuse ambiguity — this
 * module never silently picks "first".
 *
 * The minimal {@link HitTestMap} surface keeps the module pure and testable
 * without WebGL; a real MapLibre map is structurally compatible.
 */

import type { EditorSource, Position } from "./model";
import {
  distanceM,
  enumerateLineParts,
  enumeratePointParts,
  nearestPointOnLine,
} from "./geometry";
import type { EditorSourceRegistry } from "./source-layers";
import { isRouteEligibleFeature } from "./line-eligibility";

/** A minimal MapLibre feature as returned by queryRenderedFeatures. */
export interface CandidateFeature {
  id?: string | number;
  /** Stable rendered properties; the `id` property is authoritative-first. */
  properties?: Record<string, unknown>;
  layer: { id: string };
}

/** A minimal point-like (pixel) value with x/y coordinates. */
export interface PointLike {
  x: number;
  y: number;
}

/** The minimal MapLibre surface the hit-test needs (mockable in tests). */
export interface HitTestMap {
  project(lngLat: Position): PointLike;
  queryRenderedFeatures(
    point: PointLike,
    options?: { layers?: string[] },
  ): CandidateFeature[];
}

/** A hit on a line part: the nearest authoritative point on that part. */
export interface LineHit {
  kind: "line";
  sourceId: string;
  featureId: string;
  partIndex: number;
  segmentIndex: number;
  fraction: number;
  coordinate: Position;
  distanceM: number;
}

/** A hit on a discrete POI point. */
export interface PoiHit {
  kind: "poi";
  sourceId: string;
  featureId: string;
  coordinate: Position;
  distanceM: number;
}

export type EditorHit = LineHit | PoiHit;

/**
 * Resolve a candidate feature back to the authoritative source feature by
 * exact id. The stable rendered `properties.id` is tried first when it is a
 * string or number, then the candidate's own `id`. Each is compared strictly
 * (`===`) to the authoritative feature id, so numeric and string ids are
 * handled consistently and never cross-match. Returns null when the candidate
 * cannot be resolved.
 */
function findAuthoritativeFeature(
  source: EditorSource,
  candidate: CandidateFeature,
): import("./model").GeoJSONFeature | null {
  const ids: (string | number | undefined)[] = [];
  const propsId = candidate.properties?.id;
  if (typeof propsId === "string" || typeof propsId === "number") ids.push(propsId);
  if (candidate.id !== undefined) ids.push(candidate.id);

  for (const candidateId of ids) {
    for (const feature of source.data.features) {
      if (feature.id !== undefined && feature.id === candidateId) return feature;
    }
  }
  return null;
}

/** Deterministic order: distance, then stable feature/part refs. */
function sortHits(hits: EditorHit[]): EditorHit[] {
  return hits.slice().sort((a, b) => {
    if (a.distanceM !== b.distanceM) return a.distanceM - b.distanceM;
    if (a.sourceId !== b.sourceId) return a.sourceId < b.sourceId ? -1 : 1;
    if (a.featureId !== b.featureId) return a.featureId < b.featureId ? -1 : 1;
    if (a.kind !== b.kind) return a.kind === "line" ? -1 : 1;
    if (a.kind === "line" && b.kind === "line") {
      if (a.partIndex !== b.partIndex) return a.partIndex - b.partIndex;
      if (a.segmentIndex !== b.segmentIndex) return a.segmentIndex - b.segmentIndex;
      if (a.fraction !== b.fraction) return a.fraction - b.fraction;
    }
    return 0;
  });
}

/**
 * Absolute distance tolerance (metres) for treating two candidate distances as
 * a deterministic tie. Distances are computed in local metric space where
 * mathematically equal candidates can differ by a tiny floating-point epsilon
 * (well below 1e-9 m); genuine differences between distinct parts/points are
 * far larger, so this never collapses real differences.
 */
const DISTANCE_TOLERANCE_M = 1e-9;

/** The line-hit fields chosen by {@link nearestLinePart}. */
interface LinePartChoice {
  partIndex: number;
  segmentIndex: number;
  fraction: number;
  coordinate: Position;
  distanceM: number;
}

/**
 * Choose the single nearest authoritative line part for a query point,
 * recursing through the geometry (including GeometryCollection contents).
 * Returns null when the geometry has no usable line part (e.g. a pure
 * polygon). Mathematically tied distances (within {@link DISTANCE_TOLERANCE_M})
 * resolve to the lowest part index (parts are enumerated in source order).
 */
function nearestLinePart(geometry: import("./model").GeoJSONGeometry, click: Position): LinePartChoice | null {
  const lineParts = enumerateLineParts(geometry);
  let best: LinePartChoice | null = null;
  for (let partIndex = 0; partIndex < lineParts.length; partIndex++) {
    const coords = lineParts[partIndex];
    if (coords.length < 2) continue;
    const nearest = nearestPointOnLine(coords, click);
    // Only a distance more than the tolerance smaller replaces the current
    // best; a within-tolerance (tied) candidate keeps the earlier, lower
    // partIndex because partIndex is visited in ascending order.
    if (best === null || nearest.distanceM < best.distanceM - DISTANCE_TOLERANCE_M) {
      best = {
        partIndex,
        segmentIndex: nearest.segmentIndex,
        fraction: nearest.fraction,
        coordinate: nearest.coordinate,
        distanceM: nearest.distanceM,
      };
    }
  }
  return best;
}

/** The POI fields chosen by {@link nearestPoint}. */
interface PointChoice {
  coordinate: Position;
  distanceM: number;
}

/**
 * Choose the single nearest authoritative point coordinate for a query point,
 * recursing through the geometry (including GeometryCollection contents).
 * Returns null when the geometry has no point part. Mathematically tied
 * distances (within {@link DISTANCE_TOLERANCE_M}) resolve to the lowest point
 * index (points are enumerated in source order).
 */
function nearestPoint(geometry: import("./model").GeoJSONGeometry, click: Position): PointChoice | null {
  const coords = enumeratePointParts(geometry);
  let bestIndex = -1;
  let bestDistance = Infinity;
  for (let i = 0; i < coords.length; i++) {
    const d = distanceM(click, coords[i]);
    // Only a distance more than the tolerance smaller replaces the current
    // best; a within-tolerance (tied) candidate keeps the earlier, lower index
    // because i is visited in ascending order.
    if (d < bestDistance - DISTANCE_TOLERANCE_M) {
      bestDistance = d;
      bestIndex = i;
    }
  }
  if (bestIndex === -1) return null;
  return { coordinate: coords[bestIndex], distanceM: bestDistance };
}

/**
 * Hit-test a geographic click against all registered editor POI/hitbox layers
 * of visible, selectable sources. Returns every overlapping candidate across
 * distinct features/sources in deterministic order; an empty array means no
 * selectable hit.
 *
 * The candidate's originating layer decides its kind: a hitbox-layer candidate
 * yields the single nearest line part; a POI-layer candidate yields the single
 * nearest point coordinate. A candidate that cannot be resolved to an
 * authoritative feature (or is a pure polygon, which yields no line/point
 * parts) is silently dropped.
 */
export function hitTestEditor(
  map: HitTestMap,
  click: Position,
  sources: EditorSource[],
  registry: EditorSourceRegistry,
): EditorHit[] {
  // Only visible + selectable sources are queried; collect their hitbox and
  // POI layer ids and remember which source and kind backs each layer.
  const queryIds: string[] = [];
  const sourceByLayer = new Map<string, EditorSource>();
  const layerKind = new Map<string, "line" | "point">();
  for (const source of sources) {
    if (!source.visible || !source.selectable) continue;
    const ids = registry.bySourceId[source.id];
    if (!ids) continue;
    queryIds.push(ids.hitbox, ids.poi);
    sourceByLayer.set(ids.hitbox, source);
    sourceByLayer.set(ids.poi, source);
    layerKind.set(ids.hitbox, "line");
    layerKind.set(ids.poi, "point");
  }
  if (queryIds.length === 0) return [];

  const candidates = map.queryRenderedFeatures(map.project(click), {
    layers: queryIds,
  });

  const hits: EditorHit[] = [];
  const resolved = new Set<string>(); // dedupe candidate -> (source, feature, kind)
  for (const candidate of candidates) {
    const layerId = candidate?.layer?.id;
    const source = layerId !== undefined ? sourceByLayer.get(layerId) : undefined;
    const kind = layerId !== undefined ? layerKind.get(layerId) : undefined;
    if (!source || kind === undefined) continue;

    const feature = findAuthoritativeFeature(source, candidate);
    if (!feature || !feature.geometry) continue;

    const featureKey = `${source.id}\u0000${String(feature.id)}\u0000${kind}`;
    if (resolved.has(featureKey)) continue; // already processed via another layer
    resolved.add(featureKey);

    const geometry = feature.geometry;

    if (kind === "line") {
      // A hitbox candidate yields only the single nearest line part. Also
      // enforce route-eligibility again at the trust boundary (not only via the
      // rendered hitbox filter): visual diagnostic lines (POI offsets / gaps)
      // are never reported as authoritative line hits.
      if (!isRouteEligibleFeature(feature)) continue;
      const chosen = nearestLinePart(geometry, click);
      if (chosen === null) continue;
      hits.push({
        kind: "line",
        sourceId: source.id,
        featureId: String(feature.id),
        ...chosen,
      });
    } else {
      // A POI candidate yields only the single nearest point coordinate.
      const chosen = nearestPoint(geometry, click);
      if (chosen === null) continue;
      hits.push({
        kind: "poi",
        sourceId: source.id,
        featureId: String(feature.id),
        coordinate: chosen.coordinate,
        distanceM: chosen.distanceM,
      });
    }
  }

  return sortHits(hits);
}
