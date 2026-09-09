import { describe, expect, it } from "vitest";
import { convertHenrohub, type HenrohubFeatureCollection } from "./henrohub";

function line(id: string, role: string, routeClass: string): HenrohubFeatureCollection["features"][number] {
  return {
    type: "Feature",
    id,
    geometry: { type: "LineString", coordinates: [[133.0, 33.0], [133.001, 33.0]] },
    properties: { kind: "line", route_id: id, route_role: role, route_class: routeClass, name: id },
  };
}

describe("convertHenrohub", () => {
  it("groups by route_role in fixed order and keeps route order", () => {
    const data: HenrohubFeatureCollection = {
      type: "FeatureCollection",
      features: [
        line("a1", "unique_alternative", "black"),
        line("m1", "canonical_shikoku88", "red"),
        line("m2", "canonical_shikoku88", "green"),
        line("f1", "continuity_fallback", "black"),
        line("c1", "transition_connector", "blue"),
      ],
    };
    const { groups } = convertHenrohub(data);
    expect(groups.map((g) => g.label)).toEqual([
      "main (canonical 88)",
      "alternative",
      "connector",
      "fallback",
    ]);
    expect(groups[0].routes.map((r) => r.routeId)).toEqual(["m1", "m2"]);
    expect(groups[1].routes.map((r) => r.routeId)).toEqual(["a1"]);
    expect(groups[2].routes.map((r) => r.routeId)).toEqual(["c1"]);
    expect(groups[3].routes.map((r) => r.routeId)).toEqual(["f1"]);
  });

  it("collects unknown roles into an other group", () => {
    const data: HenrohubFeatureCollection = {
      type: "FeatureCollection",
      features: [line("x1", "mystery_role", "red")],
    };
    const { groups } = convertHenrohub(data);
    const other = groups.find((g) => g.label === "other");
    expect(other?.routes.map((r) => r.routeId)).toEqual(["x1"]);
  });

  it("skips non-line features", () => {
    const data: HenrohubFeatureCollection = {
      type: "FeatureCollection",
      features: [
        line("m1", "canonical_shikoku88", "red"),
        {
          type: "Feature",
          id: "p1",
          geometry: { type: "LineString", coordinates: [[133.0, 33.0], [133.001, 33.0]] },
          properties: { kind: "point", route_id: "p1" },
        },
      ],
    };
    const { groups } = convertHenrohub(data);
    const total = groups.reduce((n, g) => n + g.routes.length, 0);
    expect(total).toBe(1);
  });
});