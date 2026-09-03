import { describe, expect, it } from "vitest";
import {
  convertArukihenro,
  type ArukihenroData,
  type ArukihenroRouteInput,
} from "./arukihenro";

function route(overrides: Partial<ArukihenroRouteInput> = {}): ArukihenroRouteInput {
  return {
    id: "r1",
    region: "tokushima",
    title: "01番～02番",
    url: null,
    from_temple: 1,
    to_temple: 2,
    temple_range: [1, 2],
    maps: [],
    ...overrides,
  };
}

function makeData(routes: ArukihenroRouteInput[]): ArukihenroData {
  return { schema_version: 1, routes };
}

describe("convertArukihenro", () => {
  it("flattens lines and points with full properties and deterministic ids", () => {
    const data = makeData([
      route({
        maps: [
          {
            map_id: "MAP_A",
            map_name: "A map",
            map_description: "desc",
            from_temple: 1,
            to_temple: 2,
            temple_range: [1, 2],
            lines: [
              {
                name: "line name",
                folder: "folder",
                source: "google_directions",
                coordinates: [
                  [134, 34],
                  [134.1, 34.1],
                ],
              },
            ],
            points: [
              {
                name: "point name",
                folder: "folder",
                category: "waymarker",
                coordinates: [134, 34],
                photos: ["http://a", "http://b"],
              },
            ],
          },
        ],
      }),
    ]);

    const { featureCollection, groups } = convertArukihenro(data);
    expect(featureCollection.features).toHaveLength(2);

    const line = featureCollection.features[0];
    expect(line.id).toBe("r1:MAP_A:M0:L0");
    expect(line.geometry.type).toBe("LineString");
    expect(line.properties).toMatchObject({
      route_id: "r1",
      route_title: "01番～02番",
      region: "tokushima",
      map_id: "MAP_A",
      map_name: "A map",
      map_description: "desc",
      kind: "line",
      name: "line name",
      folder: "folder",
      line_source: "google_directions",
    });

    const point = featureCollection.features[1];
    expect(point.id).toBe("r1:MAP_A:M0:P0");
    expect(point.geometry.type).toBe("Point");
    expect(point.properties).toMatchObject({
      kind: "point",
      name: "point name",
      category: "waymarker",
      photo_count: 2,
    });
    expect(point.properties.photos).toBe("http://a\nhttp://b");

    expect(groups).toHaveLength(1);
    expect(groups[0].routes[0]).toMatchObject({ routeId: "r1", hasGeometry: true });
  });

  it("handles multiple maps in one route", () => {
    const data = makeData([
      route({
        maps: [
          {
            map_id: "M0",
            map_name: null,
            map_description: null,
            from_temple: null,
            to_temple: null,
            temple_range: null,
            lines: [
              {
                name: null,
                folder: null,
                source: null,
                coordinates: [
                  [134, 34],
                  [134.1, 34.1],
                ],
              },
            ],
            points: [],
          },
          {
            map_id: "M1",
            map_name: null,
            map_description: null,
            from_temple: null,
            to_temple: null,
            temple_range: null,
            lines: [],
            points: [
              {
                name: null,
                folder: null,
                category: null,
                coordinates: [134, 34],
                photos: null,
              },
            ],
          },
        ],
      }),
    ]);

    const { featureCollection } = convertArukihenro(data);
    expect(featureCollection.features.map((f) => f.id)).toEqual([
      "r1:M0:M0:L0",
      "r1:M1:M1:P0",
    ]);
  });

  it("does not collide ids when two routes share a map_id", () => {
    const data = makeData([
      route({
        id: "rA",
        maps: [
          {
            map_id: "SHARED",
            map_name: null,
            map_description: null,
            from_temple: null,
            to_temple: null,
            temple_range: null,
            lines: [
              {
                name: null,
                folder: null,
                source: null,
                coordinates: [
                  [134, 34],
                  [134.1, 34.1],
                ],
              },
            ],
            points: [],
          },
        ],
      }),
      route({
        id: "rB",
        maps: [
          {
            map_id: "SHARED",
            map_name: null,
            map_description: null,
            from_temple: null,
            to_temple: null,
            temple_range: null,
            lines: [
              {
                name: null,
                folder: null,
                source: null,
                coordinates: [
                  [134, 34],
                  [134.1, 34.1],
                ],
              },
            ],
            points: [],
          },
        ],
      }),
    ]);

    const { featureCollection } = convertArukihenro(data);
    const ids = featureCollection.features.map((f) => f.id);
    expect(new Set(ids).size).toBe(ids.length);
    expect(ids).toEqual(["rA:SHARED:M0:L0", "rB:SHARED:M0:L0"]);
  });

  it("still emits a group for a route with maps=[] and hasGeometry=false", () => {
    const data = makeData([route({ maps: [] })]);
    const { featureCollection, groups } = convertArukihenro(data);
    expect(featureCollection.features).toHaveLength(0);
    expect(groups).toHaveLength(1);
    expect(groups[0].routes[0]).toMatchObject({ routeId: "r1", hasGeometry: false });
  });

  it("groups routes by region preserving source order", () => {
    const data = makeData([
      route({ id: "a", region: "tokushima" }),
      route({ id: "b", region: "ehime" }),
      route({ id: "c", region: "tokushima" }),
    ]);
    const { groups } = convertArukihenro(data);
    expect(groups.map((g) => g.region)).toEqual(["tokushima", "ehime"]);
    expect(groups[0].routes.map((r) => r.routeId)).toEqual(["a", "c"]);
    expect(groups[1].routes.map((r) => r.routeId)).toEqual(["b"]);
  });

  it("throws on wrong schema_version", () => {
    expect(() => convertArukihenro({ schema_version: 2, routes: [] })).toThrow(
      /schema_version/,
    );
  });

  it("throws on non-array routes", () => {
    expect(() =>
      convertArukihenro({ schema_version: 1, routes: "nope" as unknown as ArukihenroRouteInput[] }),
    ).toThrow(/not an array/);
  });
});
