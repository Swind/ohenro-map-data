import { describe, expect, it } from "vitest";
import type { EditorSource } from "./model";
import {
  addSourceLayers,
  createEditorSourceRegistry,
  editorFillLayerId,
  editorGeoJsonSourceId,
  editorHitboxLayerId,
  editorLineLayerId,
  editorOutlineLayerId,
  editorPoiLayerId,
  layerIdsForSource,
  removeSourceLayers,
  setSourceColor,
  setSourceOpacity,
  setSourceVisibility,
  type EditorSourceRegistry,
} from "./source-layers";
import { ROUTE_ELIGIBLE_LINE_FILTER } from "./line-eligibility";

/** A minimal MapLibre surface with an in-memory layer/source store. */
interface MockMap {
  layers: Set<string>;
  sources: Set<string>;
  layoutProps: Record<string, string>;
  paintProps: Record<string, unknown>;
  layerSpecs: Record<string, { filter?: unknown }>;
  addSource(id: string, spec: unknown): void;
  getSource(id: string): unknown;
  removeSource(id: string): void;
  addLayer(layer: { id: string; filter?: unknown }): void;
  getLayer(id: string): unknown;
  removeLayer(id: string): void;
  setLayoutProperty(id: string, prop: string, value: string): void;
  setPaintProperty(id: string, prop: string, value: unknown): void;
}

function mockMap(): MockMap {
  const layers = new Set<string>();
  const sources = new Set<string>();
  const layoutProps: Record<string, string> = {};
  const paintProps: Record<string, unknown> = {};
  const layerSpecs: Record<string, { filter?: unknown }> = {};
  return {
    layers,
    sources,
    layoutProps,
    paintProps,
    layerSpecs,
    addSource(id) {
      sources.add(id);
    },
    getSource(id) {
      return sources.has(id) ? {} : undefined;
    },
    removeSource(id) {
      sources.delete(id);
    },
    addLayer(layer) {
      layers.add(layer.id);
      layerSpecs[layer.id] = { filter: layer.filter };
      const vis = (layer as { layout?: { visibility?: string } }).layout?.visibility;
      if (vis) layoutProps[`${layer.id}:visibility`] = vis;
    },
    getLayer(id) {
      return layers.has(id) ? {} : undefined;
    },
    removeLayer(id) {
      layers.delete(id);
    },
    setLayoutProperty(id, prop, value) {
      layoutProps[`${id}:${prop}`] = value;
    },
    setPaintProperty(id, prop, value) {
      paintProps[`${id}:${prop}`] = value;
    },
  };
}

function source(id: string, visible = true, selectable = true): EditorSource {
  return {
    id,
    name: `source ${id}`,
    sha256: "aa",
    format: "geojson",
    color: "#ff0000",
    visible,
    selectable,
    data: { type: "FeatureCollection", features: [] },
    importWarnings: [],
  };
}

describe("stable layer id helpers", () => {
  it("prefixes every runtime id with editor-", () => {
    const ids = layerIdsForSource("src-1");
    expect(ids.sourceId).toBe("editor-src-src-1");
    expect(ids.fill).toBe("editor-src-1-fill");
    expect(ids.outline).toBe("editor-src-1-outline");
    expect(ids.line).toBe("editor-src-1-line");
    expect(ids.hitbox).toBe("editor-src-1-hitbox");
    expect(ids.poi).toBe("editor-src-1-poi");
  });

  it("keeps all five layer ids distinct per source", () => {
    const ids = layerIdsForSource("a");
    const all = [ids.fill, ids.outline, ids.line, ids.hitbox, ids.poi];
    expect(new Set(all).size).toBe(5);
  });

  it("produces deterministic ids across calls", () => {
    expect(layerIdsForSource("x")).toEqual(layerIdsForSource("x"));
    expect(editorGeoJsonSourceId("x")).toBe("editor-src-x");
    expect(editorFillLayerId("x")).toBe("editor-x-fill");
    expect(editorOutlineLayerId("x")).toBe("editor-x-outline");
    expect(editorLineLayerId("x")).toBe("editor-x-line");
    expect(editorHitboxLayerId("x")).toBe("editor-x-hitbox");
    expect(editorPoiLayerId("x")).toBe("editor-x-poi");
  });
});

describe("add/remove source layers", () => {
  it("adds one GeoJSON source and five editor-prefixed layers", () => {
    const map = mockMap();
    const registry = createEditorSourceRegistry();
    const ids = addSourceLayers(map, source("s1"), registry);

    expect(map.sources).toContain("editor-src-s1");
    for (const layerId of [ids.fill, ids.outline, ids.line, ids.hitbox, ids.poi]) {
      expect(map.layers).toContain(layerId);
    }
    expect(registry.bySourceId["s1"]).toEqual(ids);
  });

  it("initialises visibility from the source", () => {
    const map = mockMap();
    const registry = createEditorSourceRegistry();
    addSourceLayers(map, source("s1", true), registry);
    expect(map.layoutProps["editor-s1-line:visibility"]).toBe("visible");

    const map2 = mockMap();
    addSourceLayers(map2, source("s2", false), registry);
    expect(map2.layoutProps["editor-s2-line:visibility"]).toBe("none");
  });

  it("removes layers and source and unregisters", () => {
    const map = mockMap();
    const registry = createEditorSourceRegistry();
    const ids = addSourceLayers(map, source("s1"), registry);

    removeSourceLayers(map, "s1", registry);
    for (const layerId of [ids.fill, ids.outline, ids.line, ids.hitbox, ids.poi]) {
      expect(map.layers.has(layerId)).toBe(false);
    }
    expect(map.sources.has("editor-src-s1")).toBe(false);
    expect(registry.bySourceId["s1"]).toBeUndefined();
  });

  it("is a no-op when removing an unregistered source", () => {
    const map = mockMap();
    const registry = createEditorSourceRegistry();
    expect(() => removeSourceLayers(map, "ghost", registry)).not.toThrow();
  });
});

describe("addSourceLayers transactional rollback", () => {
  it("removes every layer/source and leaves no registry entry when an addLayer throws midway", () => {
    const map = mockMap();
    // Fail on the third layer (line), after source + fill + outline succeeded.
    let calls = 0;
    const origAddLayer = map.addLayer.bind(map);
    map.addLayer = (layer) => {
      calls += 1;
      if (calls === 3) throw new Error("boom");
      origAddLayer(layer);
    };

    const registry = createEditorSourceRegistry();
    expect(() => addSourceLayers(map, source("s1"), registry)).toThrow("boom");

    // No layer, source, or registry entry survives the partial install.
    expect(map.sources.size).toBe(0);
    expect(map.layers.size).toBe(0);
    expect(registry.bySourceId["s1"]).toBeUndefined();
  });

  it("cleans up even when addSource itself throws", () => {
    const map = mockMap();
    map.addSource = () => {
      throw new Error("source boom");
    };

    const registry = createEditorSourceRegistry();
    expect(() => addSourceLayers(map, source("s1"), registry)).toThrow("source boom");
    expect(map.sources.size).toBe(0);
    expect(map.layers.size).toBe(0);
    expect(registry.bySourceId["s1"]).toBeUndefined();
  });

  it("leaves a pre-existing matching source/layers untouched when addSource id-collides", () => {
    const map = mockMap();
    const registry = createEditorSourceRegistry();
    const ids = layerIdsForSource("s1");
    registry.bySourceId["s1"] = ids;
    const allLayers = [ids.fill, ids.outline, ids.line, ids.hitbox, ids.poi];

    // Simulate an already-installed identical source (e.g. from a prior
    // successful import or an externally added source). Pre-seed all five
    // layers and the GeoJSON source as they would already exist.
    map.addSource(ids.sourceId, { type: "geojson" });
    for (const layerId of allLayers) map.addLayer({ id: layerId });

    // Re-adding the same source id throws (MapLibre rejects duplicate ids),
    // after the source step so nothing from this invocation is installed.
    map.addSource = (id) => {
      if (map.sources.has(id)) throw new Error(`Source "${id}" already exists`);
    };

    expect(() => addSourceLayers(map, source("s1"), registry)).toThrow(
      `Source "${ids.sourceId}" already exists`,
    );

    // Every pre-existing resource must survive rollback byte-for-byte.
    expect(map.sources.has(ids.sourceId)).toBe(true);
    for (const layerId of allLayers) {
      expect(map.layers.has(layerId)).toBe(true);
    }
    expect(map.sources.size).toBe(1);
    expect(map.layers.size).toBe(5);
    expect(registry.bySourceId["s1"]).toBe(ids);
  });
});

describe("visibility / color / opacity updates", () => {
  it("toggles visibility across all runtime layers", () => {
    const map = mockMap();
    const registry = createEditorSourceRegistry();
    const ids = addSourceLayers(map, source("s1"), registry);

    setSourceVisibility(map, "s1", registry, false);
    for (const layerId of [ids.fill, ids.outline, ids.line, ids.hitbox, ids.poi]) {
      expect(map.layoutProps[`${layerId}:visibility`]).toBe("none");
    }

    setSourceVisibility(map, "s1", registry, true);
    for (const layerId of [ids.fill, ids.outline, ids.line, ids.hitbox, ids.poi]) {
      expect(map.layoutProps[`${layerId}:visibility`]).toBe("visible");
    }
  });

  it("recolours display layers but never the hitbox", () => {
    const map = mockMap();
    const registry = createEditorSourceRegistry();
    const ids = addSourceLayers(map, source("s1"), registry);

    setSourceColor(map, "s1", registry, "#00ff00");
    expect(map.paintProps[`${ids.fill}:fill-color`]).toBe("#00ff00");
    expect(map.paintProps[`${ids.outline}:line-color`]).toBe("#00ff00");
    expect(map.paintProps[`${ids.line}:line-color`]).toBe("#00ff00");
    expect(map.paintProps[`${ids.poi}:circle-color`]).toBe("#00ff00");
    expect(map.paintProps[`${ids.hitbox}:line-color`]).toBeUndefined();
  });

  it("sets opacity on display layers and keeps the hitbox transparent", () => {
    const map = mockMap();
    const registry = createEditorSourceRegistry();
    const ids = addSourceLayers(map, source("s1"), registry);

    setSourceOpacity(map, "s1", registry, 0.5);
    expect(map.paintProps[`${ids.line}:line-opacity`]).toBe(0.5);
    expect(map.paintProps[`${ids.poi}:circle-opacity`]).toBe(0.5);
    expect(map.paintProps[`${ids.fill}:fill-opacity`]).toBeCloseTo(0.125);
    expect(map.paintProps[`${ids.hitbox}:line-opacity`]).toBeUndefined();
  });

  it("ignores updates for unregistered sources", () => {
    const map = mockMap();
    const registry: EditorSourceRegistry = { bySourceId: {} };
    expect(() => {
      setSourceVisibility(map, "ghost", registry, false);
      setSourceColor(map, "ghost", registry, "#000000");
      setSourceOpacity(map, "ghost", registry, 0);
    }).not.toThrow();
  });
});

describe("hitbox eligibility filter", () => {
  it("uses the route-eligibility filter for the hitbox but not the line visual", () => {
    const map = mockMap();
    const registry = createEditorSourceRegistry();
    addSourceLayers(map, source("s1"), registry);

    expect(map.layerSpecs[editorHitboxLayerId("s1")].filter).toEqual(ROUTE_ELIGIBLE_LINE_FILTER);
    // The display line visual keeps a separate (unfiltered-by-eligibility) filter
    // so diagnostic lines remain visible as context even though they are not
    // selectable/hover-eligible.
    expect(map.layerSpecs[editorLineLayerId("s1")].filter).not.toEqual(ROUTE_ELIGIBLE_LINE_FILTER);
  });
});
