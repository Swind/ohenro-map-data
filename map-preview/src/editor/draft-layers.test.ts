import { describe, expect, it } from "vitest";
import type { GeoJSONFeatureCollection, Position, RouteLeg, RouteSection } from "./model";
import type { SectionSummary } from "./validation";
import {
  addDraftLayers,
  buildDraftData,
  DRAFT_GAP_LAYER_ID,
  DRAFT_OFFSET_LAYER_ID,
  DRAFT_POINT_LAYER_ID,
  DRAFT_ROUTE_LAYER_ID,
  DRAFT_SOURCE_ID,
  updateDraft,
  type DraftMap,
} from "./draft-layers";

const leg: RouteLeg = {
  id: "leg1",
  sourceId: "s",
  featureId: "f",
  partIndex: 0,
  start: {
    sourceId: "s",
    featureId: "f",
    partIndex: 0,
    segmentIndex: 0,
    fraction: 0,
    coordinate: [134, 33],
  },
  end: {
    sourceId: "s",
    featureId: "f",
    partIndex: 0,
    segmentIndex: 0,
    fraction: 1,
    coordinate: [134, 34],
  },
  direction: "forward",
  coordinates: [
    [134, 33],
    [134, 34],
  ],
  lengthM: 1000,
};

const section: RouteSection = {
  id: "S",
  fromPoi: { sourceId: "s", featureId: "p0", coordinate: [134, 32.9] },
  toPoi: { sourceId: "s", featureId: "p1", coordinate: [134, 34.1] },
  fromAnchor: leg.start,
  toAnchor: leg.end,
  waypoints: [],
  legs: [leg],
};

const summary: SectionSummary = {
  sectionId: "S",
  status: "continuous",
  legCount: 1,
  routeLengthM: 1000,
  totalGapM: 100,
  gaps: [{ betweenLegIndex: 0, from: [134, 34], to: [134, 34.1], distanceM: 100 }],
  issues: [],
};

function kinds(data: GeoJSONFeatureCollection): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const f of data.features) {
    const kind = (f.properties as { draftKind?: string })?.draftKind ?? "?";
    counts[kind] = (counts[kind] ?? 0) + 1;
  }
  return counts;
}

function mockDraftMap(): {
  sources: Set<string>;
  layers: Set<string>;
  get data(): GeoJSONFeatureCollection | null;
  map: DraftMap;
} {
  const sources = new Set<string>();
  const layers = new Set<string>();
  let data: GeoJSONFeatureCollection | null = null;
  return {
    sources,
    layers,
    get data() {
      return data;
    },
    map: {
      addSource(id) {
        sources.add(id);
      },
      getSource(id) {
        return sources.has(id) ? { setData: (d: GeoJSONFeatureCollection) => { data = d; } } : undefined;
      },
      addLayer(layer) {
        layers.add((layer as { id: string }).id);
      },
    },
  };
}

describe("buildDraftData", () => {
  it("returns an empty collection for a null section", () => {
    const data = buildDraftData(null, null);
    expect(data.type).toBe("FeatureCollection");
    expect(data.features).toHaveLength(0);
  });

  it("emits route legs, POIs, anchors, offsets and gaps with draftKind markers", () => {
    const data = buildDraftData(section, summary);
    const counts = kinds(data);
    expect(counts.route).toBe(1); // one leg
    expect(counts.poi).toBe(2); // fromPoi + toPoi
    expect(counts.anchor).toBe(2); // fromAnchor + toAnchor
    expect(counts.offset).toBe(2); // fromPoi->fromAnchor, toPoi->toAnchor
    expect(counts.gap).toBe(1); // one exact gap
  });

  it("skips offsets when a POI or its anchor is missing", () => {
    const partial: RouteSection = { ...section, fromPoi: null };
    const data = buildDraftData(partial, summary);
    const counts = kinds(data);
    expect(counts.poi).toBe(1);
    expect(counts.offset).toBe(1); // only the toPoi->toAnchor pair survives
  });

  it("skips legs with fewer than two coordinates", () => {
    const single = [{ ...leg, coordinates: [[134, 33]] as Position[] }];
    const data = buildDraftData({ ...section, legs: single }, null);
    expect(kinds(data).route).toBeUndefined();
  });

  it("marks offsets and gaps as visualisation features in the draft only", () => {
    const data = buildDraftData(section, summary);
    for (const f of data.features) {
      const kind = (f.properties as { draftKind?: string }).draftKind;
      if (kind === "gap" || kind === "offset") {
        // These must never carry route semantics.
        expect(f.properties).not.toHaveProperty("legIndex");
      }
    }
  });
});

describe("addDraftLayers / updateDraft", () => {
  it("registers the shared source and four editor-prefixed layers", () => {
    const { sources, layers, map } = mockDraftMap();
    addDraftLayers(map);
    expect(sources).toContain(DRAFT_SOURCE_ID);
    expect(layers).toEqual(
      new Set([
        DRAFT_OFFSET_LAYER_ID,
        DRAFT_ROUTE_LAYER_ID,
        DRAFT_GAP_LAYER_ID,
        DRAFT_POINT_LAYER_ID,
      ]),
    );
  });

  it("pushes draft data through setData on the shared source", () => {
    const mock = mockDraftMap();
    addDraftLayers(mock.map);
    updateDraft(mock.map, section, summary);
    expect(mock.data).not.toBeNull();
    expect(mock.data!.features.length).toBeGreaterThan(0);
  });

  it("is a no-op when the draft source is absent", () => {
    const mock = mockDraftMap();
    expect(() => updateDraft(mock.map, section, summary)).not.toThrow();
    expect(mock.data).toBeNull();
  });
});