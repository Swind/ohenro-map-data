/**
 * Exact-only automatic ordering of the selected legs of a route section.
 *
 * This is NOT routing. It never chooses a path or a subset from all source
 * features, never adds/joins legs, never snaps/proximity-links, and never uses
 * POI offset distance. It operates only on `section.legs`: given the section's
 * `fromAnchor`/`toAnchor`, it reorders (and, where needed, reverses) the
 * already-selected whole legs so they form a single fromAnchor→toAnchor chain.
 *
 * Direction is governed by the ANCHORS, not the POIs: a POI may legitimately
 * sit off the route (a discrete reference with a visual offset to its anchor),
 * so sorting by `fromPoi`/`toPoi` would be wrong. Conceptually the user picks a
 * start/end POI to name the interval, but the actual ordering follows the
 * corresponding anchors. See map-preview/README.md.
 *
 * Safety (all exact, component-wise `===` WGS84 coordinate equality):
 *   - both anchors are required;
 *   - every leg is consumed exactly once, with a unique non-empty id and a
 *     finite, valid geometry of >= 2 coordinates whose first/last coordinates
 *     exactly match `leg.start.coordinate`/`leg.end.coordinate`;
 *   - the selected legs must form a UNIQUE simple chain from the fromAnchor to
 *     the toAnchor: no self-loops/cycles, no branching, no extra terminals, no
 *     parallel ambiguity, all in one connected component;
 *   - the anchors must lie exactly on the chain endpoints (a leg-interior or
 *     non-endpoint anchor is rejected, never auto-split);
 *   - start/end nodes have degree 1 and every other node degree 2.
 *
 * On success the legs are ordered from→to; any leg needing to be reversed has
 * its start/end swapped, coordinates reversed and direction flipped while its
 * id/sourceId/featureId/partIndex/lengthM are preserved. On failure nothing is
 * mutated and a `code`/`reason` is returned.
 */

import type { Position, RouteLeg, RouteSection } from "./model";
import { isValidPosition } from "./geometry";

/** Success: ordered legs, how many were reversed, and whether anything changed. */
export interface AutoOrderSuccess {
  ok: true;
  legs: RouteLeg[];
  reversedCount: number;
  /** False when the legs are already ordered forward from→to (no change needed). */
  changed: boolean;
}

/** Failure: nothing mutated; a stable machine code plus a human reason. */
export interface AutoOrderFailure {
  ok: false;
  code: string;
  reason: string;
}

export type AutoOrderResult = AutoOrderSuccess | AutoOrderFailure;

/** Exact WGS84 component-wise equality (`===`). */
function samePosition(a: Position, b: Position): boolean {
  return a[0] === b[0] && a[1] === b[1];
}

/**
 * A stable node key for a coordinate. `-0` is normalised to `+0` so the key
 * mirrors `===` semantics (where `-0 === 0`). Distinct doubles never share a
 * shortest round-trip decimal string, so the key is injective on `===`-distinct
 * coordinates.
 */
function nodeKey(p: Position): string {
  const x = p[0] === 0 ? 0 : p[0];
  const y = p[1] === 0 ? 0 : p[1];
  return `${x},${y}`;
}

function fail(code: string, reason: string): AutoOrderFailure {
  return { ok: false, code, reason };
}

/** A leg where start/end and coordinates are reversed, preserving its refs. */
function reverseLeg(leg: RouteLeg): RouteLeg {
  return {
    ...leg,
    start: leg.end,
    end: leg.start,
    direction: leg.direction === "forward" ? "reverse" : "forward",
    coordinates: leg.coordinates.slice().reverse(),
  };
}

/**
 * Validate every leg's structure. Returns a failure message on the first
 * problem, otherwise null. Requires unique non-empty ids, >= 2 finite valid
 * coordinates, and exact start/end ref matching.
 */
function validateLegs(legs: RouteLeg[]): AutoOrderFailure | null {
  const seen = new Set<string>();
  for (const leg of legs) {
    if (typeof leg.id !== "string" || leg.id.length === 0) {
      return fail("missing_leg_id", "A selected leg has no id; nothing was changed.");
    }
    if (seen.has(leg.id)) {
      return fail("duplicate_leg_id", `Duplicate leg id "${leg.id}"; nothing was changed.`);
    }
    seen.add(leg.id);

    const coords = leg.coordinates;
    if (!Array.isArray(coords) || coords.length < 2) {
      return fail("invalid_leg_geometry", `Leg "${leg.id}" has fewer than 2 coordinates.`);
    }
    if (!coords.every(isValidPosition)) {
      return fail("invalid_leg_geometry", `Leg "${leg.id}" contains an invalid coordinate.`);
    }
    const start = coords[0];
    const end = coords[coords.length - 1];
    if (!isValidPosition(leg.start?.coordinate) || !samePosition(leg.start.coordinate, start)) {
      return fail("stale_leg_refs", `Leg "${leg.id}" start ref does not match its first coordinate.`);
    }
    if (!isValidPosition(leg.end?.coordinate) || !samePosition(leg.end.coordinate, end)) {
      return fail("stale_leg_refs", `Leg "${leg.id}" end ref does not match its last coordinate.`);
    }
    if (samePosition(start, end)) {
      return fail("self_loop", `Leg "${leg.id}" starts and ends at the same coordinate (self-loop).`);
    }
  }
  return null;
}

/** Interface for an undirected edge between two endpoint node keys. */
interface Edge {
  aK: string;
  bK: string;
}

/**
 * Exactly order the selected legs of a section into a single fromAnchor→toAnchor
 * simple chain. Purely functional: never mutates the input legs (it reuses the
 * original leg objects when no reversal is needed and returns new reversed
 * objects otherwise). See the module docstring for the full safety contract.
 */
export function autoOrderLegs(
  section: Pick<RouteSection, "legs" | "fromAnchor" | "toAnchor">,
): AutoOrderResult {
  const { legs, fromAnchor, toAnchor } = section;

  if (!fromAnchor || !toAnchor) {
    return fail("missing_anchors", "Both a from-anchor and a to-anchor are required.");
  }
  if (!Array.isArray(legs)) return fail("invalid_legs", "section.legs is missing.");

  if (legs.length === 0) {
    // Anchors present but nothing to order: already consistent, no change.
    return { ok: true, legs: [], reversedCount: 0, changed: false };
  }

  const validation = validateLegs(legs);
  if (validation) return validation;

  const fromKey = nodeKey(fromAnchor.coordinate);
  const toKey = nodeKey(toAnchor.coordinate);
  if (fromKey === toKey) {
    return fail("anchors_same", "The from and to anchors are the same point.");
  }

  // Build an undirected multigraph over leg endpoint coordinates.
  const nodePos = new Map<string, Position>();
  const degree = new Map<string, number>();
  const neighbors = new Map<string, Array<{ key: string; edgeIndex: number }>>();
  const edges: Edge[] = [];

  const bump = (key: string, neighborKey: string, edgeIndex: number): void => {
    degree.set(key, (degree.get(key) ?? 0) + 1);
    const list = neighbors.get(key);
    if (list) list.push({ key: neighborKey, edgeIndex });
    else neighbors.set(key, [{ key: neighborKey, edgeIndex }]);
  };

  for (let i = 0; i < legs.length; i++) {
    const leg = legs[i];
    const aK = nodeKey(leg.start.coordinate);
    const bK = nodeKey(leg.end.coordinate);
    if (aK === bK) {
      return fail("self_loop", `Leg "${leg.id}" starts and ends at the same coordinate (self-loop).`);
    }
    if (!nodePos.has(aK)) nodePos.set(aK, leg.start.coordinate);
    if (!nodePos.has(bK)) nodePos.set(bK, leg.end.coordinate);
    edges.push({ aK, bK });
    bump(aK, bK, i);
    bump(bK, aK, i);
  }

  const totalNodes = nodePos.size;

  // Anchors must be chain-endpoint nodes; a leg-interior anchor is not a node.
  if (!nodePos.has(fromKey) || !nodePos.has(toKey)) {
    return fail(
      "anchor_not_terminal",
      "Each anchor must lie exactly on one end of the chain (not on a leg interior or shared node).",
    );
  }

  // Parallel ambiguity: two edges between the same unordered pair.
  const pairSeen = new Map<string, number>();
  for (let i = 0; i < edges.length; i++) {
    const { aK, bK } = edges[i];
    const pairKey = aK < bK ? `${aK}\u0000${bK}` : `${bK}\u0000${aK}`;
    const prev = pairSeen.get(pairKey);
    if (prev !== undefined) {
      return fail(
        "parallel",
        `Legs "${legs[prev].id}" and "${legs[i].id}" connect the same two points (parallel); ambiguous.`,
      );
    }
    pairSeen.set(pairKey, i);
  }

  // Branch: any node with degree > 2.
  for (const [key, deg] of degree) {
    if (deg > 2) {
      const [lon, lat] = nodePos.get(key) as Position;
      return fail(
        "branch",
        `Branching at (${lon}, ${lat}): a node connects more than 2 legs; ambiguous.`,
      );
    }
  }

  // Connectivity: from the from-anchor, every node must be reachable.
  const reached = new Set<string>();
  const stack = [fromKey];
  while (stack.length > 0) {
    const key = stack.pop() as string;
    if (reached.has(key)) continue;
    reached.add(key);
    for (const n of neighbors.get(key) ?? []) stack.push(n.key);
  }
  if (reached.size !== totalNodes) {
    return fail(
      "disconnected",
      "The selected legs are not all connected by exact shared coordinates.",
    );
  }
  if (!reached.has(toKey)) {
    return fail(
      "disconnected",
      "The to-anchor is not connected to the from-anchor by the selected legs.",
    );
  }

  // Terminal count: a simple path has exactly two degree-1 nodes.
  const terminals = [...degree.entries()].filter(([, deg]) => deg === 1).map(([key]) => key);
  if (terminals.length !== 2) {
    return fail(
      "cycle",
      "The selected legs form a closed loop (no two distinct endpoints); a simple chain is required.",
    );
  }

  // Anchors must be the two distinct chain endpoints (never leg-interior).
  const fromDeg = degree.get(fromKey);
  const toDeg = degree.get(toKey);
  if (fromDeg !== 1 || toDeg !== 1 || fromKey === toKey) {
    return fail(
      "anchor_not_terminal",
      "Each anchor must lie exactly on one end of the chain (not on a leg interior or shared node).",
    );
  }

  // Unique traversal from the from-anchor following degree-1/2 nodes.
  const usedEdge = new Set<number>();
  const order: number[] = [];
  const pathNodes: string[] = [fromKey];
  let cur = fromKey;
  for (let step = 0; step < legs.length; step++) {
    const cands = (neighbors.get(cur) ?? []).filter((e) => !usedEdge.has(e.edgeIndex));
    if (cands.length !== 1) {
      return fail("branch", "Could not find a unique next leg while traversing the chain.");
    }
    const chosen = cands[0];
    usedEdge.add(chosen.edgeIndex);
    order.push(chosen.edgeIndex);
    cur = chosen.key;
    pathNodes.push(cur);
  }
  if (usedEdge.size !== legs.length || order.length !== legs.length) {
    return fail("unexpected", "Failed to consume every selected leg exactly once.");
  }
  if (cur !== toKey) {
    return fail("unexpected", "Traversal did not end at the to-anchor.");
  }

  // Orient each leg forward from the traversal path and count reversals.
  let reversedCount = 0;
  const outLegs: RouteLeg[] = [];
  for (let k = 0; k < order.length; k++) {
    const leg = legs[order[k]];
    const fromPos = nodePos.get(pathNodes[k]) as Position;
    if (samePosition(leg.start.coordinate, fromPos)) {
      outLegs.push(leg); // already oriented along the traversal
    } else {
      outLegs.push(reverseLeg(leg));
      reversedCount += 1;
    }
  }

  // changed = any reordering or any reversal relative to the input.
  let changed = reversedCount > 0;
  for (let i = 0; i < order.length; i++) {
    if (order[i] !== i) changed = true;
  }

  return { ok: true, legs: outLegs, reversedCount, changed };
}
