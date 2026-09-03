/**
 * Project persistence for the route editor.
 *
 * `serializeProject` produces deterministic, pretty, recursively-key-sorted
 * JSON with a trailing newline and no timestamp (stable across runs and
 * machine-independent). `parseProject` treats JSON as an untrusted trust
 * boundary: it re-validates the embedded normalized source FeatureCollections
 * and reconstructs every RouteLeg's coordinates, direction and length from the
 * authoritative source geometry — never trusting saved derived values.
 *
 * Download helper (`downloadText`) is provided for the browser UI.
 */

import type {
  EditorProject,
  EditorSource,
  GeoJSONFeature,
  LinePointRef,
  PoiRef,
  Position,
  RouteLeg,
  RouteSection,
} from "./model";
import {
  EPSILON,
  enumerateLineParts,
  enumeratePointParts,
  extractLineRange,
  isValidPosition,
  lineLengthM,
  projectPoint,
  unprojectPoint,
} from "./geometry";
import { parseGeoJSON } from "./import-geojson";

/** A parsed, re-validated normalized FeatureCollection keyed by feature id. */
interface SourceIndex {
  source: EditorSource;
  features: Map<string, FeatureRef>;
}

/** Per-feature precomputed authoritative geometry lookup data. */
interface FeatureRef {
  feature: GeoJSONFeature;
  lineParts: Position[][];
  pointCoords: Position[];
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Exact WGS84 coordinate equality (JSON round-trip exactness). */
function samePosition(a: Position, b: Position): boolean {
  return a[0] === b[0] && a[1] === b[1];
}

/**
 * Recursively sort object keys (array order is preserved). Returns a new
 * tree; nothing is mutated. Keys are copied with `Object.defineProperty` so
 * the literal key `"__proto__"` is preserved as an own JSON property rather
 * than mutating the output's prototype (which plain `out[key] = ...` would).
 */
function sortKeys(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortKeys);
  if (isObject(value)) {
    const out: Record<string, unknown> = {};
    for (const key of Object.keys(value).sort()) {
      Object.defineProperty(out, key, {
        value: sortKeys(value[key]),
        enumerable: true,
        writable: true,
        configurable: true,
      });
    }
    return out;
  }
  return value;
}

/**
 * Serialize any JSON-safe value to deterministic pretty JSON: two-space
 * indentation, recursively sorted object keys, array order preserved, trailing
 * newline, and no timestamp. Two structurally-equal values always produce
 * identical bytes regardless of original object-key insertion order.
 */
export function serializeJson(value: unknown): string {
  return JSON.stringify(sortKeys(value), null, 2) + "\n";
}

/**
 * Serialize a project to deterministic pretty JSON (see {@link serializeJson}).
 */
export function serializeProject(project: EditorProject): string {
  return serializeJson(project);
}

/** The coordinate a segment/fraction ref resolves to on a line part. */
function resolveRefCoordinate(
  part: Position[],
  segmentIndex: number,
  fraction: number,
): Position {
  if (fraction <= EPSILON) return part[segmentIndex];
  if (fraction >= 1 - EPSILON) return part[segmentIndex + 1];
  const [ax, ay] = projectPoint(part[segmentIndex]);
  const [bx, by] = projectPoint(part[segmentIndex + 1]);
  return unprojectPoint([ax + (bx - ax) * fraction, ay + (by - ay) * fraction]);
}

/**
 * Validate a line ref that must be consistent with a leg's top-level
 * sourceId/featureId/partIndex and reject stale/tampered coordinates.
 */
function assertLineRef(
  sourceIndex: Map<string, SourceIndex>,
  ref: unknown,
  expSourceId: string,
  expFeatureId: string,
  expPartIndex: number,
  label: string,
): LinePointRef {
  if (!isObject(ref)) throw new Error(`${label}: ref must be an object`);
  if (ref.sourceId !== expSourceId) {
    throw new Error(`${label}: sourceId mismatch (expected "${expSourceId}", got "${String(ref.sourceId)}")`);
  }
  if (ref.featureId !== expFeatureId) {
    throw new Error(`${label}: featureId mismatch (expected "${expFeatureId}", got "${String(ref.featureId)}")`);
  }
  if (ref.partIndex !== expPartIndex) {
    throw new Error(`${label}: partIndex mismatch (expected ${expPartIndex}, got ${String(ref.partIndex)})`);
  }
  const src = sourceIndex.get(expSourceId);
  const feat = src?.features.get(expFeatureId);
  if (!src || !feat) {
    throw new Error(`${label}: unresolved source/feature ${expSourceId}/${expFeatureId}`);
  }
  const parts = feat.lineParts;
  if (!Number.isInteger(expPartIndex) || expPartIndex < 0 || expPartIndex >= parts.length) {
    throw new Error(`${label}: out-of-range partIndex ${expPartIndex} (source has ${parts.length} line parts)`);
  }
  const part = parts[expPartIndex];
  if (part.length < 2) throw new Error(`${label}: line part has fewer than 2 coordinates`);
  const segmentIndex = ref.segmentIndex;
  const fraction = ref.fraction;
  const savedCoordinate = ref.coordinate;
  if (typeof segmentIndex !== "number" || !Number.isInteger(segmentIndex) || segmentIndex < 0 || segmentIndex >= part.length - 1) {
    throw new Error(`${label}: out-of-range segmentIndex ${String(segmentIndex)} (part has ${part.length - 1} segments)`);
  }
  if (typeof fraction !== "number" || !Number.isFinite(fraction) || fraction < 0 || fraction > 1) {
    throw new Error(`${label}: invalid fraction ${String(fraction)}`);
  }
  const coordinate = resolveRefCoordinate(part, segmentIndex, fraction);
  if (savedCoordinate !== undefined && savedCoordinate !== null) {
    if (!isValidPosition(savedCoordinate)) throw new Error(`${label}: invalid coordinate`);
    if (!samePosition(savedCoordinate, coordinate)) {
      throw new Error(
        `${label}: stale coordinate; does not match the source geometry ` +
          `(saved [${String(savedCoordinate)}], resolved [${coordinate[0]},${coordinate[1]}])`,
      );
    }
  }
  return {
    sourceId: expSourceId,
    featureId: expFeatureId,
    partIndex: expPartIndex,
    segmentIndex,
    fraction,
    coordinate,
  };
}

/** Validate a standalone line ref (anchors, waypoints) using its own fields. */
function validateLineRef(
  sourceIndex: Map<string, SourceIndex>,
  ref: unknown,
  label: string,
): LinePointRef {
  if (!isObject(ref)) throw new Error(`${label}: ref must be an object`);
  const sourceId = ref.sourceId;
  const featureId = ref.featureId;
  const partIndex = ref.partIndex;
  if (typeof sourceId !== "string" || sourceId.length === 0) {
    throw new Error(`${label}: sourceId must be a nonempty string`);
  }
  if (typeof featureId !== "string" || featureId.length === 0) {
    throw new Error(`${label}: featureId must be a nonempty string`);
  }
  if (typeof partIndex !== "number" || !Number.isInteger(partIndex)) {
    throw new Error(`${label}: partIndex must be an integer`);
  }
  return assertLineRef(sourceIndex, ref, sourceId, featureId, partIndex, label);
}

/** Validate a POI ref: coordinate must exactly match an authoritative point. */
function validatePoiRef(
  sourceIndex: Map<string, SourceIndex>,
  ref: unknown,
  label: string,
): PoiRef {
  if (!isObject(ref)) throw new Error(`${label}: POI ref must be an object`);
  const sourceId = ref.sourceId;
  const featureId = ref.featureId;
  const coordinate = ref.coordinate;
  if (typeof sourceId !== "string" || sourceId.length === 0) {
    throw new Error(`${label}: sourceId must be a nonempty string`);
  }
  if (typeof featureId !== "string" || featureId.length === 0) {
    throw new Error(`${label}: featureId must be a nonempty string`);
  }
  const feat = sourceIndex.get(sourceId)?.features.get(featureId);
  if (!feat) {
    throw new Error(`${label}: unresolved source/feature ${sourceId}/${featureId}`);
  }
  if (!isValidPosition(coordinate)) {
    throw new Error(`${label}: invalid POI coordinate`);
  }
  const matches = feat.pointCoords.some((c) => c[0] === coordinate[0] && c[1] === coordinate[1]);
  if (!matches) {
    throw new Error(
      `${label}: POI coordinate [${coordinate[0]},${coordinate[1]}] does not match ` +
        `any authoritative point in feature "${featureId}"`,
    );
  }
  return {
    sourceId,
    featureId,
    coordinate: [coordinate[0], coordinate[1]],
  };
}

/**
 * Reconstruct one leg from its sourceId/featureId/partIndex/start/end refs.
 * Coordinates, direction and length are always recomputed from the embedded
 * authoritative source geometry via extractLineRange/lineLengthM; the saved
 * derived coordinates/length are never trusted.
 */
function reconstructLeg(
  sourceIndex: Map<string, SourceIndex>,
  leg: unknown,
  sectionId: string,
  index: number,
): RouteLeg {
  const label = `section "${sectionId}" leg ${index}`;
  if (!isObject(leg)) throw new Error(`${label}: leg must be an object`);
  const legId = leg.id;
  const sourceId = leg.sourceId;
  const featureId = leg.featureId;
  const partIndex = leg.partIndex;
  if (typeof legId !== "string" || legId.length === 0) {
    throw new Error(`${label}: id must be a nonempty string`);
  }
  if (typeof sourceId !== "string" || sourceId.length === 0) {
    throw new Error(`${label}: sourceId must be a nonempty string`);
  }
  if (typeof featureId !== "string" || featureId.length === 0) {
    throw new Error(`${label}: featureId must be a nonempty string`);
  }
  const src = sourceIndex.get(sourceId);
  if (!src) throw new Error(`${label}: unknown sourceId "${sourceId}"`);
  const feat = src.features.get(featureId);
  if (!feat) throw new Error(`${label}: unknown featureId "${featureId}" in source "${sourceId}"`);
  if (typeof partIndex !== "number" || !Number.isInteger(partIndex) || partIndex < 0 || partIndex >= feat.lineParts.length) {
    throw new Error(
      `${label}: out-of-range partIndex ${String(partIndex)} (source has ${feat.lineParts.length} line parts)`,
    );
  }
  const part = feat.lineParts[partIndex];
  if (part.length < 2) throw new Error(`${label}: line part has fewer than 2 coordinates`);

  const start = assertLineRef(
    sourceIndex,
    leg.start,
    sourceId,
    featureId,
    partIndex,
    `${label} start`,
  );
  const end = assertLineRef(
    sourceIndex,
    leg.end,
    sourceId,
    featureId,
    partIndex,
    `${label} end`,
  );

  const { coordinates, direction } = extractLineRange(
    part,
    { segmentIndex: start.segmentIndex, fraction: start.fraction },
    { segmentIndex: end.segmentIndex, fraction: end.fraction },
  );
  if (coordinates.length < 2) {
    throw new Error(`${label}: reconstructed fewer than 2 coordinates`);
  }
  if (!samePosition(start.coordinate, coordinates[0])) {
    throw new Error(`${label}: start coordinate does not match reconstructed range start`);
  }
  if (!samePosition(end.coordinate, coordinates[coordinates.length - 1])) {
    throw new Error(`${label}: end coordinate does not match reconstructed range end`);
  }

  return {
    id: legId,
    sourceId,
    featureId,
    partIndex,
    start,
    end,
    direction,
    coordinates,
    lengthM: lineLengthM(coordinates),
  };
}

/** Validate a single source's basic fields and normalized FeatureCollection. */
function parseSource(value: unknown, label: string): { source: EditorSource; index: SourceIndex } {
  if (!isObject(value)) throw new Error(`${label}: source must be an object`);
  const id = value.id;
  const name = value.name;
  const sha256 = value.sha256;
  const format = value.format;
  const color = value.color;
  const visible = value.visible;
  const selectable = value.selectable;
  const importWarnings = value.importWarnings;
  if (typeof id !== "string" || id.length === 0) {
    throw new Error(`${label}: id must be a nonempty string`);
  }
  if (typeof name !== "string") throw new Error(`${label}: name must be a string`);
  if (typeof sha256 !== "string" || !/^[0-9a-f]{64}$/.test(sha256)) {
    throw new Error(`${label}: sha256 must be a 64-character lowercase hex string`);
  }
  // The source id is derived from the hash: SRC_<first 16 hex chars>. Reject
  // ids that do not match their sha256 (no independent id/hash validation).
  if (id !== `SRC_${sha256.slice(0, 16)}`) {
    throw new Error(
      `${label}: source id "${id}" does not match sha256 (expected "SRC_${sha256.slice(0, 16)}")`,
    );
  }
  if (typeof format !== "string") throw new Error(`${label}: format must be a string`);
  // Only the two supported import formats are accepted, so a malformed value
  // can never reach MapLibre/export as an unknown type.
  if (format !== "geojson" && format !== "kml") {
    throw new Error(`${label}: format must be "geojson" or "kml" (got ${JSON.stringify(format)})`);
  }
  if (typeof color !== "string") throw new Error(`${label}: color must be a string`);
  // Browser color-input-compatible #RRGGBB (hex digits case-insensitive).
  if (!/^#[0-9a-fA-F]{6}$/.test(color)) {
    throw new Error(`${label}: color must be a #RRGGBB hex string (got ${JSON.stringify(color)})`);
  }
  if (typeof visible !== "boolean") throw new Error(`${label}: visible must be a boolean`);
  if (typeof selectable !== "boolean") {
    throw new Error(`${label}: selectable must be a boolean`);
  }
  if (!Array.isArray(importWarnings) || !importWarnings.every((w) => typeof w === "string")) {
    throw new Error(`${label}: importWarnings must be an array of strings`);
  }
  if (!isObject(value.data) || value.data.type !== "FeatureCollection" || !Array.isArray(value.data.features)) {
    throw new Error(`${label}: data must be a FeatureCollection`);
  }

  // Re-validate the normalized FeatureCollection at the trust boundary (the
  // same parser used at import) and require a nonempty, unique string id on
  // every feature (the authoritative reference key).
  let parsed: ReturnType<typeof parseGeoJSON>;
  try {
    parsed = parseGeoJSON(JSON.stringify(value.data));
  } catch (e) {
    throw new Error(`${label}: invalid normalized FeatureCollection: ${(e as Error).message}`);
  }
  const features = parsed.features;
  const featureIndex = new Map<string, FeatureRef>();
  const seenIds = new Set<string>();
  for (let j = 0; j < features.length; j++) {
    const f = features[j];
    const fid = f.id;
    if (typeof fid !== "string" || fid.length === 0) {
      throw new Error(`${label}: feature ${j} must have a nonempty string id`);
    }
    if (seenIds.has(fid)) throw new Error(`${label}: duplicate feature id "${fid}"`);
    seenIds.add(fid);
    const geom = f.geometry;
    featureIndex.set(fid, {
      feature: f,
      lineParts: geom ? enumerateLineParts(geom) : [],
      pointCoords: geom ? enumeratePointParts(geom) : [],
    });
  }

  const source: EditorSource = {
    id,
    name,
    sha256,
    format,
    color,
    visible,
    selectable,
    data: { type: "FeatureCollection", features },
    importWarnings: [...importWarnings],
  };
  return { source, index: { source, features: featureIndex } };
}

/**
 * Parse an untrusted project JSON document into a normalized EditorProject.
 *
 * Enforces schema_version 1, the expected kind and a nonempty projectId;
 * unique source/section/feature ids; validates normalized source
 * FeatureCollections and source hashes/IDs/basic fields; validates that every
 * POI/line ref resolves to an embedded authoritative source feature; and
 * reconstructs every leg's coordinates/direction/length from the source
 * geometry. Stale or malformed references throw a useful error — nothing is
 * guessed and saved derived geometry is never trusted.
 */
export function parseProject(text: string): EditorProject {
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch (e) {
    throw new Error(`Invalid project JSON: ${(e as Error).message}`);
  }
  if (!isObject(data)) throw new Error("Project root must be an object");
  if (data.schema_version !== 1) {
    throw new Error(`Unsupported schema_version (expected 1, got ${JSON.stringify(data.schema_version)})`);
  }
  if (data.kind !== "ohenro_route_editor_project") {
    throw new Error(`Unexpected kind "${String(data.kind)}"`);
  }
  const projectId = data.projectId;
  if (typeof projectId !== "string" || !/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(projectId)) {
    throw new Error("projectId must be 1-128 filename-safe ASCII characters");
  }
  if (!Array.isArray(data.sources)) throw new Error("sources must be an array");
  if (!Array.isArray(data.sections)) throw new Error("sections must be an array");

  // --- Sources ---
  const sources: EditorSource[] = [];
  const sourceIndex = new Map<string, SourceIndex>();
  const seenSourceIds = new Set<string>();
  for (let i = 0; i < data.sources.length; i++) {
    const label = `sources[${i}]`;
    const { source, index } = parseSource(data.sources[i], label);
    if (seenSourceIds.has(source.id)) throw new Error(`${label}: duplicate source id "${source.id}"`);
    seenSourceIds.add(source.id);
    sources.push(source);
    sourceIndex.set(source.id, index);
  }

  // --- Sections ---
  const sections: RouteSection[] = [];
  const seenSectionIds = new Set<string>();
  for (let i = 0; i < data.sections.length; i++) {
    const sec = data.sections[i];
    const label = `sections[${i}]`;
    if (!isObject(sec)) throw new Error(`${label}: section must be an object`);
    const sectionId = sec.id;
    if (typeof sectionId !== "string" || sectionId.length === 0) {
      throw new Error(`${label}: id must be a nonempty string`);
    }
    if (seenSectionIds.has(sectionId)) throw new Error(`${label}: duplicate section id "${sectionId}"`);
    seenSectionIds.add(sectionId);

    const fromPoi =
      sec.fromPoi === null || sec.fromPoi === undefined
        ? null
        : validatePoiRef(sourceIndex, sec.fromPoi, `${label} fromPoi`);
    const toPoi =
      sec.toPoi === null || sec.toPoi === undefined
        ? null
        : validatePoiRef(sourceIndex, sec.toPoi, `${label} toPoi`);
    const fromAnchor =
      sec.fromAnchor === null || sec.fromAnchor === undefined
        ? null
        : validateLineRef(sourceIndex, sec.fromAnchor, `${label} fromAnchor`);
    const toAnchor =
      sec.toAnchor === null || sec.toAnchor === undefined
        ? null
        : validateLineRef(sourceIndex, sec.toAnchor, `${label} toAnchor`);

    if (!Array.isArray(sec.waypoints)) throw new Error(`${label}: waypoints must be an array`);
    const waypoints = sec.waypoints.map((w, wi) =>
      validateLineRef(sourceIndex, w, `${label} waypoint ${wi}`),
    );

    if (!Array.isArray(sec.legs)) throw new Error(`${label}: legs must be an array`);
    const legs = sec.legs.map((leg, li) => reconstructLeg(sourceIndex, leg, sectionId, li));

    let humanSelected: boolean | undefined;
    if (sec.humanSelected !== undefined) {
      if (typeof sec.humanSelected !== "boolean") {
        throw new Error(`${label}: humanSelected must be a boolean`);
      }
      humanSelected = sec.humanSelected;
    }

    const section: RouteSection = {
      id: sectionId,
      fromPoi,
      toPoi,
      fromAnchor,
      toAnchor,
      waypoints,
      legs,
    };
    if (humanSelected !== undefined) section.humanSelected = humanSelected;
    sections.push(section);
  }

  return {
    schema_version: 1,
    kind: "ohenro_route_editor_project",
    projectId,
    sources,
    sections,
  };
}

/**
 * Trigger a browser download of `text` as a file via Blob + object URL.
 * Browser-only; revokes the object URL after initiating the click.
 */
export function downloadText(filename: string, text: string, mime = "application/octet-stream"): void {
  const blob = new Blob([text], { type: mime });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
