import { describe, expect, it } from "vitest";
import { lineLengthM } from "./geometry";
import type { EditorProject, LinePointRef, Position, RouteLeg, RouteSection } from "./model";
import { deriveLegGaps, summarizeProject, summarizeSection } from "./validation";

function mkLeg(id: string, coords: Position[], lengthM?: number): RouteLeg {
  const n = coords.length;
  const start: LinePointRef = {
    sourceId: "s",
    featureId: "f",
    partIndex: 0,
    segmentIndex: 0,
    fraction: 0,
    coordinate: coords[0],
  };
  const end: LinePointRef = {
    sourceId: "s",
    featureId: "f",
    partIndex: 0,
    segmentIndex: n - 2,
    fraction: 1,
    coordinate: coords[n - 1],
  };
  return {
    id,
    sourceId: "s",
    featureId: "f",
    partIndex: 0,
    start,
    end,
    direction: "forward",
    coordinates: coords,
    lengthM: lengthM ?? lineLengthM(coords),
  };
}

function mkSection(id: string, legs: RouteLeg[]): RouteSection {
  const first = legs[0]?.start.coordinate ?? null;
  const last = legs[legs.length - 1]?.end.coordinate ?? null;
  return {
    id,
    fromPoi: first === null ? null : { sourceId: "s", featureId: "p0", coordinate: first },
    toPoi: last === null ? null : { sourceId: "s", featureId: "p1", coordinate: last },
    fromAnchor: legs[0]?.start ?? null,
    toAnchor: legs[legs.length - 1]?.end ?? null,
    waypoints: [],
    legs,
  };
}

describe("exact continuity and gap detection", () => {
  it("reports no gap when consecutive legs meet at an exact shared coordinate", () => {
    const legs = [
      mkLeg("l0", [[134, 33], [134, 33.5]]),
      mkLeg("l1", [[134, 33.5], [134, 34]]),
    ];
    expect(deriveLegGaps(legs)).toEqual([]);
    const summary = summarizeSection(mkSection("S", legs));
    expect(summary.status).toBe("continuous");
    expect(summary.gaps).toEqual([]);
  });

  it("reports a gap (with metric distance) when endpoints differ", () => {
    const legs = [
      mkLeg("l0", [[134, 33], [134, 33.5]]),
      mkLeg("l1", [[134, 33.6], [134, 34]]),
    ];
    const gaps = deriveLegGaps(legs);
    expect(gaps).toHaveLength(1);
    expect(gaps[0].betweenLegIndex).toBe(0);
    expect(gaps[0].from).toEqual([134, 33.5]);
    expect(gaps[0].to).toEqual([134, 33.6]);
    expect(gaps[0].distanceM).toBeCloseTo(lineLengthM([[134, 33.5], [134, 33.6]]), 9);

    const summary = summarizeSection(mkSection("S", legs));
    expect(summary.status).toBe("has_gaps");
    expect(summary.totalGapM).toBeCloseTo(gaps[0].distanceM, 9);
  });
});

describe("section summary", () => {
  it("reports empty status for a section with no legs", () => {
    const summary = summarizeSection(mkSection("S", []));
    expect(summary.status).toBe("empty");
    expect(summary.legCount).toBe(0);
    expect(summary.routeLengthM).toBe(0);
    expect(summary.totalGapM).toBe(0);
  });

  it("sums leg lengths, excluding gaps and POI offsets", () => {
    // Explicit lengthM values prove the summary uses only leg lengths
    // (POI offsets and gaps are never part of a leg and so never counted).
    const legs = [
      mkLeg("l0", [[134, 33], [134, 33.5]], 50),
      mkLeg("l1", [[134, 33.6], [134, 34]], 70),
    ];
    const summary = summarizeSection(mkSection("S", legs));
    expect(summary.routeLengthM).toBe(120);
    expect(summary.totalGapM).toBeCloseTo(0.1 * Math.PI / 180 * 6371008.8, 3);
  });
});

describe("issue detection", () => {
  it("flags missing anchors and invalid numbers/references", () => {
    const leg = mkLeg("l0", [[134, 33], [134, 34]], 100);
    const section: RouteSection = {
      ...mkSection("S", [leg]),
      fromAnchor: null,
    };
    const bad = { ...leg, lengthM: -5 };
    const section2: RouteSection = { ...mkSection("S2", [bad]) };
    const badRef = { ...leg, start: { ...leg.start, segmentIndex: -1 } };
    const section3: RouteSection = { ...mkSection("S3", [badRef]) };

    expect(summarizeSection(section).issues.some((i) => i.includes("fromAnchor"))).toBe(true);
    expect(summarizeSection(section2).issues.some((i) => i.includes("lengthM"))).toBe(true);
    expect(summarizeSection(section3).issues.some((i) => i.includes("start ref"))).toBe(true);
  });

  it("flags a leg whose start ref coordinate disagrees with its first coordinate", () => {
    const leg = mkLeg("l0", [[134, 33], [134, 34]], 100);
    const bad = { ...leg, start: { ...leg.start, coordinate: [134, 33.1] as Position } };
    const section = mkSection("S", [bad]);
    expect(summarizeSection(section).issues.some((i) => i.includes("start ref coordinate"))).toBe(true);
  });

  it("flags a leg with fewer than 2 coordinates", () => {
    const leg = mkLeg("l0", [[134, 33]]);
    const summary = summarizeSection(mkSection("S", [leg]));
    expect(summary.issues.some((i) => i.includes("fewer than 2"))).toBe(true);
  });

  it("flags an anchor whose coordinate disagrees with the section endpoint", () => {
    const leg = mkLeg("l0", [[134, 33], [134, 34]], 100);
    const section = {
      ...mkSection("S", [leg]),
      fromAnchor: { ...leg.start, coordinate: [134, 33.5] as Position },
    };
    const summary = summarizeSection(section);
    expect(summary.issues.some((i) => i.includes("fromAnchor coordinate does not match"))).toBe(true);
    // POIs are allowed to be offset from the anchors.
    expect(summary.issues.some((i) => i.includes("fromPoi"))).toBe(false);
  });

  it("does not flag anchors when a section has no legs", () => {
    const section = mkSection("S", []);
    expect(summarizeSection(section).issues.some((i) => i.includes("anchor coordinate does not match"))).toBe(false);
  });
});

describe("project summary", () => {
  it("aggregates sections and total length", () => {
    const project: EditorProject = {
      schema_version: 1,
      kind: "ohenro_route_editor_project",
      projectId: "p1",
      sources: [],
      sections: [
        mkSection("S1", [mkLeg("a", [[134, 33], [134, 33.5]], 60)]),
        mkSection("S2", [mkLeg("b", [[134, 33.5], [134, 34]], 40)]),
      ],
    };
    const summary = summarizeProject(project);
    expect(summary.projectId).toBe("p1");
    expect(summary.sectionCount).toBe(2);
    expect(summary.totalRouteLengthM).toBe(100);
    expect(summary.sections.map((s) => s.status)).toEqual(["continuous", "continuous"]);
  });
});