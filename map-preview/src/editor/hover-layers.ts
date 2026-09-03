/**
 * Authoritative hover highlight for the route editor.
 *
 * Hover uses a single ephemeral GeoJSON source backed by one line layer and
 * one point layer. On every hover it is rebuilt from the AUTHORITATIVE source
 * feature (never from rendered/tiled candidate geometry):
 *
 *   - a `line` hit highlights the FULL authoritative line part at
 *     `hit.partIndex` (via `enumerateLineParts`), so hovering a segment
 *     reveals the whole selectable range the user would extract; it also
 *     emits the part's first/last coordinates as two endpoint Point markers
 *     (`hoverKind: "line-start"` / `"line-end"`) purely to make the line
 *     range easier to pick. These markers are ephemeral visualization only —
 *     they never snap to anything and never affect click/extraction (the
 *     actual leg is still decided by the two clicks' nearest authoritative
 *     positions);
 *   - a `poi` hit highlights exactly the discrete `hit.coordinate`.
 *
 * If the source/feature/part cannot be resolved (or the line is not
 * route-eligible) the source is set to an empty FeatureCollection so nothing
 * is highlighted. Hovering never touches the project/model/history — it only
 * swaps data on this ephemeral source.
 */

import type { EditorHit } from "./hit-test";
import { enumerateLineParts } from "./geometry";
import { isRouteEligibleFeature } from "./line-eligibility";
import type { DraftMap } from "./draft-layers";
import type { EditorSource, GeoJSONFeatureCollection } from "./model";

export const HOVER_SOURCE_ID = "editor-hover-source";
export const HOVER_LINE_LAYER_ID = "editor-hover-line";
export const HOVER_POINT_LAYER_ID = "editor-hover-point";

/** The minimal MapLibre surface the hover module needs (a real map is compatible). */
export interface HoverMap extends DraftMap {}

function empty(): GeoJSONFeatureCollection {
  return { type: "FeatureCollection", features: [] };
}

/**
 * Resolve an authoritative feature for a hit. Returns null when the source or
 * feature id no longer resolves (stale hover candidate).
 */
function resolveFeature(
  hit: EditorHit,
  sources: EditorSource[],
): import("./model").GeoJSONFeature | null {
  const source = sources.find((s) => s.id === hit.sourceId);
  if (!source) return null;
  return (
    source.data.features.find(
      (f) => f.id !== undefined && f.id !== null && String(f.id) === hit.featureId,
    ) ?? null
  );
}

/**
 * Build the ephemeral hover FeatureCollection for a hit. Returns an empty
 * collection when `hit` is null or when the source/feature/part cannot be
 * resolved (or the line feature is not route-eligible). Line hits highlight
 * the full authoritative part at `hit.partIndex`; POI hits highlight the
 * discrete `hit.coordinate`. Purely functional — never mutates any input.
 */
export function buildHoverData(hit: EditorHit | null, sources: EditorSource[]): GeoJSONFeatureCollection {
  if (!hit) return empty();
  const feature = resolveFeature(hit, sources);
  if (!feature || !feature.geometry) return empty();

  if (hit.kind === "poi") {
    return {
      type: "FeatureCollection",
      features: [
        {
          type: "Feature",
          properties: { hoverKind: "poi" },
          geometry: { type: "Point", coordinates: hit.coordinate },
        },
      ],
    };
  }

  // Line hit: highlight the whole authoritative part, not the candidate's
  // possibly simplified/tiled geometry, and never a diagnostic line.
  if (!isRouteEligibleFeature(feature)) return empty();
  const parts = enumerateLineParts(feature.geometry);
  const part = parts[hit.partIndex];
  if (!part || part.length < 2) return empty();
  const start = part[0];
  const end = part[part.length - 1];
  return {
    type: "FeatureCollection",
    features: [
      {
        type: "Feature",
        properties: { hoverKind: "line" },
        geometry: { type: "LineString", coordinates: part },
      },
      {
        type: "Feature",
        properties: { hoverKind: "line-start" },
        geometry: { type: "Point", coordinates: start },
      },
      {
        type: "Feature",
        properties: { hoverKind: "line-end" },
        geometry: { type: "Point", coordinates: end },
      },
    ],
  };
}

/**
 * Register the ephemeral hover GeoJSON source and its line/point layers.
 * Call once after the map loads, passing the draft route layer id (or another
 * beforeId) so the hover sits ABOVE imported sources but BELOW the draft
 * route/POIs. The source starts empty.
 */
export function addHoverLayers(map: HoverMap, beforeId?: string): void {
  map.addSource(HOVER_SOURCE_ID, {
    type: "geojson",
    data: { type: "FeatureCollection", features: [] },
  });

  // Hover line — bright, wide, high-contrast cyan.
  map.addLayer(
    {
      id: HOVER_LINE_LAYER_ID,
      type: "line",
      source: HOVER_SOURCE_ID,
      filter: ["==", ["geometry-type"], "LineString"],
      layout: {
        "line-cap": "round",
        "line-join": "round",
      },
      paint: {
        "line-color": "#00e5ff",
        "line-width": 8,
        "line-opacity": 0.9,
      },
    },
    beforeId,
  );

  // Hover point — large, high-contrast, dark ring. Start/end markers on a
  // hovered line part are colour-coded (green start / orange end, POI yellow)
  // so the selectable range is easy to distinguish; all keep the dark stroke.
  map.addLayer(
    {
      id: HOVER_POINT_LAYER_ID,
      type: "circle",
      source: HOVER_SOURCE_ID,
      filter: ["==", ["geometry-type"], "Point"],
      paint: {
        "circle-radius": [
          "match",
          ["get", "hoverKind"],
          "line-start",
          12,
          "line-end",
          12,
          "poi",
          11,
          11,
        ],
        "circle-color": [
          "match",
          ["get", "hoverKind"],
          "line-start",
          "#00c853",
          "line-end",
          "#ff6d00",
          "poi",
          "#ffe600",
          "#ffe600",
        ],
        "circle-stroke-color": "#0b2545",
        "circle-stroke-width": 3,
      },
    },
    beforeId,
  );
}

/**
 * Push hover data for a hit onto the shared ephemeral source via `setData`.
 * A null/missing hit (or unresolvable candidate) clears the highlight because
 * `buildHoverData` returns an empty collection. No-op when the hover source is
 * absent (e.g. before the map has loaded). Never increments a revision or
 * creates a history checkpoint.
 */
export function updateHover(
  map: HoverMap,
  hit: EditorHit | null,
  sources: EditorSource[],
): void {
  const data = buildHoverData(hit, sources);
  const src = map.getSource(HOVER_SOURCE_ID) as
    | { setData(data: GeoJSONFeatureCollection): void }
    | undefined;
  if (src) src.setData(data);
}
