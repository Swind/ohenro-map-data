import { describe, expect, it } from "vitest";
import {
  buildGpx,
  fillElevationGaps,
  simplifyToBudget,
  smoothElevation,
  type GpxCoord,
} from "./gpx";

const coord = (lon: number, lat: number, ele: number | null = null): GpxCoord => ({
  lon,
  lat,
  ele,
});

function countMatches(haystack: string, needle: string): number {
  return haystack.split(needle).length - 1;
}

describe("buildGpx", () => {
  it("emits a single track with one seg, no timestamps, and wpt order", () => {
    const gpx = buildGpx(
      [
        { lon: 133.0, lat: 33.0, ele: 100 },
        { lon: 133.0001, lat: 33.0001, ele: 100.5 },
        { lon: 133.0002, lat: 33.0, ele: 101 },
      ],
      [
        { lon: 133.0, lat: 33.0, name: "A" },
        { lon: 133.0002, lat: 33.0, name: "B" },
      ],
      { name: "Test plan", desc: "a & b <plan> \"q\"", smoothElevation: false },
    );
    expect(countMatches(gpx, "<trk>")).toBe(1);
    expect(countMatches(gpx, "<trkseg>")).toBe(1);
    expect(countMatches(gpx, "<wpt ")).toBe(2);
    expect(gpx).not.toContain("<time>");
    expect(gpx).toContain("<name>Test plan</name>");
    expect(gpx).toContain("a &amp; b &lt;plan&gt; &quot;q&quot;");
    expect(gpx).toContain(
      '<wpt lat="33.0000000" lon="133.0000000"><name>A</name></wpt>',
    );
    const bIndex = gpx.indexOf("<name>B</name>");
    expect(bIndex).toBeGreaterThan(gpx.indexOf("<name>A</name>"));
    expect(gpx).toContain(
      '<trkpt lat="33.0000000" lon="133.0000000"><ele>100.0</ele></trkpt>',
    );
    expect(gpx).toContain(
      '<trkpt lat="33.0001000" lon="133.0001000"><ele>100.5</ele></trkpt>',
    );
    expect(gpx).toContain(
      '<trkpt lat="33.0000000" lon="133.0002000"><ele>101.0</ele></trkpt>',
    );
    expect(gpx.endsWith("\n")).toBe(true);
  });

  it("omits metadata when no name/desc and omits ele when none present", () => {
    const gpx = buildGpx(
      [
        { lon: 133.0, lat: 33.0 },
        { lon: 133.001, lat: 33.0 },
      ],
      [],
      { smoothElevation: false },
    );
    expect(gpx).not.toContain("<metadata>");
    expect(gpx).not.toContain("<ele>");
    expect(countMatches(gpx, "<trkpt ")).toBe(2);
  });

  it("does not mutate its inputs", () => {
    const coords: GpxCoord[] = [
      coord(133.0, 33.0, 100),
      coord(133.001, 33.0, null),
      coord(133.002, 33.0, 200),
    ];
    buildGpx(coords, [], { smoothElevation: false });
    expect(coords[1].ele).toBeNull();
  });
});

describe("fillElevationGaps", () => {
  it("clamps leading/trailing gaps and interpolates interior gaps", () => {
    const out = fillElevationGaps([
      coord(0, 0, null),
      coord(0, 1, null),
      coord(0, 2, 100),
      coord(0, 3, null),
      coord(0, 4, 200),
      coord(0, 5, null),
    ]);
    expect(out[0].ele).toBe(100);
    expect(out[1].ele).toBe(100);
    expect(out[2].ele).toBe(100);
    expect(out[3].ele).toBe(150);
    expect(out[4].ele).toBe(200);
    expect(out[5].ele).toBe(200);
  });

  it("returns unchanged when nothing is null or everything is null", () => {
    const allKnown = [coord(0, 0, 1), coord(0, 1, 2)];
    expect(fillElevationGaps(allKnown)).toEqual(allKnown);
    const allNull = [coord(0, 0), coord(0, 1)];
    expect(fillElevationGaps(allNull)).toEqual(allNull);
  });
});

describe("smoothElevation", () => {
  it("averages a centered window", () => {
    const out = smoothElevation(
      [coord(0, 0, 100), coord(0, 1, 200), coord(0, 2, 100)],
      5,
    );
    for (const c of out) {
      expect(c.ele).toBeCloseTo(400 / 3, 5);
    }
  });
});

describe("simplifyToBudget", () => {
  it("keeps endpoints and order within the budget", () => {
    const pts: GpxCoord[] = [];
    for (let i = 0; i < 50; i++) pts.push(coord(i * 0.001, 0));
    const out = simplifyToBudget(pts, 8);
    expect(out.length).toBe(8);
    expect(out[0]).toEqual(pts[0]);
    expect(out[out.length - 1]).toEqual(pts[pts.length - 1]);
  });

  it("removes the least-important point first and keeps the corner", () => {
    const pts: GpxCoord[] = [
      coord(0, 0),
      coord(0.5, 0),
      coord(1, 0),
      coord(2, 1),
      coord(3, 1),
    ];
    const out = simplifyToBudget(pts, 4);
    expect(out).toEqual([pts[0], pts[2], pts[3], pts[4]]);
  });

  it("keeps the full list when under the budget", () => {
    const pts = [coord(0, 0), coord(1, 1), coord(2, 0)];
    expect(simplifyToBudget(pts, 4000)).toEqual(pts);
  });
});
