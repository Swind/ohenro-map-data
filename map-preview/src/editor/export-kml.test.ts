import { describe, expect, it, beforeAll } from "vitest";
import { DOMParser, XMLSerializer } from "@xmldom/xmldom";
import { exportProjectToKML } from "./export-kml";
import type { GeoJSONFeatureCollection } from "./model";

// Node has no browser DOM globals; install the dev-only @xmldom/xmldom
// implementations for tests. Production (export-kml.ts) uses browser globals
// and never imports @xmldom/xmldom.
beforeAll(() => {
  const seed = new DOMParser().parseFromString("<kml/>", "text/xml");
  (globalThis as Record<string, unknown>).document = seed;
  (globalThis as Record<string, unknown>).XMLSerializer = XMLSerializer;
});

const FC: GeoJSONFeatureCollection = {
  type: "FeatureCollection",
  features: [
    {
      type: "Feature",
      id: "section:A",
      geometry: { type: "LineString", coordinates: [[134, 33], [134, 34]] },
      properties: {
        section_id: "A",
        type: "section",
        status: "continuous",
        length_m: 120,
        human_selected: true,
        source_ids: ["src"],
        feature_ids: ["line"],
        note: "a<b&c\"'",
      },
    },
    {
      type: "Feature",
      id: "section:A:poi:from",
      geometry: { type: "Point", coordinates: [134, 33] },
      properties: { section_id: "A", type: "poi", role: "from_poi", source_id: "src", feature_id: "poi_start" },
    },
    {
      type: "Feature",
      id: "section:M",
      geometry: { type: "MultiLineString", coordinates: [[[134, 33], [134, 33.5]], [[134, 33.6], [134, 34]]] },
      properties: { section_id: "M", type: "section", status: "has_gaps" },
    },
    {
      type: "Feature",
      id: "section:A:gap:0",
      geometry: { type: "LineString", coordinates: [[134, 33.5], [134, 33.6]] },
      properties: { section_id: "A", type: "gap", distance_m: 3, visualization_only: true, nested: { a: [1, 2] } },
    },
  ],
};

describe("exportProjectToKML structure", () => {
  it("emits a KML 2.2 document with Sections, POIs and QA Diagnostics folders", () => {
    const xml = exportProjectToKML(FC);
    expect(xml).toContain("http://www.opengis.net/kml/2.2");
    expect(xml).toContain("<Folder><name>Sections</name>");
    expect(xml).toContain("<Folder><name>POIs</name>");
    expect(xml).toContain("<Folder><name>QA Diagnostics</name>");
  });

  it("emits lon,lat,0 coordinates", () => {
    const xml = exportProjectToKML(FC);
    expect(xml).toContain("<coordinates>134,33,0 134,34,0</coordinates>");
  });

  it("emits a MultiLineString as MultiGeometry with one LineString per part", () => {
    const xml = exportProjectToKML(FC);
    expect(xml).toContain("<MultiGeometry><LineString>");
  });
});

describe("exportProjectToKML escaping and ExtendedData", () => {
  it("escapes XML-special characters in ExtendedData values", () => {
    const xml = exportProjectToKML(FC);
    // < and & are escaped; quotes are legal in XML text nodes and left as-is.
    expect(xml).toContain("a&lt;b&amp;c");
    expect(xml).not.toContain("a<b&c");
  });

  it("emits scalar properties as Data values and arrays/objects as compact JSON", () => {
    const xml = exportProjectToKML(FC);
    expect(xml).toContain("<Data name=\"status\"><value>continuous</value></Data>");
    expect(xml).toContain("<Data name=\"human_selected\"><value>true</value></Data>");
    expect(xml).toContain("<Data name=\"source_ids\"><value>[\"src\"]</value></Data>");
    expect(xml).toContain("<Data name=\"nested\"><value>{\"a\":[1,2]}</value></Data>");
  });
});

describe("exportProjectToKML determinism", () => {
  it("produces identical output for identical input", () => {
    expect(exportProjectToKML(FC)).toBe(exportProjectToKML(FC));
  });
});