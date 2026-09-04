import { describe, expect, it } from "vitest";
import { decodeTerrainRgb, tileXY } from "./terrain";

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