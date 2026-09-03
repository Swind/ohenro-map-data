import { describe, expect, it } from "vitest";
import { parseGeoJSON } from "./import-geojson";

describe("parseGeoJSON root handling", () => {
  it("accepts a FeatureCollection root", () => {
    const { features, warnings } = parseGeoJSON(
      JSON.stringify({
        type: "FeatureCollection",
        features: [{ type: "Feature", geometry: { type: "Point", coordinates: [134, 33] }, properties: {} }],
      }),
    );
    expect(features).toHaveLength(1);
    expect(warnings).toEqual([]);
  });

  it("accepts a single Feature root", () => {
    const { features } = parseGeoJSON(
      JSON.stringify({ type: "Feature", geometry: { type: "Point", coordinates: [134, 33] }, properties: null }),
    );
    expect(features).toHaveLength(1);
    expect(features[0].geometry).toEqual({ type: "Point", coordinates: [134, 33] });
  });

  it("rejects other root types", () => {
    expect(() => parseGeoJSON(JSON.stringify({ type: "GeometryCollection", geometries: [] }))).toThrow(
      /must be a Feature or FeatureCollection/,
    );
    expect(() => parseGeoJSON(JSON.stringify({ foo: 1 }))).toThrow(/must be a Feature or FeatureCollection/);
  });

  it("throws a useful error on invalid JSON", () => {
    expect(() => parseGeoJSON("{ not json")).toThrow(/Invalid GeoJSON JSON/);
  });
});

describe("parseGeoJSON properties trust boundary", () => {
  it("accepts object and null properties", () => {
    expect(
      parseGeoJSON(JSON.stringify({ type: "Feature", geometry: null, properties: { a: 1 } })).features[0].properties,
    ).toEqual({ a: 1 });
    expect(
      parseGeoJSON(JSON.stringify({ type: "Feature", geometry: null, properties: null })).features[0].properties,
    ).toBeNull();
  });

  it("rejects non-object properties (trust boundary)", () => {
    expect(() =>
      parseGeoJSON(JSON.stringify({ type: "Feature", geometry: null, properties: [1, 2] })),
    ).toThrow(/properties must be an object or null/);
    expect(() =>
      parseGeoJSON(JSON.stringify({ type: "Feature", geometry: null, properties: "nope" })),
    ).toThrow(/properties must be an object or null/);
  });
});

describe("parseGeoJSON null geometry", () => {
  it("retains null geometry with a warning", () => {
    const { features, warnings } = parseGeoJSON(
      JSON.stringify({ type: "Feature", geometry: null, properties: {} }),
    );
    expect(features[0].geometry).toBeNull();
    expect(warnings).toHaveLength(1);
    expect(warnings[0]).toMatch(/null geometry/);
  });
});

describe("parseGeoJSON coordinates", () => {
  it("strips altitude to [lon, lat]", () => {
    const { features } = parseGeoJSON(
      JSON.stringify({ type: "Feature", geometry: { type: "Point", coordinates: [134, 33, 250] }, properties: {} }),
    );
    expect(features[0].geometry).toEqual({ type: "Point", coordinates: [134, 33] });
  });

  it("rejects out-of-bounds and non-numeric coordinates", () => {
    expect(() => parseGeoJSON(JSON.stringify({ type: "Feature", geometry: { type: "Point", coordinates: [181, 0] }, properties: {} }))).toThrow(/out of bounds/);
    // NaN/Infinity cannot be serialized by JSON; a non-number (string) is the realistic trust violation.
    expect(() => parseGeoJSON(JSON.stringify({ type: "Feature", geometry: { type: "Point", coordinates: [134, "x"] }, properties: {} }))).toThrow(/must be numbers/);
    expect(() => parseGeoJSON(JSON.stringify({ type: "Feature", geometry: { type: "Point", coordinates: [134] }, properties: {} }))).toThrow(/position must be \[lon, lat\]/);
  });

  it("requires Point cardinality (exactly one position)", () => {
    expect(() =>
      parseGeoJSON(JSON.stringify({ type: "Feature", geometry: { type: "Point", coordinates: [[134, 33]] }, properties: {} })),
    ).toThrow(/position must be \[lon, lat\]/);
  });

  it("requires LineString to have at least 2 coordinates", () => {
    expect(() =>
      parseGeoJSON(JSON.stringify({ type: "Feature", geometry: { type: "LineString", coordinates: [[134, 33]] }, properties: {} })),
    ).toThrow(/at least 2 positions/);
  });
});

describe("parseGeoJSON recursive geometry", () => {
  it("parses Point/MultiPoint/LineString/MultiLineString", () => {
    const { features } = parseGeoJSON(
      JSON.stringify({
        type: "FeatureCollection",
        features: [
          { type: "Feature", geometry: { type: "MultiPoint", coordinates: [[134, 33], [134, 34]] }, properties: {} },
          { type: "Feature", geometry: { type: "MultiLineString", coordinates: [[[134, 33], [134, 34]], [[135, 33], [135, 34]]] }, properties: {} },
        ],
      }),
    );
    expect(features[0].geometry).toEqual({ type: "MultiPoint", coordinates: [[134, 33], [134, 34]] });
    expect(features[1].geometry).toEqual({
      type: "MultiLineString",
      coordinates: [[[134, 33], [134, 34]], [[135, 33], [135, 34]]],
    });
  });

  it("parses Polygon rings and requires >= 4 ring coordinates", () => {
    const ok = parseGeoJSON(
      JSON.stringify({
        type: "Feature",
        geometry: {
          type: "Polygon",
          coordinates: [
            [[134, 33], [134, 34], [135, 34], [134, 33]],
            [[134.2, 33.2], [134.2, 33.3], [134.3, 33.3], [134.2, 33.2]],
          ],
        },
        properties: {},
      }),
    );
    expect((ok.features[0].geometry as { type: "Polygon" }).type).toBe("Polygon");
    expect(() =>
      parseGeoJSON(
        JSON.stringify({
          type: "Feature",
          geometry: { type: "Polygon", coordinates: [[[134, 33], [134, 34], [135, 34]]] },
          properties: {},
        }),
      ),
    ).toThrow(/at least 4 positions/);
  });

  it("parses MultiPolygon and GeometryCollection recursively", () => {
    const { features } = parseGeoJSON(
      JSON.stringify({
        type: "Feature",
        geometry: {
          type: "GeometryCollection",
          geometries: [
            { type: "Point", coordinates: [134, 33] },
            {
              type: "MultiPolygon",
              coordinates: [[[[134, 33], [134, 34], [135, 34], [134, 33]]]],
            },
          ],
        },
        properties: {},
      }),
    );
    const geom = features[0].geometry as { type: "GeometryCollection"; geometries: unknown[] };
    expect(geom.type).toBe("GeometryCollection");
    expect(geom.geometries).toHaveLength(2);
    expect(geom.geometries[1]).toEqual({
      type: "MultiPolygon",
      coordinates: [[[[134, 33], [134, 34], [135, 34], [134, 33]]]],
    });
  });

  it("rejects unsupported geometry types", () => {
    expect(() =>
      parseGeoJSON(JSON.stringify({ type: "Feature", geometry: { type: "Circle", coordinates: [134, 33] }, properties: {} })),
    ).toThrow(/unsupported geometry type "Circle"/);
  });
});