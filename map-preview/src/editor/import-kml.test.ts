import { describe, expect, it, beforeAll } from "vitest";
import { DOMParser } from "@xmldom/xmldom";
import { parseKML } from "./import-kml";

// Node has no DOM DOMParser; install @xmldom/xmldom (dev-only) for tests.
// Production code (import-kml.ts) uses the global browser DOMParser and never
// imports @xmldom/xmldom.
beforeAll(() => {
  (globalThis as Record<string, unknown>).DOMParser = DOMParser as unknown as typeof DOMParser;
});

const KML_DOC = `<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Routes</name>
    <Folder>
      <name>Leg 1</name>
      <Placemark id="pm_a">
        <name>Start</name>
        <description><![CDATA[<b>plain</b> text]]></description>
        <ExtendedData>
          <Data name="type"><value>waypoint</value></Data>
          <SchemaData schemaUrl="#x">
            <SimpleData name="temple">1</SimpleData>
          </SchemaData>
        </ExtendedData>
        <Point><coordinates>134,33,120</coordinates></Point>
      </Placemark>
      <Placemark id="pm_b">
        <name>Trail</name>
        <LineString>
          <coordinates>134,33 134,33.5,80 134,34</coordinates>
        </LineString>
      </Placemark>
    </Folder>
    <Folder>
      <name>Area</name>
      <Placemark>
        <name>Boundary</name>
        <Polygon>
          <outerBoundaryIs><LinearRing><coordinates>134,33 134,34 135,34 134,33</coordinates></LinearRing></outerBoundaryIs>
          <innerBoundaryIs><LinearRing><coordinates>134.2,33.2 134.2,33.3 134.3,33.3 134.2,33.2</coordinates></LinearRing></innerBoundaryIs>
        </Polygon>
      </Placemark>
      <Placemark>
        <name>Multi</name>
        <MultiGeometry>
          <Point><coordinates>136,34</coordinates></Point>
          <LineString><coordinates>136,34 136,34.5</coordinates></LineString>
        </MultiGeometry>
      </Placemark>
    </Folder>
  </Document>
</kml>`;

describe("parseKML basic structure", () => {
  it("parses Document/Folder/Placemark in source order with folder path", () => {
    const { features, warnings } = parseKML(KML_DOC);
    expect(features).toHaveLength(4);
    expect(warnings).toEqual([]);
    // Source order preserved.
    expect(features[0].properties?.name).toBe("Start");
    expect(features[0].properties?.folder).toBe("Leg 1");
    expect(features[2].properties?.name).toBe("Boundary");
    expect(features[2].properties?.folder).toBe("Area");
  });

  it("preserves the KML Placemark id as the feature id", () => {
    const { features } = parseKML(KML_DOC);
    expect(features[0].id).toBe("pm_a");
    expect(features[0].properties?.kmlId).toBe("pm_a");
  });

  it("reads a plain description (CDATA HTML is not injected)", () => {
    const { features } = parseKML(KML_DOC);
    expect(features[0].properties?.description).toBe("<b>plain</b> text");
  });

  it("reads ExtendedData Data and SchemaData values", () => {
    const { features } = parseKML(KML_DOC);
    expect(features[0].properties?.type).toBe("waypoint");
    expect(features[0].properties?.temple).toBe("1");
  });

  it("preserves an ExtendedData key of __proto__ as an own property", () => {
    const kml = `<?xml version="1.0"?><kml><Document>
      <Placemark><name>P</name>
        <ExtendedData>
          <Data name="__proto__"><value>payload</value></Data>
        </ExtendedData>
        <Point><coordinates>134,33</coordinates></Point>
      </Placemark>
    </Document></kml>`;
    const { features } = parseKML(kml);
    const props = features[0].properties;
    expect(props).not.toBeNull();
    // Own property named "__proto__" is preserved (not a prototype mutation).
    expect(Object.getOwnPropertyNames(props as object)).toContain("__proto__");
    expect((props as Record<string, unknown>)["__proto__"]).toBe("payload");
    // The properties object has no Object.prototype (so writing "__proto__"
    // could never pollute Object.prototype) and Object.prototype is untouched.
    expect(Object.getPrototypeOf(props)).toBeNull();
    expect(({} as Record<string, unknown>).payload).toBeUndefined();
  });

  it("strips altitude from coordinates", () => {
    const { features } = parseKML(KML_DOC);
    expect(features[0].geometry).toEqual({ type: "Point", coordinates: [134, 33] });
    expect(features[1].geometry).toEqual({
      type: "LineString",
      coordinates: [[134, 33], [134, 33.5], [134, 34]],
    });
  });

  it("parses Polygon outer + inner rings", () => {
    const { features } = parseKML(KML_DOC);
    expect(features[2].geometry).toEqual({
      type: "Polygon",
      coordinates: [
        [[134, 33], [134, 34], [135, 34], [134, 33]],
        [[134.2, 33.2], [134.2, 33.3], [134.3, 33.3], [134.2, 33.2]],
      ],
    });
  });

  it("recursively parses MultiGeometry into a GeometryCollection", () => {
    const { features } = parseKML(KML_DOC);
    expect(features[3].geometry).toEqual({
      type: "GeometryCollection",
      geometries: [
        { type: "Point", coordinates: [136, 34] },
        { type: "LineString", coordinates: [[136, 34], [136, 34.5]] },
      ],
    });
  });

  it("handles namespace-prefixed elements via localName", () => {
    const kml = `<kml:Document xmlns:kml="http://www.opengis.net/kml/2.2">
      <kml:Folder><kml:name>Prefixed</kml:name>
        <kml:Placemark><kml:name>P</kml:name>
          <kml:Point><kml:coordinates>134,33</kml:coordinates></kml:Point>
        </kml:Placemark>
      </kml:Folder>
    </kml:Document>`;
    const { features, warnings } = parseKML(kml);
    expect(warnings).toEqual([]);
    expect(features).toHaveLength(1);
    expect(features[0].properties?.name).toBe("P");
    expect(features[0].properties?.folder).toBe("Prefixed");
    expect(features[0].geometry).toEqual({ type: "Point", coordinates: [134, 33] });
  });
});

describe("parseKML warnings and failures", () => {
  it("warns on unsupported geometry and retains the feature with null geometry", () => {
    const kml = `<?xml version="1.0"?><kml><Document>
      <Placemark><name>Model</name><Model><altitudeMode>relativeToGround</altitudeMode></Model></Placemark>
      <Placemark><name>Empty</name></Placemark>
    </Document></kml>`;
    const { features, warnings } = parseKML(kml);
    expect(features).toHaveLength(2);
    expect(features[0].geometry).toBeNull();
    expect(warnings.some((w) => w.includes("unsupported KML geometry <Model>"))).toBe(true);
    expect(warnings.some((w) => w.includes("no supported geometry"))).toBe(true);
  });

  it("fails on malformed selectable geometry rather than guessing", () => {
    // LineString with a single coordinate is malformed for our model.
    const kml = `<?xml version="1.0"?><kml><Document>
      <Placemark><name>Bad</name><LineString><coordinates>134,33</coordinates></LineString></Placemark>
    </Document></kml>`;
    expect(() => parseKML(kml)).toThrow(/at least 2 coordinates/);
  });

  it("fails on malformed coordinates", () => {
    const kml = `<?xml version="1.0"?><kml><Document>
      <Placemark><name>Bad</name><Point><coordinates>not-a-coordinate</coordinates></Point></Placemark>
    </Document></kml>`;
    expect(() => parseKML(kml)).toThrow(/malformed coordinate|non-finite/);
  });

  it("fails on a Polygon without an outerBoundaryIs", () => {
    const kml = `<?xml version="1.0"?><kml><Document>
      <Placemark><name>P</name><Polygon></Polygon></Placemark>
    </Document></kml>`;
    expect(() => parseKML(kml)).toThrow(/requires an outerBoundaryIs/);
  });

  it("turns XML parser errors into useful errors", () => {
    const bad = `<kml><Document><Placemark><name>X</name></Placemark></Document>`; // unclosed <kml>
    expect(() => parseKML(bad)).toThrow(/KML XML parse error/);
  });
});