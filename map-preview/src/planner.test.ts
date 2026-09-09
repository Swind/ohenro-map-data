import { describe, expect, it } from "vitest";
import {
  buildSnapIndex,
  lineMeters,
  planRoute,
  routeEdges,
  snapPoint,
  snapPointIndexed,
  type PlanEdge,
  type PlanGraph,
} from "./planner";

const COORDS: Record<string, [number, number]> = {
  A: [133.0, 33.0],
  B: [133.001, 33.0],
  C: [133.002, 33.0],
  D: [133.0005, 33.0007],
  E: [133.003, 33.0],
  F: [133.004, 33.0],
};

function lenM(a: string, b: string): number {
  return lineMeters([COORDS[a], COORDS[b]]);
}

function te(id: string, a: string, b: string): PlanEdge {
  return {
    id,
    from: a,
    to: b,
    length_m: lenM(a, b),
  };
}

function graph(edges: PlanEdge[], joins: PlanEdge[] = []): PlanGraph {
  const nodeIds = new Set<string>();
  const edge_geometry: Record<string, number[][]> = {};
  const collect = (list: PlanEdge[]): void => {
    for (const e of list) {
      nodeIds.add(e.from);
      nodeIds.add(e.to);
      edge_geometry[e.id] = [COORDS[e.from], COORDS[e.to]];
    }
  };
  collect(edges);
  collect(joins);
  return {
    kind: "plan_graph",
    nodes: [...nodeIds]
      .sort()
      .map((id) => ({ id, lon: COORDS[id][0], lat: COORDS[id][1] })),
    traversal_edges: edges,
    synthetic_joins: joins,
    edge_geometry,
  };
}

function plan(g: PlanGraph, pts: Array<[number, number]>, snapMaxM = 500) {
  return planRoute(g, pts.map(([lon, lat]) => ({ lon, lat })), snapMaxM);
}

describe("planRoute", () => {
  it("picks the short branch", () => {
    const g = graph([te("e1", "A", "B"), te("e2", "B", "C"), te("e3", "A", "D"), te("e4", "D", "C")]);
    const short = lenM("A", "B") + lenM("B", "C");
    const result = plan(g, [COORDS["A"], COORDS["C"]]);
    expect(result.status).toBe("candidate");
    expect(result.lengthM).toBeCloseTo(short, 1);
    expect(result.legs[0].status).toBe("candidate");
  });

  it("waypoint forces the longer detour", () => {
    const g = graph([te("e1", "A", "B"), te("e2", "B", "C"), te("e3", "A", "D"), te("e4", "D", "C")]);
    const detour = lenM("A", "D") + lenM("D", "C");
    const result = plan(g, [COORDS["A"], COORDS["D"], COORDS["C"]]);
    expect(result.status).toBe("candidate");
    expect(result.lengthM).toBeCloseTo(detour, 1);
    expect(result.legs).toHaveLength(2);
  });

  it("connects two points on the same edge directly", () => {
    const g = graph([te("e1", "A", "B")]);
    const mid: [number, number] = [133.0005, 33.0];
    const result = plan(g, [COORDS["A"], mid]);
    expect(result.status).toBe("candidate");
    expect(result.lengthM).toBeCloseTo(lenM("A", "B") / 2, 1);
    expect(result.coords).toHaveLength(2); // A -> projected mid
  });

  it("reports disconnected components", () => {
    const g = graph([te("e1", "A", "B"), te("e5", "E", "F")]);
    const result = plan(g, [COORDS["A"], COORDS["E"]]);
    expect(result.status).toBe("disconnected");
    expect(result.lengthM).toBeNull();
    expect(result.legs[0].status).toBe("disconnected");
  });

  it("rejects a point far from the route", () => {
    const g = graph([te("e1", "A", "B")]);
    expect(() => plan(g, [COORDS["A"], [132.0, 33.0]], 500)).toThrow();
  });

  it("keeps intermediate edge vertices in the stitched path", () => {
    const edge = te("e1", "A", "C");
    const coords: [number, number][] = [
      COORDS["A"],
      [133.0005, 33.0],
      [133.001, 33.0],
      [133.0015, 33.0],
      COORDS["C"],
    ];
    const g = graph([edge]);
    g.edge_geometry!["e1"] = coords;
    edge.length_m = lineMeters(coords);
    const result = plan(g, [COORDS["A"], COORDS["C"]]);
    expect(result.status).toBe("candidate");
    expect(result.coords).toHaveLength(5);
  });
});

describe("snapPointIndexed", () => {
  it("matches snapPoint on the nearest edge of a multi-edge graph", () => {
    const edges = [te("e1", "A", "B"), te("e2", "B", "C"), te("e3", "A", "D"), te("e4", "D", "C")];
    const g = graph(edges);
    const indexed = snapPointIndexed(buildSnapIndex(routeEdges(g)), 133.0005, 33.0003);
    const brute = snapPoint(routeEdges(g), 133.0005, 33.0003);
    expect(indexed).not.toBeNull();
    expect(indexed!.edgeId).toBe(brute!.edgeId);
    expect(indexed!.distanceM).toBeCloseTo(brute!.distanceM, 6);
    expect(indexed!.projection[0]).toBeCloseTo(brute!.projection[0], 6);
    expect(indexed!.projection[1]).toBeCloseTo(brute!.projection[1], 6);
  });

  it("snaps a point near a long edge's interior vertex", () => {
    const edge = te("e1", "A", "C");
    const g = graph([edge]);
    g.edge_geometry!["e1"] = [
      COORDS["A"],
      [133.0005, 33.0],
      [133.001, 33.0],
      [133.0015, 33.0],
      COORDS["C"],
    ];
    const result = snapPointIndexed(buildSnapIndex(routeEdges(g)), 133.001, 33.0001);
    expect(result).not.toBeNull();
    expect(result!.edgeId).toBe("e1");
    expect(result!.projection[0]).toBeCloseTo(133.001, 3);
    expect(result!.projection[1]).toBeCloseTo(33.0, 3);
  });

  it("returns null when the point is far from every edge", () => {
    const g = graph([te("e1", "A", "B")]);
    const result = snapPointIndexed(buildSnapIndex(routeEdges(g)), 133.5, 33.5);
    expect(result).toBeNull();
  });
});