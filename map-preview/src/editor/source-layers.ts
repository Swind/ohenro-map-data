/**
 * Runtime MapLibre source/layer management for imported editor sources.
 *
 * Each EditorSource becomes one GeoJSON source plus five editor-prefixed
 * runtime layers:
 *
 *   - polygon `fill` and `outline`  – display-only context (never selectable)
 *   - `line`                       – the line visual (display-only)
 *   - `hitbox`                     – a transparent, extra-wide line layer used
 *                                    purely as a hit-testing target
 *   - `poi`                        – discrete POI circles
 *
 * The transparent hitbox and POI layers are the only layers the hit-test
 * module queries (see hit-test.ts); polygons remain context and are never
 * selectable. No labels or fonts are added in this MVP.
 *
 * All layer/source ids are derived deterministically from the source id and
 * carry a stable `editor-` prefix. Callers keep a single plain-object registry
 * (`EditorSourceRegistry`) mapping source ids to their layer ids; there is no
 * class, framework, or state library involved.
 */

import type { FilterSpecification } from "maplibre-gl";
import type { EditorSource } from "./model";
import { DRAFT_OFFSET_LAYER_ID } from "./draft-layers";
import { ROUTE_ELIGIBLE_LINE_FILTER } from "./line-eligibility";

/**
 * The minimal MapLibre surface the source-layers module needs. A real
 * MapLibre map is structurally compatible; tests use a plain mock so no
 * WebGL context is required.
 */
export interface SourceLayerMap {
  addSource(id: string, spec: unknown): void;
  getSource(id: string): unknown;
  removeSource(id: string): void;
  addLayer(layer: object, beforeId?: string): void;
  getLayer(id: string): unknown;
  removeLayer(id: string): void;
  setLayoutProperty(id: string, prop: string, value: unknown): void;
  setPaintProperty(id: string, prop: string, value: unknown): void;
}

/** Editor-prefixed, stable GeoJSON source id for an editor source. */
export const editorGeoJsonSourceId = (sourceId: string): string =>
  `editor-src-${sourceId}`;

/** Editor-prefixed, stable runtime layer ids for an editor source. */
export const editorFillLayerId = (sourceId: string): string =>
  `editor-${sourceId}-fill`;
export const editorOutlineLayerId = (sourceId: string): string =>
  `editor-${sourceId}-outline`;
export const editorLineLayerId = (sourceId: string): string =>
  `editor-${sourceId}-line`;
export const editorHitboxLayerId = (sourceId: string): string =>
  `editor-${sourceId}-hitbox`;
export const editorPoiLayerId = (sourceId: string): string =>
  `editor-${sourceId}-poi`;

/** The five runtime layer ids belonging to one editor source. */
export interface SourceLayerIds {
  /** The GeoJSON source id on the map (`editor-src-<sourceId>`). */
  sourceId: string;
  fill: string;
  outline: string;
  line: string;
  hitbox: string;
  poi: string;
}

/**
 * A plain registry mapping each registered source id to its runtime layer
 * ids. `hitTestEditor` reads it to know which layers to query.
 */
export interface EditorSourceRegistry {
  bySourceId: Record<string, SourceLayerIds>;
}

/** Create an empty registry. */
export function createEditorSourceRegistry(): EditorSourceRegistry {
  return { bySourceId: {} };
}

/**
 * The `beforeId` to pass to {@link addSourceLayers} so imported sources render
 * below ALL draft layers (draft route, POIs, gaps, and offsets stay on top).
 *
 * The draft stack, from bottom to top, is: offset lines, route legs, gaps,
 * POIs/anchors (see draft-layers.ts). Passing this as `beforeId` inserts the
 * imported source's layers directly below the bottommost draft layer — the
 * POI→anchor offset lines — i.e. below the entire draft. main.ts passes this
 * constant to every addSourceLayers call.
 */
export const DRAFT_LAYER_BEFORE_ID = DRAFT_OFFSET_LAYER_ID;

/** Stable layer ids for a source id (pure; does not touch a map). */
export function layerIdsForSource(sourceId: string): SourceLayerIds {
  return {
    sourceId: editorGeoJsonSourceId(sourceId),
    fill: editorFillLayerId(sourceId),
    outline: editorOutlineLayerId(sourceId),
    line: editorLineLayerId(sourceId),
    hitbox: editorHitboxLayerId(sourceId),
    poi: editorPoiLayerId(sourceId),
  };
}

/** Geometry-type filters: which features each runtime layer renders. */
const lineFilter: FilterSpecification = [
  "any",
  ["==", ["geometry-type"], "LineString"],
  ["==", ["geometry-type"], "MultiLineString"],
];
const pointFilter: FilterSpecification = [
  "any",
  ["==", ["geometry-type"], "Point"],
  ["==", ["geometry-type"], "MultiPoint"],
];
const polygonFilter: FilterSpecification = [
  "any",
  ["==", ["geometry-type"], "Polygon"],
  ["==", ["geometry-type"], "MultiPolygon"],
];

/** All display/query layer ids for a source, in stable removal order. */
function layerIdList(ids: SourceLayerIds): string[] {
  return [ids.fill, ids.outline, ids.line, ids.hitbox, ids.poi];
}

/**
 * Add the GeoJSON source and all five runtime layers for an editor source,
 * registering its layer ids in `registry`. `beforeId` (optional) is passed to
 * each addLayer call to control z-order. Existing layers/sources are left
 * untouched; callers are responsible for removing first if re-adding.
 *
 * Transactional: if any addSource/addLayer throws partway, every layer/source
 * added for this source is removed, no registry entry is left behind, and the
 * error is rethrown — so a caller can never observe a half-installed source.
 */
export function addSourceLayers(
  map: SourceLayerMap,
  source: EditorSource,
  registry: EditorSourceRegistry,
  beforeId?: string,
): SourceLayerIds {
  const ids = layerIdsForSource(source.id);
  const geoSourceId = ids.sourceId;

  // Track exactly what this invocation installed so rollback only ever removes
  // resources this call added. If addSource throws because the id already
  // exists (or for any other reason), `sourceAdded` stays false and nothing is
  // removed; a pre-existing source/layers are never touched by rollback.
  let sourceAdded = false;
  const addedLayerIds: string[] = [];

  try {
    map.addSource(geoSourceId, { type: "geojson", data: source.data });
    sourceAdded = true;

    // Polygon fill — display-only context.
    map.addLayer(
      {
        id: ids.fill,
        type: "fill",
        source: geoSourceId,
        filter: polygonFilter,
        layout: { visibility: source.visible ? "visible" : "none" },
        paint: {
          "fill-color": source.color,
          "fill-opacity": 0.25,
        },
      },
      beforeId,
    );
    addedLayerIds.push(ids.fill);

    // Polygon outline — display-only context.
    map.addLayer(
      {
        id: ids.outline,
        type: "line",
        source: geoSourceId,
        filter: polygonFilter,
        layout: { visibility: source.visible ? "visible" : "none" },
        paint: {
          "line-color": source.color,
          "line-width": 1.5,
          "line-opacity": 0.8,
        },
      },
      beforeId,
    );
    addedLayerIds.push(ids.outline);

    // Line visual — display-only.
    map.addLayer(
      {
        id: ids.line,
        type: "line",
        source: geoSourceId,
        filter: lineFilter,
        layout: { visibility: source.visible ? "visible" : "none" },
        paint: {
          "line-color": source.color,
          "line-width": ["interpolate", ["linear"], ["zoom"], 8, 2, 14, 4],
          "line-opacity": 0.9,
        },
      },
      beforeId,
    );
    addedLayerIds.push(ids.line);

    // Transparent wide line hitbox — invisible but queryable for hit-testing.
    // Paint opacity 0 keeps it invisible while still returned by
    // queryRenderedFeatures (unlike layout visibility "none"). Its filter is
    // the route-eligibility filter (geometry + diagnostic markers) so visual
    // diagnostic lines (POI offsets / gaps) are never discovered as selectable
    // line candidates, while the display `line` visual above still renders them
    // as context.
    map.addLayer(
      {
        id: ids.hitbox,
        type: "line",
        source: geoSourceId,
        filter: ROUTE_ELIGIBLE_LINE_FILTER,
        layout: { visibility: source.visible ? "visible" : "none" },
        paint: {
          "line-color": "rgba(0, 0, 0, 0)",
          "line-width": 16,
          "line-opacity": 0,
        },
      },
      beforeId,
    );
    addedLayerIds.push(ids.hitbox);

    // POI circles.
    map.addLayer(
      {
        id: ids.poi,
        type: "circle",
        source: geoSourceId,
        filter: pointFilter,
        layout: { visibility: source.visible ? "visible" : "none" },
        paint: {
          "circle-radius": 6,
          "circle-color": source.color,
          "circle-stroke-color": "#ffffff",
          "circle-stroke-width": 1.5,
        },
      },
      beforeId,
    );
    addedLayerIds.push(ids.poi);

    registry.bySourceId[source.id] = ids;
    return ids;
  } catch (err) {
    // Roll back only what this invocation successfully added: the source (iff
    // this call created it) plus the layers recorded as installed, removed in
    // reverse order. Pre-existing sources/layers with colliding ids are never
    // removed. The registry is written only after all layers succeed, so there
    // is no new entry to clean here (and a pre-existing entry must survive).
    for (let i = addedLayerIds.length - 1; i >= 0; i -= 1) {
      const layerId = addedLayerIds[i];
      if (map.getLayer(layerId)) map.removeLayer(layerId);
    }
    if (sourceAdded && map.getSource(geoSourceId)) map.removeSource(geoSourceId);
    throw err;
  }
}

/**
 * Remove all runtime layers and the GeoJSON source for an editor source and
 * drop it from the registry. Missing layers/sources are ignored.
 */
export function removeSourceLayers(
  map: SourceLayerMap,
  sourceId: string,
  registry: EditorSourceRegistry,
): void {
  const ids = registry.bySourceId[sourceId];
  if (ids) {
    for (const layerId of layerIdList(ids)) {
      if (map.getLayer(layerId)) map.removeLayer(layerId);
    }
    delete registry.bySourceId[sourceId];
  }
  const geoSourceId = editorGeoJsonSourceId(sourceId);
  if (map.getSource(geoSourceId)) map.removeSource(geoSourceId);
}

/** Toggle the layout visibility of a single runtime layer (no-op if absent). */
function setLayerVisibility(
  map: SourceLayerMap,
  layerId: string,
  visible: boolean,
): void {
  if (map.getLayer(layerId)) {
    map.setLayoutProperty(layerId, "visibility", visible ? "visible" : "none");
  }
}

/** Show or hide every runtime layer of a registered source. */
export function setSourceVisibility(
  map: SourceLayerMap,
  sourceId: string,
  registry: EditorSourceRegistry,
  visible: boolean,
): void {
  const ids = registry.bySourceId[sourceId];
  if (!ids) return;
  for (const layerId of layerIdList(ids)) setLayerVisibility(map, layerId, visible);
}

/**
 * Recolour every display layer of a registered source. The hitbox stays
 * transparent (never recoloured) so it remains a pure hit target.
 */
export function setSourceColor(
  map: SourceLayerMap,
  sourceId: string,
  registry: EditorSourceRegistry,
  color: string,
): void {
  const ids = registry.bySourceId[sourceId];
  if (!ids) return;
  if (map.getLayer(ids.fill)) map.setPaintProperty(ids.fill, "fill-color", color);
  if (map.getLayer(ids.outline)) map.setPaintProperty(ids.outline, "line-color", color);
  if (map.getLayer(ids.line)) map.setPaintProperty(ids.line, "line-color", color);
  if (map.getLayer(ids.poi)) map.setPaintProperty(ids.poi, "circle-color", color);
}

/**
 * Set the opacity of every display layer of a registered source (0..1).
 * The polygon fill stays semi-transparent (25% of the given opacity); the
 * hitbox is never made opaque.
 */
export function setSourceOpacity(
  map: SourceLayerMap,
  sourceId: string,
  registry: EditorSourceRegistry,
  opacity: number,
): void {
  const ids = registry.bySourceId[sourceId];
  if (!ids) return;
  if (map.getLayer(ids.fill)) {
    map.setPaintProperty(ids.fill, "fill-opacity", opacity * 0.25);
  }
  if (map.getLayer(ids.line)) {
    map.setPaintProperty(ids.line, "line-opacity", opacity);
  }
  if (map.getLayer(ids.poi)) {
    map.setPaintProperty(ids.poi, "circle-opacity", opacity);
  }
}
