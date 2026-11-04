/**
 * Client-side day planner over the 88sekaiisan effective route graph.
 *
 * Mirrors datasets/sekaiisan_henro/planner.py in the browser: snap user points onto the
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
  length_m?: number;
  distance_m?: number;
}

export type EdgeGeometry = Record<string, number[][]>;

export interface PlanGraph {
  kind: "plan_graph";
  nodes: PlanNode[];
  traversal_edges: PlanEdge[];
  synthetic_joins: PlanEdge[];
  edge_geometry?: EdgeGeometry;
}

export interface RouteEdge {
  id: string;
  from: string;
  to: string;
  weight: number;
  coordinates: number[][];
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
  coords: number[][];
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

/**
 * Fill elevation for 2D vertices in a route whose graph is 3D but has a few
 * 2D points (short synthetic joins are exported without height). Heights are
 * linearly interpolated between the nearest 3D vertices before/after; when a
 * whole run is 2D the run keeps the boundary heights. Every point becomes 3D
 * whenever at least one 3D point exists, so the elevation profile never sees
 * gaps in the middle of a 3D graph route.
 */
export function fillElevationInPath(coords: number[][]): number[][] {
  const out: number[][] = coords.map((c) => [c[0], c[1], Number.isFinite(c[2]) ? c[2] : NaN]);
  const known = out.map((c) => c[2]);
  const left = new Array<number>(known.length);
  let prev = NaN;
  for (let i = 0; i < known.length; i++) {
    if (Number.isFinite(known[i])) prev = known[i];
    left[i] = prev;
  }
  const right = new Array<number>(known.length);
  let next = NaN;
  for (let i = known.length - 1; i >= 0; i--) {
    if (Number.isFinite(known[i])) next = known[i];
    right[i] = next;
  }
  for (let i = 0; i < out.length; i++) {
    if (Number.isFinite(out[i][2])) continue;
    const l = left[i];
    const r = right[i];
    if (Number.isFinite(l) && Number.isFinite(r)) {
      out[i][2] = (l + r) / 2;
    } else if (Number.isFinite(l)) {
      out[i][2] = l;
    } else if (Number.isFinite(r)) {
      out[i][2] = r;
    } else {
      out[i][2] = 0;
    }
  }
  return out;
}

/** Normalize graph edges to a uniform undirected weighted edge list. */
export function routeEdges(graph: PlanGraph): RouteEdge[] {
  const geo = graph.edge_geometry ?? {};
  const edges: RouteEdge[] = [];
  for (const e of graph.traversal_edges) {
    const coords = geo[e.id] ?? ([[], []] as number[][]);
    edges.push({
      id: e.id,
      from: e.from,
      to: e.to,
      weight: e.length_m ?? 0,
      coordinates: coords as [number, number][],
    });
  }
  for (const e of graph.synthetic_joins) {
    const coords = geo[e.id] ?? ([[], []] as number[][]);
    edges.push({
      id: e.id,
      from: e.from,
      to: e.to,
      weight: e.distance_m ?? 0,
      coordinates: coords as [number, number][],
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

// --- Spatial index for fast point-to-route snapping -----------------------
//
// The routing graph is split into topology + geometry: a chosen route only
// materialises the polyline vertices it actually draws. Snapping still needs
// to find the nearest route edge to a click, but scanning every vertex of
// every edge is O(edges x vertices). Instead we bucket edge segments into a
// fixed grid (cell ~50m in the shared equirectangular metric), so a click
// only inspects segments in the small set of overlapping cells.

interface GridSegment {
  edge: RouteEdge;
  aIdx: number;
  a: [number, number];
  b: [number, number];
}

export interface SnapIndex {
  cellSize: number; // metres
  cells: Map<string, GridSegment[]>;
  edges: RouteEdge[];
}

export function buildSnapIndex(edges: RouteEdge[], cellSize = 50): SnapIndex {
  const cells = new Map<string, GridSegment[]>();
  for (const edge of edges) {
    const pts = edge.coordinates;
    for (let i = 0; i < pts.length - 1; i++) {
      const a = [pts[i][0], pts[i][1]] as [number, number];
      const b = [pts[i + 1][0], pts[i + 1][1]] as [number, number];
      const seg: GridSegment = { edge, aIdx: i, a, b };
      const [ax, ay] = xy(a[0], a[1]);
      const [bx, by] = xy(b[0], b[1]);
      const minX = Math.min(ax, bx);
      const maxX = Math.max(ax, bx);
      const minY = Math.min(ay, by);
      const maxY = Math.max(ay, by);
      const cx0 = Math.floor(minX / cellSize);
      const cx1 = Math.floor(maxX / cellSize);
      const cy0 = Math.floor(minY / cellSize);
      const cy1 = Math.floor(maxY / cellSize);
      for (let gx = cx0; gx <= cx1; gx++) {
        for (let gy = cy0; gy <= cy1; gy++) {
          const key = `${gx}:${gy}`;
          if (!cells.has(key)) cells.set(key, []);
          cells.get(key)!.push(seg);
        }
      }
    }
  }
  return { cellSize, cells, edges };
}

/** Project a WGS84 point onto the nearest segment in a grid snap index. */
export function snapPointIndexed(
  index: SnapIndex,
  lon: number,
  lat: number,
): SnapResult | null {
  const { cellSize, cells } = index;
  const p = xy(lon, lat);
  const gx = Math.floor(p[0] / cellSize);
  const gy = Math.floor(p[1] / cellSize);
  const radius = 1;
  let best: SnapResult | null = null;
  for (let dx = -radius; dx <= radius; dx++) {
    for (let dy = -radius; dy <= radius; dy++) {
      const segs = cells.get(`${gx + dx}:${gy + dy}`);
      if (!segs) continue;
      for (const seg of segs) {
        const hit = projectOnEdge(seg.edge, lon, lat);
        if (!best || hit.distanceM < best.distanceM) {
          best = {
            edgeId: seg.edge.id,
            distanceM: hit.distanceM,
            measureM: hit.measureM,
            fraction: hit.fraction,
            projection: hit.projection,
          };
        }
      }
    }
  }
  return best;
}

/** Substring of an edge between two measures, mirroring shapely substring().
 *  Elevation is carried through: an interpolated point between two 3D
 *  vertices gets the linearly interpolated height. */
function substringCoords(
  edge: RouteEdge,
  a: number,
  b: number,
): number[][] {
  const pts = edge.coordinates.map((c) => xy(c[0], c[1]));
  const cum = [0];
  for (let i = 1; i < pts.length; i++) {
    cum.push(cum[i - 1] + Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]));
  }
  const interp = (offset: number): number[] => {
    let i = 0;
    while (i < cum.length - 1 && cum[i + 1] < offset) i++;
    const t = cum[i + 1] - cum[i] > 0 ? (offset - cum[i]) / (cum[i + 1] - cum[i]) : 0;
    const lon = unxy(pts[i][0] + t * (pts[i + 1][0] - pts[i][0]), pts[i][1] + t * (pts[i + 1][1] - pts[i][1]));
    const e0 = edge.coordinates[i];
    const e1 = edge.coordinates[i + 1];
    const out: number[] = [lon[0], lon[1]];
    if (e0.length >= 3 && e1.length >= 3) {
      out.push(e0[2] + t * (e1[2] - e0[2]));
    }
    return out;
  };
  const out: number[][] = [interp(a)];
  for (let k = 0; k < cum.length; k++) {
    if (cum[k] > a && cum[k] < b) out.push([...edge.coordinates[k]]);
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

/** Stitch edge coordinates along the path into one dense coordinate list.
 *  Coordinates keep the source dimension (2D for 2D graphs, 3D when the
 *  graph's edge_geometry carries elevation). */
export function stitchCoords(
  edgeIds: string[],
  nodeIds: string[],
  edgesById: Map<string, RouteEdge>,
): number[][] {
  const coords: number[][] = [];
  for (let i = 0; i < edgeIds.length; i++) {
    const edge = edgesById.get(edgeIds[i]);
    if (!edge) continue;
    const forward = edge.from === nodeIds[i];
    let seq: number[][] = edge.coordinates;
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
  const allCoords: number[][] = [];
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