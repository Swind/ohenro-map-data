/**
 * Pure GeoJSON text -> FeatureCollection parser for the route editor import.
 *
 * JSON input is treated as a trust boundary: coordinates must be finite and
 * in WGS84 bounds, geometry structure is validated (Point cardinality,
 * LineString / linear-ring cardinality), and feature `properties` must be an
 * object or null. Malformed selectable geometry fails (throws) rather than
 * silently guessing; a null geometry is retained with a warning. Altitude
 * (a third coordinate element) is stripped to [lon, lat].
 */

import type { GeoJSONFeature, GeoJSONGeometry, Position } from "./model";

export interface ParsedImport {
  features: GeoJSONFeature[];
  warnings: string[];
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Validate a lon/lat pair and return a finite, in-bounds Position. Throws a
 * useful message when the numbers are not finite or lie outside WGS84 bounds.
 */
export function normalizeLonLat(lon: number, lat: number): Position {
  if (typeof lon !== "number" || typeof lat !== "number") {
    throw new Error(`coordinate values must be numbers (got ${String(lon)}, ${String(lat)})`);
  }
  if (!Number.isFinite(lon) || !Number.isFinite(lat)) {
    throw new Error(`coordinate must be finite (got ${lon}, ${lat})`);
  }
  if (lon < -180 || lon > 180 || lat < -90 || lat > 90) {
    throw new Error(`coordinate out of bounds (lon=${lon}, lat=${lat})`);
  }
  return [lon, lat];
}

/**
 * Parse a single GeoJSON position value ([lon, lat] or [lon, lat, alt]) into a
 * [lon, lat] Position, validating finiteness/bounds and stripping altitude.
 */
export function parseGeoJSONPosition(value: unknown, context: string): Position {
  if (!Array.isArray(value)) {
    throw new Error(`${context}: position must be an array`);
  }
  if (value.length !== 2 && value.length !== 3) {
    throw new Error(`${context}: position must be [lon, lat] or [lon, lat, alt] (got ${value.length} elements)`);
  }
  return normalizeLonLat(value[0] as number, value[1] as number);
}

function parsePositionArray(value: unknown, context: string, min: number): Position[] {
  if (!Array.isArray(value)) {
    throw new Error(`${context}: must be an array of positions`);
  }
  if (value.length < min) {
    throw new Error(`${context}: requires at least ${min} positions (got ${value.length})`);
  }
  return value.map((p, i) => parseGeoJSONPosition(p, `${context}[${i}]`));
}

function validateGeometry(value: unknown, context: string): GeoJSONGeometry {
  if (!isObject(value)) {
    throw new Error(`${context}: geometry must be an object`);
  }
  const type = value.type;
  switch (type) {
    case "Point":
      return { type: "Point", coordinates: parseGeoJSONPosition(value.coordinates, `${context}.coordinates`) };
    case "MultiPoint":
      return { type: "MultiPoint", coordinates: parsePositionArray(value.coordinates, `${context}.coordinates`, 1) };
    case "LineString":
      return { type: "LineString", coordinates: parsePositionArray(value.coordinates, `${context}.coordinates`, 2) };
    case "MultiLineString": {
      if (!Array.isArray(value.coordinates)) {
        throw new Error(`${context}.coordinates: must be an array of LineStrings`);
      }
      return {
        type: "MultiLineString",
        coordinates: value.coordinates.map((l, i) =>
          parsePositionArray(l, `${context}.coordinates[${i}]`, 2),
        ),
      };
    }
    case "Polygon": {
      if (!Array.isArray(value.coordinates)) {
        throw new Error(`${context}.coordinates: must be an array of linear rings`);
      }
      return {
        type: "Polygon",
        coordinates: value.coordinates.map((r, i) =>
          parsePositionArray(r, `${context}.coordinates[${i}]`, 4),
        ),
      };
    }
    case "MultiPolygon": {
      if (!Array.isArray(value.coordinates)) {
        throw new Error(`${context}.coordinates: must be an array of Polygons`);
      }
      return {
        type: "MultiPolygon",
        coordinates: value.coordinates.map((poly, i) => {
          if (!Array.isArray(poly)) {
            throw new Error(`${context}.coordinates[${i}]: must be an array of linear rings`);
          }
          return poly.map((r, j) => parsePositionArray(r, `${context}.coordinates[${i}][${j}]`, 4));
        }),
      };
    }
    case "GeometryCollection": {
      if (!Array.isArray(value.geometries)) {
        throw new Error(`${context}.geometries: must be an array`);
      }
      return {
        type: "GeometryCollection",
        geometries: value.geometries.map((g, i) => validateGeometry(g, `${context}.geometries[${i}]`)),
      };
    }
    default:
      throw new Error(`${context}: unsupported geometry type "${String(type)}"`);
  }
}

function parseFeature(value: unknown, context: string, warnings: string[]): GeoJSONFeature {
  if (!isObject(value)) {
    throw new Error(`${context}: feature must be an object`);
  }
  if (value.type !== "Feature") {
    throw new Error(`${context}: expected type "Feature", got ${JSON.stringify(value.type)}`);
  }
  // Properties are a trust boundary: only object or null is accepted.
  const properties = value.properties;
  if (properties !== null && properties !== undefined && !isObject(properties)) {
    throw new Error(`${context}: properties must be an object or null (JSON trust boundary)`);
  }

  let geometry: GeoJSONGeometry | null;
  if (value.geometry === null || value.geometry === undefined) {
    geometry = null;
    warnings.push(`${context}: null geometry retained`);
  } else {
    geometry = validateGeometry(value.geometry, `${context}.geometry`);
  }

  const feature: GeoJSONFeature = {
    type: "Feature",
    geometry,
    properties: (properties as Record<string, unknown> | null) ?? null,
  };
  if (value.id !== null && value.id !== undefined) {
    if (typeof value.id !== "string" && typeof value.id !== "number") {
      throw new Error(`${context}: feature.id must be a string or number`);
    }
    feature.id = value.id;
  }
  return feature;
}

/**
 * Parse GeoJSON text into a normalized FeatureCollection. Throws on invalid
 * JSON, a non-Feature/non-FeatureCollection root, invalid properties, or
 * malformed selectable geometry; returns warnings for retained null geometry.
 */
export function parseGeoJSON(text: string): ParsedImport {
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch (e) {
    throw new Error(`Invalid GeoJSON JSON: ${(e as Error).message}`);
  }
  if (!isObject(data)) {
    throw new Error("GeoJSON root must be a Feature or FeatureCollection object");
  }

  const warnings: string[] = [];
  const type = data.type;
  if (type === "FeatureCollection") {
    if (!Array.isArray(data.features)) {
      throw new Error("GeoJSON FeatureCollection.features must be an array");
    }
    const features = data.features.map((f, i) => parseFeature(f, `features[${i}]`, warnings));
    return { features, warnings };
  }
  if (type === "Feature") {
    return { features: [parseFeature(data, "root", warnings)], warnings };
  }
  throw new Error(`GeoJSON root must be a Feature or FeatureCollection, got "${String(type)}"`);
}