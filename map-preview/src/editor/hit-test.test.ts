import { describe, expect, it } from "vitest";
import type { EditorSource, GeoJSONFeature, GeoJSONGeometry, Position } from "./model";
import { distanceM } from "./geometry";
import { editorHitboxLayerId, editorPoiLayerId, layerIdsForSource } from "./source-layers";
import {
  hitTestEditor,
  type CandidateFeature,
  type HitTestMap,
} from "./hit-test";

/** A straight vertical (meridian) line part, matching geometry.test.ts. */
const V: Position[] = [
  [134, 33],
  [134, 33.5],
  [134, 34],
  [134, 34.5],
];

function feature(
  id: string | number,
  geometry: GeoJSONFeature["geometry"],
  properties: Record<string, unknown> = {},
): GeoJSONFeature {
  return { type: "Feature", id, geometry, properties };
}

function source(id: string, features: GeoJSONFeature[], opts?: Partial<EditorSource>): EditorSource {
  return {
    id,
    name: id,
    sha256: "aa",
    format: "geojson",
    color: "#ff0000",
    visible: true,
    selectable: true,
    data: { type: "FeatureCollection", features },
    importWarnings: [],
    ...opts,
  };
}

interface MockHitMap extends HitTestMap {
  queriedLayers: string[];
  candidates: CandidateFeature[];
}

/** Minimal queryRenderedFeatures mock: no WebGL, returns the given candidates. */
function mockMap(candidates: CandidateFeature[]): MockHitMap {
  const queriedLayers: string[] = [];
  return {
    candidates,
    queriedLayers,
    project: (lngLat) => ({ x: lngLat[0], y: lngLat[1] }),
    queryRenderedFeatures: (_point, options) => {
      queriedLayers.push(...(options?.layers ?? []));
      return candidates;
    },
  };
}

const lineCandidate = (sourceId: string, featureId: string | number): CandidateFeature => ({
  id: featureId,
  layer: { id: editorHitboxLayerId(sourceId) },
});
const poiCandidate = (sourceId: string, featureId: string | number): CandidateFeature => ({
  id: featureId,
  layer: { id: editorPoiLayerId(sourceId) },
});

/** Build a registry for the given source ids using their real layer ids. */
function registryFor(...sourceIds: string[]): { bySourceId: Record<string, import("./source-layers").SourceLayerIds> } {
  const bySourceId: Record<string, import("./source-layers").SourceLayerIds> = {};
  for (const id of sourceIds) bySourceId[id] = layerIdsForSource(id);
  return { bySourceId };
}

describe("authoritative line resolution", () => {
  it("resolves a hitbox candidate to the nearest authoritative line point", () => {
    const src = source("s1", [feature("f1", { type: "LineString", coordinates: V })]);
    const map = mockMap([lineCandidate("s1", "f1")]);
    const registry = registryFor("s1");

    const hits = hitTestEditor(map, [134, 33.25], [src], registry);
    expect(hits).toHaveLength(1);
    const hit = hits[0];
    expect(hit.kind).toBe("line");
    if (hit.kind !== "line") return;
    expect(hit.sourceId).toBe("s1");
    expect(hit.featureId).toBe("f1");
    expect(hit.partIndex).toBe(0);
    expect(hit.segmentIndex).toBe(0);
    expect(hit.fraction).toBeCloseTo(0.5, 9);
    expect(hit.coordinate[0]).toBeCloseTo(134, 9);
    expect(hit.coordinate[1]).toBeCloseTo(33.25, 9);
    expect(hit.distanceM).toBeCloseTo(0, 9);
  });

  it("returns only the single nearest part of a MultiLineString", () => {
    const geom: GeoJSONGeometry = {
      type: "MultiLineString",
      // part 0 is far away (lon 135); part 1 passes through lat 33.1.
      coordinates: [
        [[135, 33], [135, 34]],
        [[134, 33], [134, 33.6]],
      ],
    };
    const src = source("s1", [feature(7, geom)]);
    const map = mockMap([lineCandidate("s1", 7)]);
    const registry = registryFor("s1");

    const hits = hitTestEditor(map, [134, 33.1], [src], registry);
    // One rendered part was hit -> a single hit for the nearest part only,
    // never every distant part (no false ambiguity).
    expect(hits).toHaveLength(1);
    expect(hits[0].kind).toBe("line");
    if (hits[0].kind !== "line") return;
    expect(hits[0].featureId).toBe("7");
    // part 1 contains 33.1 (on the line) -> nearer than part 0 at lon 135.
    expect(hits[0].partIndex).toBe(1);
    expect(hits[0].segmentIndex).toBe(0);
    expect(hits[0].fraction).toBeCloseTo(0.1 / 0.6, 9);
    expect(hits[0].distanceM).toBeCloseTo(0, 9);
  });

  it("mathematically tied MultiLineString parts keep the lowest part index", () => {
    // Two horizontal parts equidistant from the click (part 0 at lat 33,
    // part 1 at lat 34, click at lat 33.5). The projected distances are
    // mathematically equal but differ by a floating-point epsilon, so the
    // distance tolerance must keep the lowest part index deterministic.
    const geom: GeoJSONGeometry = {
      type: "MultiLineString",
      coordinates: [
        [[134, 33], [135, 33]],
        [[134, 34], [135, 34]],
      ],
    };
    const src = source("s1", [feature(7, geom)]);
    const map = mockMap([lineCandidate("s1", 7)]);
    const registry = registryFor("s1");

    const hits = hitTestEditor(map, [134.5, 33.5], [src], registry);
    expect(hits).toHaveLength(1);
    expect(hits[0].kind).toBe("line");
    if (hits[0].kind !== "line") return;
    expect(hits[0].partIndex).toBe(0);
  });
});

describe("authoritative diagnostic line rejection", () => {
  it("drops a gap diagnostic line even when the rendered filter would not", () => {
    const src = source("s1", [
      feature("gap1", { type: "LineString", coordinates: V }, {
        kind: "gap",
        type: "gap",
        visualization_only: true,
      }),
    ]);
    const map = mockMap([lineCandidate("s1", "gap1")]);
    const registry = registryFor("s1");

    const hits = hitTestEditor(map, [134, 33.5], [src], registry);
    expect(hits).toEqual([]);
  });

  it("drops a poi_offset diagnostic line", () => {
    const src = source("s1", [
      feature("off1", { type: "LineString", coordinates: V }, {
        kind: "poi_offset",
        type: "poi_offset",
        review_visualization_only: true,
      }),
    ]);
    const map = mockMap([lineCandidate("s1", "off1")]);
    const registry = registryFor("s1");

    const hits = hitTestEditor(map, [134, 33.5], [src], registry);
    expect(hits).toEqual([]);
  });

  it("keeps an ordinary eligible line", () => {
    const src = source("s1", [feature("ok", { type: "LineString", coordinates: V })]);
    const map = mockMap([lineCandidate("s1", "ok")]);
    const registry = registryFor("s1");

    const hits = hitTestEditor(map, [134, 33.5], [src], registry);
    expect(hits).toHaveLength(1);
  });
});

describe("authoritative POI resolution", () => {
  it("resolves a POI candidate to the authoritative point ref", () => {
    const src = source("s1", [feature("p1", { type: "Point", coordinates: [134, 33] })]);
    const map = mockMap([poiCandidate("s1", "p1")]);
    const registry = registryFor("s1");

    const hits = hitTestEditor(map, [134.001, 33], [src], registry);
    expect(hits).toHaveLength(1);
    expect(hits[0]).toMatchObject({
      kind: "poi",
      sourceId: "s1",
      featureId: "p1",
      coordinate: [134, 33],
    });
    if (hits[0].kind !== "poi") return;
    expect(hits[0].distanceM).toBeCloseTo(distanceM([134.001, 33], [134, 33]), 9);
  });

  it("returns only the nearest point of a MultiPoint feature", () => {
    const geom: GeoJSONGeometry = {
      type: "MultiPoint",
      coordinates: [[134, 33], [134, 33.2], [134, 34]],
    };
    const src = source("s1", [feature("mp", geom)]);
    const map = mockMap([poiCandidate("s1", "mp")]);
    const registry = registryFor("s1");

    const hits = hitTestEditor(map, [134, 33.21], [src], registry);
    // One rendered point was hit -> a single nearest point only.
    expect(hits).toHaveLength(1);
    expect(hits[0].kind).toBe("poi");
    if (hits[0].kind !== "poi") return;
    expect(hits[0].featureId).toBe("mp");
    expect(hits[0].coordinate).toEqual([134, 33.2]);
  });

  it("mathematically tied MultiPoint coordinates keep the lowest index", () => {
    // Two points equidistant from the click (lat 33.1 and 33.3, click at
    // 33.2). The projected distances are mathematically equal but differ by a
    // floating-point epsilon; the tolerance keeps index 0 deterministic.
    const geom: GeoJSONGeometry = {
      type: "MultiPoint",
      coordinates: [[134, 33.1], [134, 33.3]],
    };
    const src = source("s1", [feature("mp", geom)]);
    const map = mockMap([poiCandidate("s1", "mp")]);
    const registry = registryFor("s1");

    const hits = hitTestEditor(map, [134, 33.2], [src], registry);
    expect(hits).toHaveLength(1);
    expect(hits[0].kind).toBe("poi");
    if (hits[0].kind !== "poi") return;
    expect(hits[0].coordinate).toEqual([134, 33.1]);
  });
});

describe("GeometryCollection contents", () => {
  it("yields both line and POI hits from selectable contents only", () => {
    const geom: GeoJSONGeometry = {
      type: "GeometryCollection",
      geometries: [
        { type: "LineString", coordinates: V },
        { type: "Point", coordinates: [134, 34] },
        { type: "Polygon", coordinates: [[[134, 30], [134.5, 30], [134.5, 30.5], [134, 30]]] },
      ],
    };
    const src = source("s1", [feature("gc1", geom)]);
    // Same feature discovered via BOTH the hitbox and POI layers.
    const map = mockMap([lineCandidate("s1", "gc1"), poiCandidate("s1", "gc1")]);
    const registry = registryFor("s1");

    const hits = hitTestEditor(map, [134.01, 34], [src], registry);
    // Line part (V) + POI point -> 2 hits, deduplicated across the two layers.
    expect(hits).toHaveLength(2);
    expect(hits.filter((h) => h.kind === "line")).toHaveLength(1);
    expect(hits.filter((h) => h.kind === "poi")).toHaveLength(1);
    // Polygon contents are context and never selected.
    expect(hits.some((h) => h.coordinate[1] < 31)).toBe(false);
  });

  it("ignores a pure-polygon candidate", () => {
    const src = source("s1", [
      feature("poly", {
        type: "Polygon",
        coordinates: [[[134, 30], [134.5, 30], [134.5, 30.5], [134, 30]]],
      }),
    ]);
    const map = mockMap([lineCandidate("s1", "poly"), poiCandidate("s1", "poly")]);
    const registry = registryFor("s1");
    expect(hitTestEditor(map, [134.2, 30.2], [src], registry)).toEqual([]);
  });
});

describe("candidate layer kind isolation", () => {
  it("a hitbox-only candidate yields line hits, never POI hits", () => {
    const geom: GeoJSONGeometry = {
      type: "GeometryCollection",
      geometries: [
        { type: "LineString", coordinates: V },
        { type: "Point", coordinates: [134, 34] },
      ],
    };
    const src = source("s1", [feature("gc", geom)]);
    // Discovered ONLY via the line hitbox layer.
    const map = mockMap([lineCandidate("s1", "gc")]);
    const registry = registryFor("s1");

    const hits = hitTestEditor(map, [134.01, 34], [src], registry);
    expect(hits).toHaveLength(1);
    expect(hits[0].kind).toBe("line");
    if (hits[0].kind !== "line") return;
    expect(hits[0].featureId).toBe("gc");
  });

  it("a POI-only candidate yields POI hits, never line hits", () => {
    const geom: GeoJSONGeometry = {
      type: "GeometryCollection",
      geometries: [
        { type: "LineString", coordinates: V },
        { type: "Point", coordinates: [134, 34] },
      ],
    };
    const src = source("s1", [feature("gc", geom)]);
    // Discovered ONLY via the POI layer.
    const map = mockMap([poiCandidate("s1", "gc")]);
    const registry = registryFor("s1");

    const hits = hitTestEditor(map, [134.01, 34], [src], registry);
    expect(hits).toHaveLength(1);
    expect(hits[0].kind).toBe("poi");
    if (hits[0].kind !== "poi") return;
    expect(hits[0].featureId).toBe("gc");
  });

  it("keeps overlap across distinct features of the same source", () => {
    const src = source("s1", [
      feature("l1", { type: "LineString", coordinates: [[134, 33], [134, 34]] }),
      feature("l2", { type: "LineString", coordinates: [[135, 33], [135, 34]] }),
    ]);
    const map = mockMap([lineCandidate("s1", "l2"), lineCandidate("s1", "l1")]);
    const registry = registryFor("s1");

    const hits = hitTestEditor(map, [134, 33.5], [src], registry);
    // Both are distinct authoritative features -> both reported, nearest first.
    expect(hits).toHaveLength(2);
    expect(hits.every((h) => h.kind === "line")).toBe(true);
    expect(hits.map((h) => h.featureId)).toEqual(["l1", "l2"]);
  });

  it("keeps overlap across distinct sources", () => {
    const a = source("src-a", [feature("a1", { type: "Point", coordinates: [134, 33.5] })]);
    const b = source("src-b", [feature("b1", { type: "Point", coordinates: [135, 33.5] })]);
    const map = mockMap([poiCandidate("src-b", "b1"), poiCandidate("src-a", "a1")]);
    const registry = registryFor("src-a", "src-b");

    const hits = hitTestEditor(map, [134, 33.5], [a, b], registry);
    expect(hits).toHaveLength(2);
    expect(hits.map((h) => h.sourceId)).toEqual(["src-a", "src-b"]);
  });
});

describe("numeric vs string feature ids", () => {
  it("resolves both consistently without cross-matching", () => {
    const numSrc = source("nums", [feature(123, { type: "Point", coordinates: [134, 33] })]);
    const strSrc = source("strs", [feature("123", { type: "Point", coordinates: [134, 34] })]);
    const registry = registryFor("nums", "strs");

    // Number id candidate resolves to the numeric source.
    const map1 = mockMap([poiCandidate("nums", 123)]);
    const hits1 = hitTestEditor(map1, [134, 33], [numSrc, strSrc], registry);
    expect(hits1).toHaveLength(1);
    expect(hits1[0].featureId).toBe("123"); // string form in the ref
    expect(hits1[0].sourceId).toBe("nums");

    // String id candidate resolves to the string source.
    const map2 = mockMap([poiCandidate("strs", "123")]);
    const hits2 = hitTestEditor(map2, [134, 34], [numSrc, strSrc], registry);
    expect(hits2).toHaveLength(1);
    expect(hits2[0].sourceId).toBe("strs");
  });

  it("drops a candidate whose id matches no authoritative feature", () => {
    const src = source("s1", [feature("real", { type: "Point", coordinates: [134, 33] })]);
    const map = mockMap([poiCandidate("s1", "missing")]);
    const registry = registryFor("s1");
    expect(hitTestEditor(map, [134, 33], [src], registry)).toEqual([]);
  });
});

describe("candidate id resolution (properties.id vs candidate.id)", () => {
  it("resolves a POI via the MapLibre numeric internal id plus stable properties.id", () => {
    // MapLibre reports a numeric internal feature id (0) but the stable
    // rendered properties.id carries the authoritative Feature.id ("temple-001").
    const src = source("s1", [feature("temple-001", { type: "Point", coordinates: [134, 33] })]);
    const candidate: CandidateFeature = {
      id: 0,
      properties: { id: "temple-001" },
      layer: { id: editorPoiLayerId("s1") },
    };
    const map = mockMap([candidate]);
    const registry = registryFor("s1");

    const hits = hitTestEditor(map, [134, 33], [src], registry);
    expect(hits).toHaveLength(1);
    expect(hits[0]).toMatchObject({ kind: "poi", sourceId: "s1", featureId: "temple-001" });
  });

  it("resolves a numeric authoritative Feature.id via properties.id", () => {
    const src = source("s1", [feature(42, { type: "Point", coordinates: [134, 33] })]);
    const candidate: CandidateFeature = {
      id: 0,
      properties: { id: 42 },
      layer: { id: editorPoiLayerId("s1") },
    };
    const map = mockMap([candidate]);
    const registry = registryFor("s1");

    const hits = hitTestEditor(map, [134, 33], [src], registry);
    expect(hits).toHaveLength(1);
    expect(hits[0]).toMatchObject({ kind: "poi", sourceId: "s1", featureId: "42" });
  });

  it("falls back to candidate.id when properties.id is stale/unmatched", () => {
    // properties.id does not match any authoritative feature, but candidate.id
    // does; resolution must fall back and still hit.
    const src = source("s1", [feature("temple-001", { type: "Point", coordinates: [134, 33] })]);
    const candidate: CandidateFeature = {
      id: "temple-001",
      properties: { id: "stale-value" },
      layer: { id: editorPoiLayerId("s1") },
    };
    const map = mockMap([candidate]);
    const registry = registryFor("s1");

    const hits = hitTestEditor(map, [134, 33], [src], registry);
    expect(hits).toHaveLength(1);
    expect(hits[0]).toMatchObject({ kind: "poi", sourceId: "s1", featureId: "temple-001" });
  });

  it("prefers properties.id over a conflicting candidate.id", () => {
    // properties.id matches an authoritative feature while candidate.id matches
    // none; the stable property wins.
    const src = source("s1", [feature("temple-001", { type: "Point", coordinates: [134, 33] })]);
    const candidate: CandidateFeature = {
      id: 999,
      properties: { id: "temple-001" },
      layer: { id: editorPoiLayerId("s1") },
    };
    const map = mockMap([candidate]);
    const registry = registryFor("s1");

    const hits = hitTestEditor(map, [134, 33], [src], registry);
    expect(hits).toHaveLength(1);
    expect(hits[0]).toMatchObject({ kind: "poi", sourceId: "s1", featureId: "temple-001" });
  });

  it("does not accept arbitrary property names, only properties.id", () => {
    const src = source("s1", [feature("temple-001", { type: "Point", coordinates: [134, 33] })]);
    const candidate: CandidateFeature = {
      id: 0,
      properties: { name: "temple-001" },
      layer: { id: editorPoiLayerId("s1") },
    };
    const map = mockMap([candidate]);
    const registry = registryFor("s1");

    // No id or properties.id that matches -> candidate is dropped.
    expect(hitTestEditor(map, [134, 33], [src], registry)).toEqual([]);
  });

  it("drops an unresolved candidate with neither properties.id nor candidate.id matching", () => {
    const src = source("s1", [feature("temple-001", { type: "Point", coordinates: [134, 33] })]);
    const candidate: CandidateFeature = {
      id: 0,
      properties: { id: "other-temple" },
      layer: { id: editorPoiLayerId("s1") },
    };
    const map = mockMap([candidate]);
    const registry = registryFor("s1");

    expect(hitTestEditor(map, [134, 33], [src], registry)).toEqual([]);
  });
});

describe("candidate discovery scope and ordering", () => {
  it("queries only hitbox + POI layers of visible, selectable sources", () => {
    const visible = source("vis", [feature("a", { type: "Point", coordinates: [134, 33] })]);
    const hidden = source("hid", [feature("b", { type: "Point", coordinates: [134, 34] })], {
      visible: false,
    });
    const context = source("ctx", [feature("c", { type: "Point", coordinates: [134, 35] })], {
      selectable: false,
    });
    const unregistered = source("unreg", [feature("d", { type: "Point", coordinates: [134, 36] })]);
    const registry = registryFor("vis", "hid", "ctx");

    const map = mockMap([]);
    hitTestEditor(map, [134, 33], [visible, hidden, context, unregistered], registry);
    expect(map.queriedLayers).toEqual([
      editorHitboxLayerId("vis"),
      editorPoiLayerId("vis"),
    ]);
  });

  it("returns an empty array when no visible+selectable source is registered", () => {
    const map = mockMap([poiCandidate("s1", "a")]);
    const registry = { bySourceId: {} };
    expect(hitTestEditor(map, [134, 33], [], registry)).toEqual([]);
  });

  it("orders overlapping candidates by distance, then stable refs", () => {
    // Two POIs on the same source at different distances from the click.
    const src = source("s1", [
      feature("near", { type: "Point", coordinates: [134, 33] }),
      feature("far", { type: "Point", coordinates: [134, 33.01] }),
    ]);
    const map = mockMap([poiCandidate("s1", "far"), poiCandidate("s1", "near")]);
    const registry = registryFor("s1");

    const hits = hitTestEditor(map, [134, 33], [src], registry);
    expect(hits).toHaveLength(2);
    expect(hits.map((h) => h.featureId)).toEqual(["near", "far"]);
    expect(hits[0].distanceM).toBeLessThan(hits[1].distanceM);
  });

  it("breaks distance ties deterministically by source/feature id", () => {
    // Same distance (identical coordinate), different feature ids.
    const a = source("src-a", [feature("zz", { type: "Point", coordinates: [134, 33] })]);
    const b = source("src-b", [feature("aa", { type: "Point", coordinates: [134, 33] })]);
    const registry = registryFor("src-a", "src-b");
    const map = mockMap([
      poiCandidate("src-b", "aa"),
      poiCandidate("src-a", "zz"),
    ]);
    const hits = hitTestEditor(map, [134, 33], [a, b], registry);
    expect(hits).toHaveLength(2);
    expect(hits.map((h) => `${h.sourceId}:${h.featureId}`)).toEqual([
      "src-a:zz",
      "src-b:aa",
    ]);
    expect(hits[0].distanceM).toBe(hits[1].distanceM);
  });
});