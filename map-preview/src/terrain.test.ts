import { describe, expect, it } from "vitest";
import { decodeTerrainRgb, elevationFromRgba, tileXY } from "./terrain";

describe("tileXY", () => {
  it("maps the origin to the tile centre", () => {
    const t = tileXY(0, 0, 10);
    expect(t.x).toBe(512);
    expect(t.y).toBe(512);
  });

  it("stays within the zoom tile range for Shikoku", () => {
    const t = tileXY(133.75, 33.65, 14);
    expect(t.x).toBeGreaterThanOrEqual(0);
    expect(t.x).toBeLessThan(2 ** 14);
    expect(t.y).toBeGreaterThanOrEqual(0);
    expect(t.y).toBeLessThan(2 ** 14);
  });
});

describe("decodeTerrainRgb", () => {
  it("decodes mapbox terrain-rgb elevations", () => {
    expect(decodeTerrainRgb(0, 0, 0)).toBe(-10000);
    expect(decodeTerrainRgb(1, 138, 136)).toBeCloseTo(100, 6);
    expect(decodeTerrainRgb(255, 255, 255)).toBeCloseTo(1667721.5, 6);
  });
});

describe("elevationFromRgba", () => {
  it("returns null for transparent (NODATA) pixels", () => {
    expect(elevationFromRgba(0, 0, 0, 0)).toBeNull();
    expect(elevationFromRgba(10, 20, 30, 0)).toBeNull();
  });

  it("decodes opaque pixels normally", () => {
    expect(elevationFromRgba(1, 138, 136, 255)).toBeCloseTo(100, 6);
    expect(elevationFromRgba(0, 0, 0, 255)).toBe(-10000);
  });
});