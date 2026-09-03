import { describe, expect, it } from "vitest";
import {
  convertOhenro88,
  OHENRO88_GROUP_DEFS,
  type Ohenro88FeatureCollection,
} from "./ohenro88";

function line(routeId: string, name: string, routeType: string, coords: number[][] = [[134, 34], [134.1, 34.1]]): {
  type: "Feature";
  geometry: { type: "LineString"; coordinates: number[][] };
  properties: Record<string, string | number | boolean | null>;
} {
  return {
    type: "Feature",
    geometry: { type: "LineString", coordinates: coords },
    properties: { kind: "line", route_id: routeId, name, route_type: routeType },
  };
}

function point(routeId: string, name: string): {
  type: "Feature";
  geometry: { type: "Point"; coordinates: number[] };
  properties: Record<string, string | number | boolean | null>;
} {
  return {
    type: "Feature",
    geometry: { type: "Point", coordinates: [134, 34] },
    properties: { kind: "point", route_id: routeId, name, temple_number: 1, bekkaku: false },
  };
}

function makeData(features: Ohenro88FeatureCollection["features"]): Ohenro88FeatureCollection {
  return { type: "FeatureCollection", features };
}

describe("convertOhenro88", () => {
  it("groups line features by route_type following the fixed defs", () => {
    const data = makeData([
      line("OH88_1_2", "Walking (1-2)", "main"),
      line("OH88_5_6_skip", "Walking (5-6) skip", "skip"),
      line("OH88_5_B1_bekkaku", "Walking bekkaku (5-B1)", "bekkaku"),
      line("OH88_5_B1_bekkaku_extra", "Walking bekkaku extra (5-B1)", "bekkaku_extra"),
      line("OH88_B1_extra", "Walking extra (B1)", "extra"),
      point("OH88_T1", "No.1 Ryozenji"),
    ]);

    const { groups } = convertOhenro88(data);
    expect(groups.map((g) => g.routeType)).toEqual(OHENRO88_GROUP_DEFS.map((d) => d.routeType));
    expect(groups.map((g) => g.routes.length)).toEqual([1, 1, 1, 1, 1]);
    expect(groups[0].routes[0]).toMatchObject({
      routeId: "OH88_1_2",
      name: "Walking (1-2)",
      routeType: "main",
      hasGeometry: true,
    });
  });

  it("ignores point features when building route groups", () => {
    const data = makeData([
      point("OH88_T1", "No.1 Ryozenji"),
      line("OH88_2_3", "Walking (2-3)", "main"),
    ]);
    const { groups } = convertOhenro88(data);
    const total = groups.reduce((n, g) => n + g.routes.length, 0);
    expect(total).toBe(1);
  });

  it("collects unknown route types into an 'other' group", () => {
    const data = makeData([line("OH88_X", "Walking weird", "weird")]);
    const { groups } = convertOhenro88(data);
    const other = groups.find((g) => g.routeType === "other");
    expect(other?.routes).toHaveLength(1);
    expect(other?.routes[0].routeId).toBe("OH88_X");
  });

  it("skips features without a route_id", () => {
    const data = makeData([
      { type: "Feature", geometry: { type: "LineString", coordinates: [[134, 34], [134.1, 34.1]] }, properties: { kind: "line", name: "no id", route_type: "main" } },
    ]);
    const { groups } = convertOhenro88(data);
    const total = groups.reduce((n, g) => n + g.routes.length, 0);
    expect(total).toBe(0);
  });

  it("throws on non-array features", () => {
    expect(() =>
      convertOhenro88({ type: "FeatureCollection", features: "nope" as unknown as Ohenro88FeatureCollection["features"] }),
    ).toThrow(/not an array/);
  });
});