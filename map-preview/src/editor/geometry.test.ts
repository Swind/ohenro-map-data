import { describe, expect, it } from "vitest";
import {
  R,
  dedupeConsecutive,
  distanceM,
  enumerateLineParts,
  enumeratePointParts,
  extractLineRange,
  isValidPosition,
  lineLengthM,
  nearestPointOnLine,
  projectPoint,
  unprojectPoint,
} from "./geometry";
import type { GeoJSONGeometry, Position } from "./model";

const DEG = Math.PI / 180;

/** A straight vertical (meridian) line part for deterministic tests. */
const V: Position[] = [
  [134, 33],
  [134, 33.5],
  [134, 34],
  [134, 34.5],
];

describe("coordinate bounds", () => {
  it("accepts finite in-range [lon, lat] pairs", () => {
    expect(isValidPosition([134, 33.65])).toBe(true);
    expect(isValidPosition([-180, -90])).toBe(true);
    expect(isValidPosition([180, 90])).toBe(true);
  });

  it("rejects out-of-range, non-finite, and wrong shapes", () => {
    expect(isValidPosition([181, 0])).toBe(false);
    expect(isValidPosition([0, 91])).toBe(false);
    expect(isValidPosition([0, -91])).toBe(false);
    expect(isValidPosition([NaN, 0])).toBe(false);
    expect(isValidPosition([134])).toBe(false);
    expect(isValidPosition([134, 33, 5])).toBe(false);
    expect(isValidPosition("nope")).toBe(false);
  });
});

describe("projection", () => {
  it("matches the Python constants round-trip", () => {
    const p = [134.5, 33.9] as Position;
    const [x, y] = projectPoint(p);
    const back = unprojectPoint([x, y]);
    expect(back[0]).toBeCloseTo(p[0], 12);
    expect(back[1]).toBeCloseTo(p[1], 12);
  });

  it("measures one degree of latitude as R * radians(1)", () => {
    const [, y0] = projectPoint([134, 33.65]);
    const [, y1] = projectPoint([134, 34.65]);
    expect(y1 - y0).toBeCloseTo(R * DEG, 6);
  });
});

describe("distances", () => {
  it("distanceM equals euclidean distance in projected space", () => {
    const a: Position = [134, 33];
    const b: Position = [134, 34];
    const [ax, ay] = projectPoint(a);
    const [bx, by] = projectPoint(b);
    const expected = Math.hypot(bx - ax, by - ay);
    expect(distanceM(a, b)).toBeCloseTo(expected, 9);
  });

  it("lineLengthM sums consecutive distances", () => {
    const full = lineLengthM(V);
    const per = R * DEG * 0.5;
    expect(full).toBeCloseTo(per * 3, 9);
    // Flat / empty / single-point lines have zero length.
    expect(lineLengthM([])).toBe(0);
    expect(lineLengthM([[134, 33]])).toBe(0);
    expect(lineLengthM([[134, 33], [134, 33]])).toBe(0);
  });
});

describe("nearest projection", () => {
  it("returns segment/fraction/coordinate/distance for an interior point", () => {
    const hit = nearestPointOnLine(V, [134, 33.25]);
    expect(hit.segmentIndex).toBe(0);
    expect(hit.fraction).toBeCloseTo(0.5, 9);
    expect(hit.coordinate[0]).toBeCloseTo(134, 9);
    expect(hit.coordinate[1]).toBeCloseTo(33.25, 9);
    expect(hit.distanceM).toBeCloseTo(0, 9);
  });

  it("snaps to the closest segment across the whole part", () => {
    // Nearest to the middle of the third segment ([134,34]..[134,34.5]).
    const hit = nearestPointOnLine(V, [134.0005, 34.25]);
    expect(hit.segmentIndex).toBe(2);
    expect(hit.fraction).toBeCloseTo(0.5, 9);
    // x-offset in metres at lat0.
    expect(hit.distanceM).toBeCloseTo(R * DEG * 0.0005 * Math.cos((33.65 * DEG)), 3);
  });

  it("preserves exact source endpoints when fraction is effectively 0 or 1", () => {
    const below = nearestPointOnLine(V, [134, 10]);
    expect(below.segmentIndex).toBe(0);
    expect(below.fraction).toBe(0);
    expect(below.coordinate).toEqual([134, 33]); // exact source vertex

    const above = nearestPointOnLine(V, [134, 90]);
    expect(above.segmentIndex).toBe(V.length - 2);
    expect(above.fraction).toBe(1);
    expect(above.coordinate).toEqual([134, 34.5]); // exact source vertex
  });

  it("resolves ties to the lowest segment index", () => {
    // Query exactly at shared vertex coords[1] -> segment 0, fraction 1.
    const hit = nearestPointOnLine(V, [134, 33.5]);
    expect(hit.segmentIndex).toBe(0);
    expect(hit.fraction).toBe(1);
    expect(hit.coordinate).toEqual([134, 33.5]);
    expect(hit.distanceM).toBe(0);
  });

  it("handles a degenerate zero-length segment without NaN", () => {
    const coords: Position[] = [
      [134, 33],
      [134, 33],
      [134, 34],
    ];
    const hit = nearestPointOnLine(coords, [134, 33.5]);
    expect(Number.isNaN(hit.fraction)).toBe(false);
    expect(hit.distanceM).toBeCloseTo(0, 9);
  });
});

describe("line range extraction", () => {
  it("returns a single point for a same-position same-segment range", () => {
    const r = extractLineRange(V, { segmentIndex: 0, fraction: 0.5 }, { segmentIndex: 0, fraction: 0.5 });
    expect(r.direction).toBe("forward");
    expect(r.coordinates).toHaveLength(1);
  });

  it("extracts a same-segment forward range", () => {
    const r = extractLineRange(V, { segmentIndex: 0, fraction: 0.2 }, { segmentIndex: 0, fraction: 0.7 });
    expect(r.direction).toBe("forward");
    expect(r.coordinates).toHaveLength(2);
    expect(r.coordinates[0][1]).toBeCloseTo(33.1, 9); // 33 + 0.5*0.2
    expect(r.coordinates[1][1]).toBeCloseTo(33.35, 9); // 33 + 0.5*0.7
  });

  it("extracts a same-segment reverse range", () => {
    const r = extractLineRange(V, { segmentIndex: 0, fraction: 0.7 }, { segmentIndex: 0, fraction: 0.2 });
    expect(r.direction).toBe("reverse");
    expect(r.coordinates).toHaveLength(2);
    expect(r.coordinates[0][1]).toBeCloseTo(33.35, 9);
    expect(r.coordinates[1][1]).toBeCloseTo(33.1, 9);
  });

  it("preserves every intervening source vertex on a forward multi-segment range", () => {
    const r = extractLineRange(V, { segmentIndex: 0, fraction: 0.5 }, { segmentIndex: 2, fraction: 0.5 });
    expect(r.direction).toBe("forward");
    // [start, coords[1], coords[2], end]
    expect(r.coordinates).toHaveLength(4);
    expect(r.coordinates[0][1]).toBeCloseTo(33.25, 9);
    expect(r.coordinates[1]).toEqual([134, 33.5]);
    expect(r.coordinates[2]).toEqual([134, 34]);
    expect(r.coordinates[3][1]).toBeCloseTo(34.25, 9);
  });

  it("preserves every intervening source vertex on a reverse multi-segment range", () => {
    const r = extractLineRange(V, { segmentIndex: 2, fraction: 0.5 }, { segmentIndex: 0, fraction: 0.5 });
    expect(r.direction).toBe("reverse");
    expect(r.coordinates).toHaveLength(4);
    expect(r.coordinates[0][1]).toBeCloseTo(34.25, 9);
    expect(r.coordinates[1]).toEqual([134, 34]);
    expect(r.coordinates[2]).toEqual([134, 33.5]);
    expect(r.coordinates[3][1]).toBeCloseTo(33.25, 9);
  });

  it("preserves exact source endpoints at fraction 0/1 of the full part", () => {
    const r = extractLineRange(V, { segmentIndex: 0, fraction: 0 }, { segmentIndex: V.length - 2, fraction: 1 });
    expect(r.direction).toBe("forward");
    expect(r.coordinates[0]).toEqual([134, 33]);
    expect(r.coordinates[r.coordinates.length - 1]).toEqual([134, 34.5]);
    expect(r.coordinates.length).toBe(V.length);
  });

  it("removes the duplicate point when from/to both land on the same source vertex", () => {
    // from is vertex coords[0] and to is vertex coords[1] (start of segment 1):
    // the shared vertex must appear only once in the extracted range.
    const coords: Position[] = [
      [134, 33],
      [134, 33.5],
      [134, 34],
    ];
    const r = extractLineRange(coords, { segmentIndex: 0, fraction: 0 }, { segmentIndex: 1, fraction: 0 });
    expect(r.direction).toBe("forward");
    expect(r.coordinates).toEqual([
      [134, 33],
      [134, 33.5],
    ]);
  });

  it("throws on invalid segment refs at the trust boundary", () => {
    // Non-integer segment index.
    expect(() => extractLineRange(V, { segmentIndex: 0.5, fraction: 0 }, { segmentIndex: 1, fraction: 0 }))
      .toThrow(/segmentIndex/);
    // Negative segment index.
    expect(() => extractLineRange(V, { segmentIndex: -1, fraction: 0 }, { segmentIndex: 1, fraction: 0 }))
      .toThrow(/segmentIndex/);
    // Out-of-range segment index (beyond the last segment).
    expect(() => extractLineRange(V, { segmentIndex: 0, fraction: 0 }, { segmentIndex: V.length - 1, fraction: 0 }))
      .toThrow(/segmentIndex/);
  });

  it("throws on invalid fractions at the trust boundary", () => {
    expect(() => extractLineRange(V, { segmentIndex: 0, fraction: NaN }, { segmentIndex: 1, fraction: 0 }))
      .toThrow(/fraction/);
    expect(() => extractLineRange(V, { segmentIndex: 0, fraction: -0.1 }, { segmentIndex: 1, fraction: 0 }))
      .toThrow(/fraction/);
    expect(() => extractLineRange(V, { segmentIndex: 0, fraction: 1.1 }, { segmentIndex: 1, fraction: 0 }))
      .toThrow(/fraction/);
    expect(() => extractLineRange(V, { segmentIndex: 0, fraction: 0 }, { segmentIndex: 1, fraction: Infinity }))
      .toThrow(/fraction/);
  });
});

describe("dedupeConsecutive", () => {
  it("removes only consecutive exact duplicates", () => {
    const coords: Position[] = [
      [134, 33],
      [134, 33],
      [134, 33.5],
      [134, 33.5],
      [134, 34],
    ];
    const out = dedupeConsecutive(coords);
    expect(out).toEqual([
      [134, 33],
      [134, 33.5],
      [134, 34],
    ]);
    expect(dedupeConsecutive([])).toEqual([]);
  });
});

describe("enumeration helpers", () => {
  it("enumerates point parts recursively", () => {
    const geom: GeoJSONGeometry = {
      type: "GeometryCollection",
      geometries: [
        { type: "Point", coordinates: [134, 33] },
        { type: "MultiPoint", coordinates: [[134, 34], [134, 35]] },
        { type: "LineString", coordinates: [[134, 36]] },
      ],
    };
    const parts = enumeratePointParts(geom);
    expect(parts).toEqual([
      [134, 33],
      [134, 34],
      [134, 35],
    ]);
  });

  it("enumerates line parts recursively with stable part indices", () => {
    const geom: GeoJSONGeometry = {
      type: "GeometryCollection",
      geometries: [
        { type: "LineString", coordinates: [[134, 33], [134, 34]] },
        {
          type: "MultiLineString",
          coordinates: [
            [[134, 35], [134, 36]],
            [[134, 37], [134, 38]],
          ],
        },
      ],
    };
    const parts = enumerateLineParts(geom);
    expect(parts).toHaveLength(3);
    expect(parts[0]).toHaveLength(2);
    expect(parts[1]).toHaveLength(2);
    expect(parts[2]).toHaveLength(2);
  });
});