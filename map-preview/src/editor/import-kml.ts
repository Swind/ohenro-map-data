/**
 * KML text -> FeatureCollection parser for the route editor import.
 *
 * Uses the browser `DOMParser` (never regex) to build a DOM, then walks
 * Document/Folder/Placemark preserving name, a plain `description` string
 * (via textContent, so HTML is never injected or executed), ExtendedData
 * values, and the folder path / source order. Point, LineString, Polygon
 * (outer + inner rings) and recursive MultiGeometry are supported; altitude
 * is stripped. Unsupported geometry yields an import warning; malformed
 * selectable geometry throws a useful error rather than silently guessing.
 */

import type { GeoJSONFeature, GeoJSONGeometry, Position } from "./model";
import { normalizeLonLat, type ParsedImport } from "./import-geojson";

/** KML geometry element names we recognise but do not support (warning only). */
const KNOWN_GEOMETRY = new Set([
  "Point",
  "LineString",
  "LinearRing",
  "Polygon",
  "MultiGeometry",
  "Model",
  "Track",
  "MultiTrack",
  "gx:Track",
  "gx:MultiTrack",
]);

/** XML `Element` node type constant (stable across browsers and xmldom). */
const ELEMENT_NODE = 1;

/** Local (namespace-prefix-free) tag name of an element. */
function localNameOf(el: Element): string {
  const local = el.localName;
  if (local) return local;
  const name = el.nodeName;
  const colon = name.indexOf(":");
  return colon === -1 ? name : name.slice(colon + 1);
}

/** Direct child elements of `el` (all tags), via childNodes + nodeType. */
function elementChildren(el: Element): Element[] {
  const out: Element[] = [];
  const nodes = el.childNodes;
  for (let i = 0; i < nodes.length; i++) {
    if (nodes[i].nodeType === ELEMENT_NODE) out.push(nodes[i] as Element);
  }
  return out;
}

/** Direct child elements of `el` whose local tag name equals `tag`. */
function directChildren(el: Element, tag: string): Element[] {
  return elementChildren(el).filter((c) => localNameOf(c) === tag);
}

/** Trimmed text of the first direct child with tag `tag`, or undefined. */
function childText(el: Element, tag: string): string | undefined {
  const c = directChildren(el, tag)[0];
  return c ? (c.textContent ?? "").trim() || undefined : undefined;
}

/** Parse a `<coordinates>` element body ("lon,lat[,alt] ...") to positions. */
function parseKmlCoordinates(el: Element, context: string): Position[] {
  const c = directChildren(el, "coordinates")[0];
  if (!c) throw new Error(`${context}: missing <coordinates>`);
  const text = (c.textContent ?? "").trim();
  const tokens = text.length ? text.split(/\s+/) : [];
  const out: Position[] = [];
  for (const token of tokens) {
    const parts = token.split(",");
    if (parts.length < 2) {
      throw new Error(`${context}: malformed coordinate "${token}"`);
    }
    out.push(normalizeLonLat(Number(parts[0]), Number(parts[1])));
  }
  return out;
}

function parsePoint(el: Element, context: string): GeoJSONGeometry {
  const coords = parseKmlCoordinates(el, context);
  if (coords.length !== 1) {
    throw new Error(`${context}: Point must contain exactly one coordinate (got ${coords.length})`);
  }
  return { type: "Point", coordinates: coords[0] };
}

function parseLineString(el: Element, context: string): GeoJSONGeometry {
  const coords = parseKmlCoordinates(el, context);
  if (coords.length < 2) {
    throw new Error(`${context}: LineString requires at least 2 coordinates (got ${coords.length})`);
  }
  return { type: "LineString", coordinates: coords };
}

/** Parse the LinearRing inside an outerBoundaryIs / innerBoundaryIs. */
function parseRing(el: Element, context: string): Position[] {
  const ring = directChildren(el, "LinearRing")[0];
  if (!ring) throw new Error(`${context}: missing <LinearRing>`);
  const coords = parseKmlCoordinates(ring, `${context}.LinearRing`);
  if (coords.length < 4) {
    throw new Error(`${context}: LinearRing requires at least 4 coordinates (got ${coords.length})`);
  }
  return coords;
}

function parsePolygon(el: Element, context: string): GeoJSONGeometry {
  const outer = directChildren(el, "outerBoundaryIs");
  if (outer.length === 0) {
    throw new Error(`${context}: Polygon requires an outerBoundaryIs`);
  }
  const rings: Position[][] = [parseRing(outer[0], `${context}.outerBoundaryIs`)];
  for (const inner of directChildren(el, "innerBoundaryIs")) {
    rings.push(parseRing(inner, `${context}.innerBoundaryIs`));
  }
  return { type: "Polygon", coordinates: rings };
}

/** Recursively collect supported geometries (MultiGeometry flattens). */
function collectGeometries(el: Element, label: string, warnings: string[]): GeoJSONGeometry[] {
  const out: GeoJSONGeometry[] = [];
  for (const child of elementChildren(el)) {
    const tag = localNameOf(child);
    if (tag === "Point") {
      out.push(parsePoint(child, `${label} Point`));
    } else if (tag === "LineString") {
      out.push(parseLineString(child, `${label} LineString`));
    } else if (tag === "Polygon") {
      out.push(parsePolygon(child, `${label} Polygon`));
    } else if (tag === "MultiGeometry") {
      out.push(...collectGeometries(child, label, warnings));
    } else if (KNOWN_GEOMETRY.has(tag)) {
      warnings.push(`${label}: unsupported KML geometry <${tag}> skipped`);
    }
  }
  return out;
}

function buildGeometry(list: GeoJSONGeometry[]): GeoJSONGeometry | null {
  if (list.length === 0) return null;
  if (list.length === 1) return list[0];
  return { type: "GeometryCollection", geometries: list };
}

/** Read Data / SchemaData values from ExtendedData (plain text only). */
function readExtendedData(el: Element): Record<string, unknown> {
  // Null-prototype so the literal key "__proto__" becomes an own property
  // instead of mutating the object's prototype.
  const out: Record<string, unknown> = Object.create(null);
  const ext = directChildren(el, "ExtendedData")[0];
  if (!ext) return out;
  for (const child of elementChildren(ext)) {
    const tag = localNameOf(child);
    if (tag === "Data") {
      const name = child.getAttribute("name");
      if (name !== null) out[name] = childText(child, "value") ?? "";
    } else if (tag === "SchemaData") {
      for (const sd of elementChildren(child)) {
        if (localNameOf(sd) === "SimpleData") {
          const name = sd.getAttribute("name");
          if (name !== null) out[name] = (sd.textContent ?? "").trim();
        }
      }
    }
  }
  return out;
}

function parsePlacemark(el: Element, folderPath: string[], warnings: string[]): GeoJSONFeature {
  const name = childText(el, "name");
  const label = name ? `Placemark "${name}"` : "Placemark";
  const description = childText(el, "description");
  const kmlId = el.getAttribute("id") ?? undefined;
  const extended = readExtendedData(el);

  // Null-prototype so an ExtendedData key of "__proto__" is copied as an own
  // property (plain `properties[k] = v` would mutate the prototype instead).
  const properties: Record<string, unknown> = Object.create(null);
  if (name) properties.name = name;
  if (description !== undefined) properties.description = description;
  if (folderPath.length > 0) properties.folder = folderPath.join(" / ");
  if (kmlId !== undefined) properties.kmlId = kmlId;
  for (const [k, v] of Object.entries(extended)) properties[k] = v;

  const geometries = collectGeometries(el, label, warnings);
  let geometry: GeoJSONGeometry | null;
  if (geometries.length === 0) {
    geometry = null;
    warnings.push(`${label}: no supported geometry; feature retained with null geometry`);
  } else {
    geometry = buildGeometry(geometries);
  }

  const feature: GeoJSONFeature = {
    type: "Feature",
    geometry,
    properties: Object.keys(properties).length > 0 ? properties : null,
  };
  if (kmlId !== undefined) feature.id = kmlId;
  return feature;
}

/** Walk container elements (Document/Folder) collecting Placemarks in order. */
function walkContainer(
  node: Element,
  folderPath: string[],
  features: GeoJSONFeature[],
  warnings: string[],
): void {
  for (const child of elementChildren(node)) {
    const tag = localNameOf(child);
    if (tag === "Folder") {
      const fname = childText(child, "name");
      walkContainer(child, fname ? [...folderPath, fname] : folderPath, features, warnings);
    } else if (tag === "Document" || tag === "kml") {
      walkContainer(child, folderPath, features, warnings);
    } else if (tag === "Placemark") {
      features.push(parsePlacemark(child, folderPath, warnings));
    }
  }
}

/** All elements (self + descendants) whose local tag name equals `tag`. */
function findElementsByLocalName(root: Element, tag: string): Element[] {
  const out: Element[] = [];
  if (localNameOf(root) === tag) out.push(root);
  for (const child of elementChildren(root)) out.push(...findElementsByLocalName(child, tag));
  return out;
}

/**
 * Parse KML text into a normalized FeatureCollection. Throws a useful error on
 * XML parse failure or malformed selectable geometry; returns warnings for
 * unsupported geometry and placemarks without supported geometry.
 *
 * XML parse errors surface either as a browser `<parsererror>` document or as
 * a thrown error (e.g. xmldom); both are converted to a useful error.
 */
export function parseKML(xml: string): ParsedImport {
  let doc: Document;
  try {
    doc = new DOMParser().parseFromString(xml, "text/xml");
  } catch (e) {
    throw new Error(`KML XML parse error: ${(e as Error).message}`);
  }
  const root = doc.documentElement;
  if (!root) {
    throw new Error("KML: empty document");
  }
  const parseErrors = findElementsByLocalName(root, "parsererror");
  if (parseErrors.length > 0) {
    const message = parseErrors[0].textContent?.trim() || "unknown XML parse error";
    throw new Error(`KML XML parse error: ${message}`);
  }
  const features: GeoJSONFeature[] = [];
  const warnings: string[] = [];
  walkContainer(root, [], features, warnings);
  return { features, warnings };
}