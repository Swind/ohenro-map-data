import { describe, expect, it } from "vitest";
import {
  convertOhenroNoAkari,
  OHENRO_NO_AKARI_ATTRIBUTION,
  type OhenroNoAkariFeatureCollection,
} from "./ohenro-no-akari";

function line(coords: number[][] = [[134, 34], [134.1, 34.1]]): {
  type: "Feature";
  geometry: { type: "LineString"; coordinates: number[][] };
  properties: Record<string, string | number | boolean | null>;
} {
  return {
    type: "Feature",
    geometry: { type: "LineString", coordinates: coords },
    properties: { _color: "#0000ff", _opacity: 1, _weight: 3, id: "henro-no-akari-0000" },
  };
}

function makeData(features: OhenroNoAkariFeatureCollection["features"]): OhenroNoAkariFeatureCollection {
  return { type: "FeatureCollection", features };
}

describe("convertOhenroNoAkari", () => {
  it("returns the FeatureCollection unchanged for a single continuous route", () => {
    const data = makeData([line(), line([[134.1, 34.1], [134.2, 34.2]])]);
    const out = convertOhenroNoAkari(data);
    expect(out).toBe(data);
    expect(out.features).toHaveLength(2);
  });

  it("preserves the source styling props", () => {
    const data = makeData([line()]);
    const out = convertOhenroNoAkari(data);
    expect(out.features[0].properties._color).toBe("#0000ff");
    expect(out.features[0].properties.id).toBe("henro-no-akari-0000");
  });

  it("throws on non-array features", () => {
    expect(() =>
      convertOhenroNoAkari({ type: "FeatureCollection", features: "nope" as unknown as OhenroNoAkariFeatureCollection["features"] }),
    ).toThrow(/not an array/);
  });
});

describe("OHENRO_NO_AKARI_ATTRIBUTION", () => {
  it("points at the app web bundle", () => {
    expect(OHENRO_NO_AKARI_ATTRIBUTION).toContain("https://app.henro-no-akari.com");
  });
});