/**
 * Derived KML 2.2 export for the route editor.
 *
 * Converts a derived GeoJSON FeatureCollection (from export-geojson.ts) into a
 * narrow, deterministic KML document using DOM APIs + XMLSerializer — never
 * string-concatenated unescaped XML. Three folders group the features:
 * `Sections` (LineString/MultiLineString section routes), `POIs` (endpoint POI
 * and anchor Points), and `QA Diagnostics` (visualization-only gap and
 * POI-offset LineStrings). Only Point, LineString and MultiLineString (as
 * MultiGeometry) geometries are emitted, with `lon,lat,0` coordinates.
 * ExtendedData carries scalar properties verbatim and arrays/objects as compact
 * JSON. KML is derived output, not a canonical format.
 *
 * Production uses the browser DOM globals (`document`, `XMLSerializer`); tests
 * install the dev-only `@xmldom/xmldom` implementations on `globalThis`.
 */

import type {
  GeoJSONFeature,
  GeoJSONFeatureCollection,
  GeoJSONGeometry,
  Position,
} from "./model";

const KML_NS = "http://www.opengis.net/kml/2.2";

/** The KML document factory; browser `document` by default, injectable for tests. */
function currentDocument(): Document {
  const doc = (globalThis as typeof globalThis & { document?: Document }).document;
  if (!doc || typeof doc.implementation?.createDocument !== "function") {
    throw new Error("KML export requires a DOM Document implementation");
  }
  return doc;
}

/** The XMLSerializer factory; browser global by default, injectable for tests. */
function currentSerializer(): { serializeToString(node: Node): string } {
  const Ctor = (globalThis as typeof globalThis & { XMLSerializer?: typeof XMLSerializer }).XMLSerializer;
  if (typeof Ctor !== "function") {
    throw new Error("KML export requires an XMLSerializer");
  }
  return new Ctor();
}

function el(doc: Document, tag: string): Element {
  return doc.createElementNS(KML_NS, tag);
}

function textEl(doc: Document, tag: string, text: string): Element {
  const node = el(doc, tag);
  node.appendChild(doc.createTextNode(text));
  return node;
}

function coordinatesEl(doc: Document, coords: Position[]): Element {
  const node = el(doc, "coordinates");
  node.appendChild(doc.createTextNode(coords.map(([lon, lat]) => `${lon},${lat},0`).join(" ")));
  return node;
}

function pointEl(doc: Document, coords: Position): Element {
  const node = el(doc, "Point");
  node.appendChild(coordinatesEl(doc, [coords]));
  return node;
}

function lineEl(doc: Document, coords: Position[]): Element {
  const node = el(doc, "LineString");
  node.appendChild(coordinatesEl(doc, coords));
  return node;
}

/** Point/LineString/MultiLineString (as MultiGeometry) only. */
function geometryEl(doc: Document, geometry: GeoJSONGeometry | null): Element | null {
  if (!geometry) return null;
  switch (geometry.type) {
    case "Point":
      return pointEl(doc, geometry.coordinates);
    case "LineString":
      return lineEl(doc, geometry.coordinates);
    case "MultiLineString": {
      const node = el(doc, "MultiGeometry");
      for (const part of geometry.coordinates) node.appendChild(lineEl(doc, part));
      return node;
    }
    default:
      return null;
  }
}

/**
 * ExtendedData: scalar properties as `<Data><value>`, arrays/objects as
 * compact JSON. Keys are sorted for deterministic output.
 */
function extendedDataEl(doc: Document, properties: Record<string, unknown> | null): Element | null {
  if (!properties) return null;
  const keys = Object.keys(properties).sort();
  if (keys.length === 0) return null;
  const node = el(doc, "ExtendedData");
  for (const key of keys) {
    const value = properties[key];
    const data = el(doc, "Data");
    data.setAttribute("name", key);
    const valueEl = el(doc, "value");
    const text =
      typeof value === "string" || typeof value === "number" || typeof value === "boolean"
        ? String(value)
        : JSON.stringify(value);
    valueEl.appendChild(doc.createTextNode(text));
    data.appendChild(valueEl);
    node.appendChild(data);
  }
  return node;
}

function placemarkEl(doc: Document, feature: GeoJSONFeature): Element {
  const pm = el(doc, "Placemark");
  const id = feature.id === undefined || feature.id === null ? "" : String(feature.id);
  pm.appendChild(textEl(doc, "name", id));
  const geom = geometryEl(doc, feature.geometry);
  if (geom) pm.appendChild(geom);
  const ext = extendedDataEl(doc, feature.properties);
  if (ext) pm.appendChild(ext);
  return pm;
}

/** Which KML folder a feature belongs to, from its stable `type` property. */
function folderFor(feature: GeoJSONFeature): "Sections" | "POIs" | "QA Diagnostics" | null {
  const type = feature.properties?.type;
  if (type === "section") return "Sections";
  if (type === "poi" || type === "anchor") return "POIs";
  if (type === "gap" || type === "poi_offset") return "QA Diagnostics";
  return null;
}

/**
 * Convert a derived GeoJSON FeatureCollection into a KML 2.2 XML string.
 * Deterministic for identical input: folders and placemarks follow input
 * order, ExtendedData keys are sorted, and the document is namespace-clean.
 */
export function exportProjectToKML(fc: GeoJSONFeatureCollection): string {
  const sourceDoc = currentDocument();
  const doc = sourceDoc.implementation.createDocument(KML_NS, "kml", null);
  const kml = doc.documentElement;
  const documentEl = el(doc, "Document");
  kml.appendChild(documentEl);
  documentEl.appendChild(textEl(doc, "name", "ohenro route export"));

  const folderNames = ["Sections", "POIs", "QA Diagnostics"] as const;
  const folders = new Map<string, GeoJSONFeature[]>(
    folderNames.map((name) => [name, []]),
  );
  for (const feature of fc.features) {
    const folder = folderFor(feature);
    if (folder) folders.get(folder)?.push(feature);
  }

  for (const name of folderNames) {
    const features = folders.get(name) ?? [];
    const folder = el(doc, "Folder");
    folder.appendChild(textEl(doc, "name", name));
    for (const feature of features) folder.appendChild(placemarkEl(doc, feature));
    documentEl.appendChild(folder);
  }

  return currentSerializer().serializeToString(doc);
}