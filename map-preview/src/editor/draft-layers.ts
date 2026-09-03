/**
 * Shared in-memory GeoJSON draft source/layers for the route editor.
 *
 * A single GeoJSON source (`editor-draft-source`) backs four editor-prefixed
 * runtime layers that visualise the ACTIVE route section only:
 *
 *   - `editor-draft-route`  – solid lines for the section's route legs
 *   - `editor-draft-point`  – circles for the selected POIs and anchors
 *   - `editor-draft-offset` – dashed lines connecting each POI to its anchor
 *   - `editor-draft-gap`    – red dashed lines for exact gaps between legs
 *
 * POI offsets and gaps are purely visualisation aids drawn over the draft
 * source; they never touch the project model and never form joins or legs.
 * The whole draft is rebuilt and pushed through `GeoJSONSource.setData` every
 * time the active section changes. Runtime ids keep the stable `editor-`
 * prefix; nothing here is navigation-grade.
 */

import type { GeoJSONFeature, GeoJSONFeatureCollection, Position, RouteSection } from "./model";
import type { SectionSummary } from "./validation";

export const DRAFT_SOURCE_ID = "editor-draft-source";
export const DRAFT_ROUTE_LAYER_ID = "editor-draft-route";
export const DRAFT_POINT_LAYER_ID = "editor-draft-point";
export const DRAFT_OFFSET_LAYER_ID = "editor-draft-offset";
export const DRAFT_GAP_LAYER_ID = "editor-draft-gap";

/** The minimal MapLibre surface the draft module needs (mockable in tests). */
export interface DraftMap {
  addSource(id: string, spec: unknown): void;
  getSource(id: string): unknown;
  addLayer(layer: object, beforeId?: string): void;
}

/**
 * Build the draft FeatureCollection for an active section. Returns an empty
 * collection for a null section. Features carry a `draftKind` property used
 * to route them to the right runtime layer.
 */
export function buildDraftData(
  section: RouteSection | null,
  summary: SectionSummary | null,
): GeoJSONFeatureCollection {
  const features: GeoJSONFeature[] = [];
  if (!section) return { type: "FeatureCollection", features };

  // Route legs — solid, ordered.
  section.legs.forEach((leg, index) => {
    if (leg.coordinates.length < 2) return;
    features.push({
      type: "Feature",
      id: `editor-draft-leg-${leg.id ?? index}`,
      geometry: { type: "LineString", coordinates: leg.coordinates },
      properties: { draftKind: "route", legIndex: index },
    });
  });

  // Selected POIs and anchors — points.
  const addPoint = (id: string, coord: Position | undefined, draftKind: string): void => {
    if (!coord) return;
    features.push({
      type: "Feature",
      id,
      geometry: { type: "Point", coordinates: coord },
      properties: { draftKind },
    });
  };
  addPoint("editor-draft-fromPoi", section.fromPoi?.coordinate, "poi");
  addPoint("editor-draft-toPoi", section.toPoi?.coordinate, "poi");
  addPoint("editor-draft-fromAnchor", section.fromAnchor?.coordinate, "anchor");
  addPoint("editor-draft-toAnchor", section.toAnchor?.coordinate, "anchor");

  // POI -> anchor offsets — dashed, visualisation only. Only drawn when both
  // the POI and its anchor are present.
  const addOffset = (id: string, from: Position | undefined, to: Position | undefined): void => {
    if (!from || !to) return;
    features.push({
      type: "Feature",
      id,
      geometry: { type: "LineString", coordinates: [from, to] },
      properties: { draftKind: "offset" },
    });
  };
  addOffset("editor-draft-offset-from", section.fromPoi?.coordinate, section.fromAnchor?.coordinate);
  addOffset("editor-draft-offset-to", section.toPoi?.coordinate, section.toAnchor?.coordinate);

  // Exact gaps between legs — red dashed, visualisation only.
  if (summary) {
    summary.gaps.forEach((gap, index) => {
      features.push({
        type: "Feature",
        id: `editor-draft-gap-${index}`,
        geometry: { type: "LineString", coordinates: [gap.from, gap.to] },
        properties: { draftKind: "gap", distanceM: gap.distanceM, betweenLegIndex: gap.betweenLegIndex },
      });
    });
  }

  return { type: "FeatureCollection", features };
}

/**
 * Register the shared draft GeoJSON source and its four runtime layers. Should
 * be called once after the map loads (before any imported source layers, which
 * are inserted below the draft via `beforeId` so the draft stays on top).
 */
export function addDraftLayers(map: DraftMap, beforeId?: string): void {
  map.addSource(DRAFT_SOURCE_ID, {
    type: "geojson",
    data: { type: "FeatureCollection", features: [] },
  });

  // POI -> anchor offsets (bottom).
  map.addLayer(
    {
      id: DRAFT_OFFSET_LAYER_ID,
      type: "line",
      source: DRAFT_SOURCE_ID,
      filter: ["==", ["get", "draftKind"], "offset"],
      paint: {
        "line-color": "#6b7280",
        "line-width": 2,
        "line-dasharray": [3, 3],
        "line-opacity": 0.7,
      },
    },
    beforeId,
  );

  // Route legs.
  map.addLayer(
    {
      id: DRAFT_ROUTE_LAYER_ID,
      type: "line",
      source: DRAFT_SOURCE_ID,
      filter: ["==", ["get", "draftKind"], "route"],
      paint: {
        "line-color": "#c0392b",
        "line-width": 4,
        "line-opacity": 0.95,
      },
    },
    beforeId,
  );

  // Exact gaps — red dashed, above the route so they stay visible.
  map.addLayer(
    {
      id: DRAFT_GAP_LAYER_ID,
      type: "line",
      source: DRAFT_SOURCE_ID,
      filter: ["==", ["get", "draftKind"], "gap"],
      paint: {
        "line-color": "#dc2626",
        "line-width": 3,
        "line-dasharray": [2, 2],
        "line-opacity": 0.95,
      },
    },
    beforeId,
  );

  // Selected POIs (red) and anchors (blue) — topmost.
  map.addLayer(
    {
      id: DRAFT_POINT_LAYER_ID,
      type: "circle",
      source: DRAFT_SOURCE_ID,
      filter: ["in", ["get", "draftKind"], ["literal", ["poi", "anchor"]]],
      paint: {
        "circle-radius": 7,
        "circle-color": [
          "match",
          ["get", "draftKind"],
          "poi",
          "#c0392b",
          "anchor",
          "#1d4ed8",
          "#6b7280",
        ],
        "circle-stroke-color": "#ffffff",
        "circle-stroke-width": 2,
      },
    },
    beforeId,
  );
}

/**
 * Rebuild and push the draft data for the active section onto the shared
 * GeoJSON source via `setData`. No-op when the draft source is absent.
 */
export function updateDraft(
  map: DraftMap,
  section: RouteSection | null,
  summary: SectionSummary | null,
): void {
  const data = buildDraftData(section, summary);
  const src = map.getSource(DRAFT_SOURCE_ID) as
    | { setData(data: GeoJSONFeatureCollection): void }
    | undefined;
  if (src) src.setData(data);
}