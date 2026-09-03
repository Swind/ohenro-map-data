/**
 * JSON-safe data model for the offline route editor core.
 *
 * This is deliberately minimal: only the geometry/feature types and the
 * project container needed by the route editor. No routing graph, no joins,
 * no navigation entities.
 */

/** A WGS84 coordinate pair: [longitude, latitude]. */
export type Position = [number, number];

/** JSON-safe GeoJSON geometry union (all coordinates WGS84). */
export type GeoJSONGeometry =
  | { type: "Point"; coordinates: Position }
  | { type: "MultiPoint"; coordinates: Position[] }
  | { type: "LineString"; coordinates: Position[] }
  | { type: "MultiLineString"; coordinates: Position[][] }
  | { type: "Polygon"; coordinates: Position[][] }
  | { type: "MultiPolygon"; coordinates: Position[][][] }
  | { type: "GeometryCollection"; geometries: GeoJSONGeometry[] };

/** A GeoJSON feature with JSON-safe properties. */
export interface GeoJSONFeature {
  type: "Feature";
  geometry: GeoJSONGeometry | null;
  properties: Record<string, unknown> | null;
  id?: string | number;
}

/** A GeoJSON feature collection. */
export interface GeoJSONFeatureCollection {
  type: "FeatureCollection";
  features: GeoJSONFeature[];
}

/**
 * A user-imported, immutable source layer. `data` is the authoritative
 * geometry; `importWarnings` records non-fatal issues found during import.
 */
export interface EditorSource {
  id: string;
  name: string;
  sha256: string;
  format: string;
  color: string;
  visible: boolean;
  selectable: boolean;
  data: GeoJSONFeatureCollection;
  importWarnings: string[];
}

/**
 * A reference to a point lying on an authoritative line part of a source.
 *
 * - `partIndex` selects which line part of the feature (0 for a
 *   LineString; the matching index for a MultiLineString part).
 * - `segmentIndex` selects the segment of that part ([i, i+1] vertices).
 * - `fraction` is the position along that segment, 0..1.
 * - `coordinate` is the resolved WGS84 point (a source vertex when the
 *   fraction is effectively 0 or 1).
 */
export interface LinePointRef {
  sourceId: string;
  featureId: string;
  partIndex: number;
  segmentIndex: number;
  fraction: number;
  coordinate: Position;
}

/** A reference to a discrete POI point. */
export interface PoiRef {
  sourceId: string;
  featureId: string;
  coordinate: Position;
}

/**
 * A single contiguous piece of route following one authoritative line part.
 * `coordinates` is the full ordered vertex list for the leg (the extraction
 * of the range between `start` and `end`), with `lengthM` its metric length.
 */
export interface RouteLeg {
  id: string;
  sourceId: string;
  featureId: string;
  partIndex: number;
  start: LinePointRef;
  end: LinePointRef;
  direction: "forward" | "reverse";
  coordinates: Position[];
  lengthM: number;
}

/**
 * A route section between two POIs, composed of one or more contiguous legs.
 * `waypoints` are optional intermediate anchor refs kept for UI/export.
 *
 * The POI and anchor references are nullable because sections are built
 * incrementally (a section may exist before its anchors/POIs are resolved);
 * validation reports missing values as issues rather than rejecting them.
 *
 * `humanSelected` is an optional flag carried through persistence/export: in
 * this MVP every section is created by the user in the editor (there is no
 * auto-joining), but the field is kept optional so future auto-derived
 * sections can be distinguished from hand-built ones.
 */
export interface RouteSection {
  id: string;
  /** Whether the section was created/edited by a human (vs. auto-derived). */
  humanSelected?: boolean;
  fromPoi: PoiRef | null;
  toPoi: PoiRef | null;
  fromAnchor: LinePointRef | null;
  toAnchor: LinePointRef | null;
  waypoints: LinePointRef[];
  legs: RouteLeg[];
}

/** The top-level editor project container (schema_version 1). */
export interface EditorProject {
  schema_version: 1;
  kind: "ohenro_route_editor_project";
  projectId: string;
  sources: EditorSource[];
  sections: RouteSection[];
}