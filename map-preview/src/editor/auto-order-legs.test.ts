import { describe, expect, it } from "vitest";
import type { LinePointRef, Position, RouteLeg, RouteSection } from "./model";
import { autoOrderLegs } from "./auto-order-legs";

const p0: Position = [134, 30];
const p1: Position = [134, 31];
const p2: Position = [134, 32];
const p3: Position = [134, 33];

function leg(id: string, coords: Position[], direction: "forward" | "reverse" = "forward"): RouteLeg {
  return {
    id,
    sourceId: "s",
    featureId: "f",
    partIndex: 0,
    start: {
      sourceId: "s",
      featureId: "f",
      partIndex: 0,
      segmentIndex: 0,
      fraction: 0,
      coordinate: coords[0],
    },
    end: {
      sourceId: "s",
      featureId: "f",
      partIndex: 0,
      segmentIndex: coords.length - 2,
      fraction: 1,
      coordinate: coords[coords.length - 1],
    },
    direction,
    coordinates: coords.slice(),
    lengthM: 100,
  };
}

function anchor(coord: Position): LinePointRef {
  return {
    sourceId: "s",
    featureId: "f",
    partIndex: 0,
    segmentIndex: 0,
    fraction: 0,
    coordinate: coord,
  };
}

function section(
  legs: RouteLeg[],
  fromAnchor: LinePointRef | null,
  toAnchor: LinePointRef | null,
): Pick<RouteSection, "legs" | "fromAnchor" | "toAnchor"> {
  return { legs, fromAnchor, toAnchor };
}

describe("autoOrderLegs — success", () => {
  it("is a no-op (changed=false) when legs are already ordered from→to", () => {
    const legs = [leg("A", [p0, p1]), leg("B", [p1, p2]), leg("C", [p2, p3])];
    const result = autoOrderLegs(section(legs, anchor(p0), anchor(p3)));
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.changed).toBe(false);
    expect(result.reversedCount).toBe(0);
    expect(result.legs.map((l) => l.id)).toEqual(["A", "B", "C"]);
  });

  it("reorders a shuffled selection into a from→to chain", () => {
    const legs = [leg("C", [p2, p3]), leg("A", [p0, p1]), leg("B", [p1, p2])];
    const result = autoOrderLegs(section(legs, anchor(p0), anchor(p3)));
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.changed).toBe(true);
    expect(result.reversedCount).toBe(0);
    expect(result.legs.map((l) => l.id)).toEqual(["A", "B", "C"]);
  });

  it("reverses a single out-of-direction leg (partial reverse)", () => {
    // B stored p2→p1 (reverse); chain p0→p1→p2→p3.
    const legs = [leg("A", [p0, p1]), leg("B", [p2, p1], "reverse"), leg("C", [p2, p3])];
    const result = autoOrderLegs(section(legs, anchor(p0), anchor(p3)));
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.changed).toBe(true);
    expect(result.reversedCount).toBe(1);
    const out = result.legs.map((l) => l.id);
    expect(out).toEqual(["A", "B", "C"]);
    const b = result.legs[1];
    expect(b.start.coordinate).toEqual(p1);
    expect(b.end.coordinate).toEqual(p2);
    expect(b.direction).toBe("forward");
  });

  it("handles a single reverse leg in both directions", () => {
    // Stored p1→p0, anchors p0→p1 => must reverse.
    const legs = [leg("A", [p1, p0], "reverse")];
    const result = autoOrderLegs(section(legs, anchor(p0), anchor(p1)));
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.changed).toBe(true);
    expect(result.reversedCount).toBe(1);
    expect(result.legs[0].start.coordinate).toEqual(p0);
    expect(result.legs[0].end.coordinate).toEqual(p1);
    expect(result.legs[0].direction).toBe("forward");
  });

  it("uses the anchors to set the traversal direction", () => {
    // Same three legs but anchors reversed (p3→p0) => chain reversed.
    const legs = [leg("A", [p0, p1]), leg("B", [p1, p2]), leg("C", [p2, p3])];
    const result = autoOrderLegs(section(legs, anchor(p3), anchor(p0)));
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.changed).toBe(true);
    expect(result.legs.map((l) => l.id)).toEqual(["C", "B", "A"]);
  });

  it("preserves refs and length and consumes every leg exactly once", () => {
    const legs = [leg("A", [p0, p1]), leg("B", [p2, p1], "reverse"), leg("C", [p2, p3])];
    const result = autoOrderLegs(section(legs, anchor(p0), anchor(p3)));
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.legs).toHaveLength(3);
    const ids = result.legs.map((l) => l.id).sort();
    expect(ids).toEqual(["A", "B", "C"]);
    const b = result.legs[1];
    expect(b.sourceId).toBe("s");
    expect(b.featureId).toBe("f");
    expect(b.partIndex).toBe(0);
    expect(b.lengthM).toBe(100);
    // Originals were never mutated.
    expect(legs[1].start.coordinate).toEqual(p2);
    expect(legs[1].coordinates).toEqual([p2, p1]);
  });
});

describe("autoOrderLegs — failure (no mutation)", () => {
  it("rejects when anchors are missing", () => {
    const legs = [leg("A", [p0, p1])];
    expect(autoOrderLegs(section(legs, null, anchor(p1))).ok).toBe(false);
    expect(autoOrderLegs(section(legs, anchor(p0), null)).ok).toBe(false);
  });

  it("rejects an anchor on a shared interior node (degree 2)", () => {
    const legs = [leg("A", [p0, p1]), leg("B", [p1, p2])];
    const result = autoOrderLegs(section(legs, anchor(p1), anchor(p2)));
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.code).toBe("anchor_not_terminal");
  });

  it("rejects an anchor that lies in a leg interior (not an endpoint)", () => {
    const interior: Position = [134, 30.5];
    const legs = [leg("A", [p0, p1]), leg("B", [p1, p2])];
    const result = autoOrderLegs(section(legs, anchor(interior), anchor(p2)));
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.code).toBe("anchor_not_terminal");
  });

  it("rejects disconnected legs (including tiny coordinate differences)", () => {
    const p1d: Position = [134, 31.0000001]; // differs slightly from p1
    const legs = [leg("A", [p0, p1]), leg("B", [p1d, p2]), leg("C", [p2, p3])];
    const result = autoOrderLegs(section(legs, anchor(p0), anchor(p3)));
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.code).toBe("disconnected");
  });

  it("rejects a branch (a node with degree 3)", () => {
    const legs = [leg("A", [p0, p1]), leg("B", [p1, p2]), leg("C", [p1, p3])];
    const result = autoOrderLegs(section(legs, anchor(p0), anchor(p2)));
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.code).toBe("branch");
  });

  it("rejects a cycle (no two distinct terminals)", () => {
    const legs = [leg("A", [p0, p1]), leg("B", [p1, p2]), leg("C", [p2, p0])];
    const result = autoOrderLegs(section(legs, anchor(p0), anchor(p2)));
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.code).toBe("cycle");
  });

  it("rejects parallel edges between the same two points", () => {
    const legs = [leg("A", [p0, p1]), leg("B", [p0, p1])];
    const result = autoOrderLegs(section(legs, anchor(p0), anchor(p1)));
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.code).toBe("parallel");
  });

  it("rejects a self-loop leg (start == end)", () => {
    const legs = [leg("A", [p0, p0])];
    const result = autoOrderLegs(section(legs, anchor(p0), anchor(p1)));
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.code).toBe("self_loop");
  });

  it("rejects duplicate leg ids", () => {
    const legs = [leg("A", [p0, p1]), leg("A", [p1, p2])];
    const result = autoOrderLegs(section(legs, anchor(p0), anchor(p2)));
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.code).toBe("duplicate_leg_id");
  });

  it("rejects a malformed leg (fewer than 2 coordinates)", () => {
    const bad = leg("A", [p0, p1]);
    bad.coordinates = [p0];
    const result = autoOrderLegs(section([bad], anchor(p0), anchor(p1)));
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.code).toBe("invalid_leg_geometry");
  });

  it("rejects a stale start ref (does not match first coordinate)", () => {
    const bad = leg("A", [p0, p1]);
    bad.start.coordinate = p2;
    const result = autoOrderLegs(section([bad], anchor(p0), anchor(p1)));
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.code).toBe("stale_leg_refs");
  });

  it("never mutates the input on failure", () => {
    const legs = [leg("A", [p0, p1]), leg("B", [p1, p2]), leg("C", [p2, p0])];
    const before = JSON.stringify(legs);
    autoOrderLegs(section(legs, anchor(p0), anchor(p2)));
    expect(JSON.stringify(legs)).toBe(before);
  });
});
