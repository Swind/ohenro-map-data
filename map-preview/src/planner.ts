/**
 * Client-side day planner over the 88sekaiisan effective route graph.
 *
 * Mirrors sekaiisan_henro/planner.py in the browser: snap user points onto the
 * nearest traversal edge (equirectangular metric projection), split the
 * snapped edges into virtual sub-edges, and run the same weighted Dijkstra
 * (simple paths, deterministic tie-break) over traversal_edges +
 * synthetic_joins only. Never claims resolved / official / navigable.
 */

export interface PlanNode {
  id: string;
  lon: number;
  lat: number;
}

export interface PlanEdge {
  id: string;
  from: string;
  to: string;
  coordinates: number[][];
  length_m?: number;
  distance_m?: number;
}

export interface PlanGraph {
  kind: "plan_graph";
  nodes: PlanNode[];
  traversal_edges: PlanEdge[];
  synthetic_joins: PlanEdge[];
}

export interface RouteEdge {
  id: string;
  from: string;
  to: string;
  weight: number;
  coordinates: [number, number][];
}

export interface SnapResult {
  edgeId: string;
  distanceM: number;
  measureM: number;
  fraction: number;
  projection: [number, number];
}

export interface PlanPoint {
  index: number;
  lon: number;
  lat: number;
  edgeId: string;
  distanceM: number;
  projection: [number, number];
}

export interface PlanLeg {
  fromIndex: number;
  toIndex: number;
  status: "candidate" | "disconnected";
  lengthM?: number;
  edgeIds?: string[];
}

export interface PlanResult {
  status: "candidate" | "disconnected";
  lengthM: number | null;
  coords: [number, number][];
  legs: PlanLeg[];
  points: PlanPoint[];
  waypointNodes: string[];
}

const R = 6371008.8;
const LON0 = 133.75;
const LAT0 = 33.65;
const RAD = Math.PI / 180;
const COS_LAT0 = Math.cos(LAT0 * RAD);

export function xy(lon: number, lat: number): [number, number] {
  return [R * (lon - LON0) * RAD * COS_LAT0, R * (lat - LAT0) * RAD];
}

export function unxy(x: number, y: number): [number, number] {
  return [LON0 + x / (R * COS_LAT0) / RAD, LAT0 + y / R / RAD];
}

export function lineMeters(coords: number[][]): number {
  let total = 0;
  for (let i = 1; i < coords.length; i++) {
    const [x1, y1] = xy(coords[i - 1][0], coords[i - 1][1]);
    const [x2, y2] = xy(coords[i][0], coords[i][1]);
    total += Math.hypot(x2 - x1, y2 - y1);
  }
  return total;
}

/** Normalize graph edges to a uniform undirected weighted edge list. */
export function routeEdges(graph: PlanGraph): RouteEdge[] {
  const edges: RouteEdge[] = [];
  for (const e of graph.traversal_edges) {
    edges.push({
      id: e.id,
      from: e.from,
      to: e.to,
      weight: e.length_m ?? 0,
      coordinates: e.coordinates as [number, number][],
    });
  }
  for (const e of graph.synthetic_joins) {
    edges.push({
      id: e.id,
      from: e.from,
      to: e.to,
      weight: e.distance_m ?? 0,
      coordinates: e.coordinates as [number, number][],
    });
  }
  return edges;
}

/** Project a WGS84 point onto the nearest segment of an edge. */
function projectOnEdge(
  edge: RouteEdge,
  lon: number,
  lat: number,
): { measureM: number; fraction: number; projection: [number, number]; distanceM: number } {
  const pts = edge.coordinates.map((c) => xy(c[0], c[1]));
  const cum = [0];
  for (let i = 1; i < pts.length; i++) {
    cum.push(cum[i - 1] + Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]));
  }
  const length = cum[cum.length - 1];
  const p = xy(lon, lat);
  let best: { d: number; t: number; measure: number; seg: number } | null = null;
  for (let i = 0; i < pts.length - 1; i++) {
    const [ax, ay] = pts[i];
    const [bx, by] = pts[i + 1];
    const abx = bx - ax;
    const aby = by - ay;
    const denom = abx * abx + aby * aby;
    let t = denom > 0 ? ((p[0] - ax) * abx + (p[1] - ay) * aby) / denom : 0;
    t = Math.max(0, Math.min(1, t));
    const qx = ax + t * abx;
    const qy = ay + t * aby;
    const d = Math.hypot(p[0] - qx, p[1] - qy);
    const measure = cum[i] + t * (cum[i + 1] - cum[i]);
    if (!best || d < best.d) best = { d, t, measure, seg: i };
  }
  const { t, measure, seg } = best!;
  const [ax, ay] = pts[seg];
  const [bx, by] = pts[seg + 1];
  const projection = unxy(ax + t * (bx - ax), ay + t * (by - ay));
  return {
    measureM: measure,
    fraction: length > 0 ? measure / length : 0,
    projection,
    distanceM: best!.d,
  };
}

export function snapPoint(
  edges: RouteEdge[],
  lon: number,
  lat: number,
): SnapResult | null {
  let best: SnapResult | null = null;
  for (const edge of edges) {
    const hit = projectOnEdge(edge, lon, lat);
    if (!best || hit.distanceM < best.distanceM) {
      best = {
        edgeId: edge.id,
        distanceM: hit.distanceM,
        measureM: hit.measureM,
        fraction: hit.fraction,
        projection: hit.projection,
      };
    }
  }
  return best;
}

/** Substring of an edge between two measures, mirroring shapely substring(). */
function substringCoords(
  edge: RouteEdge,
  a: number,
  b: number,
): [number, number][] {
  const pts = edge.coordinates.map((c) => xy(c[0], c[1]));
  const cum = [0];
  for (let i = 1; i < pts.length; i++) {
    cum.push(cum[i - 1] + Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]));
  }
  const interp = (offset: number): [number, number] => {
    let i = 0;
    while (i < cum.length - 1 && cum[i + 1] < offset) i++;
    const t = cum[i + 1] - cum[i] > 0 ? (offset - cum[i]) / (cum[i + 1] - cum[i]) : 0;
    return unxy(pts[i][0] + t * (pts[i + 1][0] - pts[i][0]), pts[i][1] + t * (pts[i + 1][1] - pts[i][1]));
  };
  const out: [number, number][] = [interp(a)];
  for (let k = 0; k < cum.length; k++) {
    if (cum[k] > a && cum[k] < b) out.push([edge.coordinates[k][0], edge.coordinates[k][1]]);
  }
  const end = interp(b);
  const last = out[out.length - 1];
  if (last[0] !== end[0] || last[1] !== end[1]) out.push(end);
  return out;
}

function adjacency(edges: RouteEdge[]): Map<string, Array<{ to: string; weight: number; id: string }>> {
  const adj = new Map<string, Array<{ to: string; weight: number; id: string }>>();
  const add = (a: string, b: string, weight: number, id: string): void => {
    if (!adj.has(a)) adj.set(a, []);
    adj.get(a)!.push({ to: b, weight, id });
  };
  for (const e of edges) {
    add(e.from, e.to, e.weight, e.id);
    add(e.to, e.from, e.weight, e.id);
  }
  return adj;
}

/** Compare tuples (weight, edgeSeq, nodeSeq) exactly like Python tuples. */
function tupleLt(
  aw: number, ae: string[], an: string[],
  bw: number, be: string[], bn: string[],
): boolean {
  if (aw !== bw) return aw < bw;
  const aek = ae.join("\u0000");
  const bek = be.join("\u0000");
  if (aek !== bek) return aek < bek;
  return an.join("\u0000") < bn.join("\u0000");
}

export function shortestPath(
  adj: Map<string, Array<{ to: string; weight: number; id: string }>>,
  start: string,
  goal: string,
): { weight: number; edgeIds: string[]; nodeIds: string[] } | null {
  if (start === goal) return { weight: 0, edgeIds: [], nodeIds: [start] };
  // Binary heap of (weight, edgeSeq, nodeSeq, node). Simple paths only.
  const heap: Array<{ w: number; es: string[]; ns: string[]; node: string }> = [];
  const push = (item: { w: number; es: string[]; ns: string[]; node: string }): void => {
    heap.push(item);
    let i = heap.length - 1;
    while (i > 0) {
      const parent = (i - 1) >> 1;
      if (!tupleLt(heap[i].w, heap[i].es, heap[i].ns, heap[parent].w, heap[parent].es, heap[parent].ns)) break;
      [heap[i], heap[parent]] = [heap[parent], heap[i]];
      i = parent;
    }
  };
  const pop = (): { w: number; es: string[]; ns: string[]; node: string } | undefined => {
    if (heap.length === 0) return undefined;
    const top = heap[0];
    const last = heap.pop()!;
    if (heap.length > 0) {
      heap[0] = last;
      let i = 0;
      for (;;) {
        const l = 2 * i + 1;
        const r = l + 1;
        let smallest = i;
        if (l < heap.length && tupleLt(heap[l].w, heap[l].es, heap[l].ns, heap[smallest].w, heap[smallest].es, heap[smallest].ns)) smallest = l;
        if (r < heap.length && tupleLt(heap[r].w, heap[r].es, heap[r].ns, heap[smallest].w, heap[smallest].es, heap[smallest].ns)) smallest = r;
        if (smallest === i) break;
        [heap[i], heap[smallest]] = [heap[smallest], heap[i]];
        i = smallest;
      }
    }
    return top;
  };

  // best[node] = (weight, edgeSeq, nodeSeq)
  const best = new Map<string, { w: number; es: string[]; ns: string[] }>();
  push({ w: 0, es: [], ns: [start], node: start });
  let item = pop();
  while (item) {
    const { w, es, ns, node } = item;
    const current = best.get(node);
    if (current && !tupleLt(w, es, ns, current.w, current.es, current.ns)) {
      item = pop();
      continue;
    }
    best.set(node, { w, es, ns });
    for (const { to, weight, id } of adj.get(node) ?? []) {
      if (ns.includes(to)) continue; // no node revisit
      push({ w: w + weight, es: [...es, id], ns: [...ns, to], node: to });
    }
    item = pop();
  }
  const result = best.get(goal);
  if (!result) return null;
  return { weight: result.w, edgeIds: result.es, nodeIds: result.ns };
}

/** Stitch edge coordinates along the path into one dense coordinate list. */
export function stitchCoords(
  edgeIds: string[],
  nodeIds: string[],
  edgesById: Map<string, RouteEdge>,
): [number, number][] {
  const coords: [number, number][] = [];
  for (let i = 0; i < edgeIds.length; i++) {
    const edge = edgesById.get(edgeIds[i]);
    if (!edge) continue;
    const forward = edge.from === nodeIds[i];
    let seq: [number, number][] = edge.coordinates;
    if (!forward) seq = [...edge.coordinates].reverse();
    const last = coords[coords.length - 1];
    if (last && last[0] === seq[0][0] && last[1] === seq[0][1]) seq = seq.slice(1);
    coords.push(...seq);
  }
  return coords;
}

export function planRoute(
  graph: PlanGraph,
  points: Array<{ lon: number; lat: number }>,
  snapMaxM = 500,
): PlanResult {
  if (points.length < 2) throw new Error("plan requires at least two points");
  const edges = routeEdges(graph);
  const edgesById = new Map(edges.map((e) => [e.id, e]));

  // Snap each point, group by snapped edge (sorted by fraction).
  const byEdge = new Map<string, Array<{ index: number; fraction: number; proj: [number, number]; edge: RouteEdge; distanceM: number }>>();
  const planPoints: PlanPoint[] = [];
  for (let index = 0; index < points.length; index++) {
    const snap = snapPoint(edges, points[index].lon, points[index].lat);
    if (!snap) throw new Error(`no routable traversal edge for point ${index}`);
    if (snap.distanceM > snapMaxM) {
      throw new Error(
        `point ${index} (${points[index].lon.toFixed(5)},${points[index].lat.toFixed(5)}) ` +
        `is ${snap.distanceM.toFixed(1)}m from the nearest route edge (max ${snapMaxM}m)`,
      );
    }
    const fraction = Math.min(Math.max(snap.fraction, 1e-9), 1 - 1e-9);
    if (!byEdge.has(snap.edgeId)) byEdge.set(snap.edgeId, []);
    byEdge.get(snap.edgeId)!.push({
      index, fraction, proj: snap.projection,
      edge: edgesById.get(snap.edgeId)!, distanceM: snap.distanceM,
    });
    planPoints.push({
      index, lon: points[index].lon, lat: points[index].lat,
      edgeId: snap.edgeId, distanceM: snap.distanceM, projection: snap.projection,
    });
  }

  // Virtual sub-edges on snapped edges.
  const virtual: RouteEdge[] = [];
  const waypointNodes: string[] = [];
  const snappedIds = new Set<string>();
  for (const [edgeId, snaps] of byEdge) {
    const edge = snaps[0].edge;
    snappedIds.add(edgeId);
    const ordered = [...snaps].sort((a, b) => a.fraction - b.fraction);
    const chain: string[] = [edge.from];
    for (const s of ordered) {
      const nodeId = `PLN_${edgeId}_${String(s.index).padStart(2, "0")}`;
      waypointNodes[s.index] = nodeId;
      chain.push(nodeId);
    }
    chain.push(edge.to);
    const length = lineMeters(edge.coordinates);
    const measures = [0, ...ordered.map((s) => s.fraction * length), length];
    for (let i = 0; i < chain.length - 1; i++) {
      const coords = substringCoords(edge, measures[i], measures[i + 1]);
      virtual.push({
        id: `PLV_${virtual.length}`,
        from: chain[i],
        to: chain[i + 1],
        weight: lineMeters(coords),
        coordinates: coords,
      });
    }
  }

  const baseEdges = edges.filter((e) => !snappedIds.has(e.id));
  const adj = adjacency([...baseEdges, ...virtual]);
  const allEdgesById = new Map(edgesById);
  for (const v of virtual) allEdgesById.set(v.id, v);

  // Per-leg Dijkstra.
  const legs: PlanLeg[] = [];
  const allCoords: [number, number][] = [];
  let disconnected = false;
  for (let i = 0; i < points.length - 1; i++) {
    const start = waypointNodes[i];
    const goal = waypointNodes[i + 1];
    const leg: PlanLeg = { fromIndex: i, toIndex: i + 1, status: "disconnected" };
    const result = shortestPath(adj, start, goal);
    if (result) {
      leg.status = "candidate";
      leg.lengthM = result.weight;
      leg.edgeIds = result.edgeIds;
      const legCoords = stitchCoords(result.edgeIds, result.nodeIds, allEdgesById);
      const last = allCoords[allCoords.length - 1];
      if (last && last[0] === legCoords[0][0] && last[1] === legCoords[0][1]) legCoords.shift();
      allCoords.push(...legCoords);
    } else {
      disconnected = true;
    }
    legs.push(leg);
  }

  return {
    status: disconnected || allCoords.length === 0 ? "disconnected" : "candidate",
    lengthM: disconnected || allCoords.length === 0 ? null : lineMeters(allCoords),
    coords: allCoords,
    legs,
    points: planPoints,
    waypointNodes: points.map((_, i) => waypointNodes[i]),
  };
}