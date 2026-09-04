import { describe, expect, it } from "vitest";
import { buildElevationProfile } from "./profile";

const R = 6371008.8;
const COS_LAT0 = Math.cos((33.65 * Math.PI) / 180);

function expectedMetres(dLon: number, dLat: number): number {
  const rad = Math.PI / 180;
  return Math.hypot(R * COS_LAT0 * dLon * rad, R * dLat * rad);
}

describe("buildElevationProfile", () => {
  it("sums cumulative distance and reports min/max", () => {
    const coords = [
      [133.0, 33.0, 100],
      [133.001, 33.0, 150],
      [133.002, 33.0, 120],
    ] as number[][];
    const profile = buildElevationProfile(coords);
    expect(profile).not.toBeNull();
    const segment = expectedMetres(0.001, 0);
    expect(profile!.totalM).toBeCloseTo(2 * segment, 6);
    expect(profile!.points).toHaveLength(3);
    expect(profile!.points[1].d).toBeCloseTo(segment, 6);
    expect(profile!.minM).toBe(100);
    expect(profile!.maxM).toBe(150);
  });

  it("skips vertices without elevation", () => {
    const coords = [
      [133.0, 33.0, 100],
      [133.001, 33.0], // no elevation -> skipped, still bridges distance
      [133.002, 33.0, 120],
    ] as number[][];
    const profile = buildElevationProfile(coords);
    expect(profile).not.toBeNull();
    expect(profile!.points).toHaveLength(2);
    expect(profile!.points[1].d).toBeCloseTo(expectedMetres(0.002, 0), 6);
  });

  it("returns null with fewer than two elevation points", () => {
    expect(buildElevationProfile([[133.0, 33.0, 100]])).toBeNull();
    expect(
      buildElevationProfile([
        [133.0, 33.0],
        [133.001, 33.0],
      ] as number[][]),
    ).toBeNull();
  });
});