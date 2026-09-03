import { describe, expect, it } from "vitest";
import type { EditorSource, GeoJSONFeature, GeoJSONFeatureCollection, GeoJSONGeometry } from "./model";
import type { LineHit, PoiHit } from "./hit-test";
import {
  addHoverLayers,
  buildHoverData,
  HOVER_LINE_LAYER_ID,
  HOVER_POINT_LAYER_ID,
  HOVER_SOURCE_ID,
  updateHover,
  type HoverMap,
} from "./hover-layers";

function feature(id: string | number, geometry: GeoJSONGeometry, properties: Record<string, unknown> = {}): GeoJSONFeature {
  return { type: "Feature", id, geometry, properties };
}

function source(id: string, features: GeoJSONFeature[]): EditorSource {
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
  };
}

const lineHit: LineHit = {
  kind: "line",
  sourceId: "s1",
  featureId: "f1",
  partIndex: 0,
  segmentIndex: 0,
  fraction: 0.5,
  coordinate: [134, 33.5],
  distanceM: 0,
};

const poiHit: PoiHit = {
  kind: "poi",
  sourceId: "s1",
  featureId: "p1",
  coordinate: [134, 33],
  distanceM: 0,
};

function single(data: GeoJSONFeatureCollection): GeoJSONFeature | undefined {
  return data.features[0];
}

function features(data: GeoJSONFeatureCollection): GeoJSONFeature[] {
  return data.features;
}

describe("buildHoverData", () => {
  it("returns an empty collection for a null hit", () => {
    const data = buildHoverData(null, []);
    expect(data.type).toBe("FeatureCollection");
    expect(data.features).toHaveLength(0);
  });

  it("returns an empty collection when the source is missing", () => {
    expect(buildHoverData(lineHit, []).features).toHaveLength(0);
  });

  it("returns an empty collection when the feature id is missing", () => {
    const src = source("s1", [feature("other", { type: "LineString", coordinates: [[134, 33], [134, 34]] })]);
    expect(buildHoverData(lineHit, [src]).features).toHaveLength(0);
  });

  it("returns an empty collection when the line part index is out of range", () => {
    const src = source("s1", [feature("f1", { type: "LineString", coordinates: [[134, 33], [134, 34]] })]);
    expect(buildHoverData({ ...lineHit, partIndex: 5 }, [src]).features).toHaveLength(0);
  });

  it("highlights the FULL authoritative part for a LineString hit", () => {
    const src = source("s1", [
      feature("f1", { type: "LineString", coordinates: [[134, 33], [134, 33.5], [134, 34]] }),
    ]);
    const data = buildHoverData(lineHit, [src]);
    const fs = features(data);
    expect(fs).toHaveLength(3);
    // 1) full part as a line
    expect(fs[0].geometry).toEqual({
      type: "LineString",
      coordinates: [[134, 33], [134, 33.5], [134, 34]],
    });
    expect(fs[0].properties).toEqual({ hoverKind: "line" });
    // 2) start marker = first coordinate
    expect(fs[1].geometry).toEqual({ type: "Point", coordinates: [134, 33] });
    expect(fs[1].properties).toEqual({ hoverKind: "line-start" });
    // 3) end marker = last coordinate
    expect(fs[2].geometry).toEqual({ type: "Point", coordinates: [134, 34] });
    expect(fs[2].properties).toEqual({ hoverKind: "line-end" });
  });

  it("highlights only the correct part of a MultiLineString", () => {
    const src = source("s1", [
      feature("f1", {
        type: "MultiLineString",
        coordinates: [
          [[135, 33], [135, 34]],
          [[134, 33], [134, 33.5], [134, 34]],
        ],
      }),
    ]);
    const data = buildHoverData({ ...lineHit, partIndex: 1 }, [src]);
    const fs = features(data);
    expect(fs).toHaveLength(3);
    expect(fs[0].geometry).toEqual({
      type: "LineString",
      coordinates: [[134, 33], [134, 33.5], [134, 34]],
    });
    // endpoint markers belong to the highlighted part, not the whole feature
    expect(fs[1].geometry).toEqual({ type: "Point", coordinates: [134, 33] });
    expect(fs[1].properties).toEqual({ hoverKind: "line-start" });
    expect(fs[2].geometry).toEqual({ type: "Point", coordinates: [134, 34] });
    expect(fs[2].properties).toEqual({ hoverKind: "line-end" });
  });

  it("highlights exactly the POI coordinate for a POI hit", () => {
    const src = source("s1", [feature("p1", { type: "Point", coordinates: [134, 33] })]);
    const data = buildHoverData(poiHit, [src]);
    const fs = features(data);
    expect(fs).toHaveLength(1);
    const f = single(data);
    expect(f!.geometry).toEqual({ type: "Point", coordinates: [134, 33] });
    expect(f!.properties).toEqual({ hoverKind: "poi" });
  });

  it("does not highlight an ineligible diagnostic line (visualization_only)", () => {
    const src = source("s1", [
      feature("gap1", { type: "LineString", coordinates: [[134, 33], [134, 34]] }, {
        kind: "gap",
        type: "gap",
        visualization_only: true,
      }),
    ]);
    const data = buildHoverData(lineHit, [src]);
    expect(data.features).toHaveLength(0);
  });

  it("does not mutate the source", () => {
    const src = source("s1", [feature("f1", { type: "LineString", coordinates: [[134, 33], [134, 34]] })]);
    const before = JSON.stringify(src.data);
    buildHoverData(lineHit, [src]);
    expect(JSON.stringify(src.data)).toBe(before);
  });
});

describe("addHoverLayers / updateHover", () => {
  it("registers the shared source and the line/point layers", () => {
    const sources = new Set<string>();
    const layers: string[] = [];
    const map: HoverMap = {
      addSource(id) {
        sources.add(id);
      },
      getSource(id) {
        return sources.has(id) ? { setData: () => {} } : undefined;
      },
      addLayer(layer) {
        layers.push((layer as { id: string }).id);
      },
    };
    addHoverLayers(map, "before-me");
    expect(sources).toContain(HOVER_SOURCE_ID);
    expect(layers).toEqual([HOVER_LINE_LAYER_ID, HOVER_POINT_LAYER_ID]);
  });

  it("pushes hover data through setData and clears on null", () => {
    let data: GeoJSONFeatureCollection | null = null;
    const sources = new Set<string>([HOVER_SOURCE_ID]);
    const map: HoverMap = {
      addSource() {},
      getSource(id) {
        return sources.has(id) ? { setData: (d: GeoJSONFeatureCollection) => { data = d; } } : undefined;
      },
      addLayer() {},
    };
    const src = source("s1", [feature("f1", { type: "LineString", coordinates: [[134, 33], [134, 34]] })]);
    updateHover(map, lineHit, [src]);
    expect(data).not.toBeNull();
    expect(data!.features).toHaveLength(3);
    updateHover(map, null, [src]);
    expect(data!.features).toHaveLength(0);
  });

  it("is a no-op when the hover source is absent", () => {
    const map: HoverMap = {
      addSource() {},
      getSource() {
        return undefined;
      },
      addLayer() {},
    };
    expect(() => updateHover(map, lineHit, [])).not.toThrow();
  });
});
