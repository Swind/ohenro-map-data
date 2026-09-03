import { describe, expect, it } from "vitest";
import { lineLengthM } from "./geometry";
import type {
  EditorProject,
  EditorSource,
  GeoJSONFeature,
  LinePointRef,
  Position,
  RouteLeg,
  RouteSection,
} from "./model";
import { exportProjectToGeoJSON } from "./export-geojson";
import { parseProject, serializeProject } from "./project-io";

const SHA = "b".repeat(64);
const SOURCE_ID = `SRC_${SHA.slice(0, 16)}`;

function makeSource(): EditorSource {
  return {
    id: SOURCE_ID,
    name: "routes.geojson",
    sha256: SHA,
    format: "geojson",
    color: "#0ea5e9",
    visible: true,
    selectable: true,
    importWarnings: [],
    data: {
      type: "FeatureCollection",
      features: [
        {
          type: "Feature",
          id: "line",
          properties: { id: "line" },
          geometry: { type: "LineString", coordinates: [[134, 33], [134, 33.5], [134, 34]] },
        },
        {
          type: "Feature",
          id: "line2",
          properties: { id: "line2" },
          geometry: { type: "LineString", coordinates: [[134, 33.6], [134, 34]] },
        },
        { type: "Feature", id: "poi_start", properties: { id: "poi_start" }, geometry: { type: "Point", coordinates: [134, 33] } },
        { type: "Feature", id: "poi_end", properties: { id: "poi_end" }, geometry: { type: "Point", coordinates: [134, 34] } },
      ],
    },
  };
}

function ref(
  segmentIndex: number,
  fraction: number,
  coordinate: Position,
  featureId = "line",
): LinePointRef {
  return { sourceId: SOURCE_ID, featureId, partIndex: 0, segmentIndex, fraction, coordinate };
}

function leg(
  id: string,
  start: LinePointRef,
  end: LinePointRef,
  direction: RouteLeg["direction"],
  coordinates: Position[],
): RouteLeg {
  return {
    id,
    sourceId: SOURCE_ID,
    featureId: start.featureId,
    partIndex: 0,
    start,
    end,
    direction,
    coordinates,
    lengthM: lineLengthM(coordinates),
  };
}

/** Two legs sharing an exact boundary at [134, 33.5] -> continuous section. */
function continuousSection(id = "S1"): RouteSection {
  const legs = [
    leg("l0", ref(0, 0, [134, 33]), ref(0, 1, [134, 33.5]), "forward", [[134, 33], [134, 33.5]]),
    leg("l1", ref(1, 0, [134, 33.5]), ref(1, 1, [134, 34]), "forward", [[134, 33.5], [134, 34]]),
  ];
  return {
    id,
    humanSelected: true,
    fromPoi: { sourceId: SOURCE_ID, featureId: "poi_start", coordinate: [134, 33] },
    toPoi: { sourceId: SOURCE_ID, featureId: "poi_end", coordinate: [134, 34] },
    fromAnchor: ref(0, 0, [134, 33]),
    toAnchor: ref(1, 1, [134, 34]),
    waypoints: [],
    legs,
  };
}

/** Two legs that do not meet exactly at the boundary -> has_gaps section. */
function gappedSection(): RouteSection {
  const legs = [
    leg("l0", ref(0, 0, [134, 33]), ref(0, 1, [134, 33.5]), "forward", [[134, 33], [134, 33.5]]),
    leg("l1", ref(0, 0, [134, 33.6], "line2"), ref(0, 1, [134, 34], "line2"), "forward", [[134, 33.6], [134, 34]]),
  ];
  return {
    id: "S2",
    humanSelected: true,
    fromPoi: { sourceId: SOURCE_ID, featureId: "poi_start", coordinate: [134, 33] },
    toPoi: { sourceId: SOURCE_ID, featureId: "poi_end", coordinate: [134, 34] },
    fromAnchor: ref(0, 0, [134, 33]),
    toAnchor: ref(0, 1, [134, 34], "line2"),
    waypoints: [],
    legs,
  };
}

function emptySection(): RouteSection {
  return {
    id: "S3",
    humanSelected: false,
    fromPoi: { sourceId: SOURCE_ID, featureId: "poi_start", coordinate: [134, 33] },
    toPoi: { sourceId: SOURCE_ID, featureId: "poi_end", coordinate: [134, 34] },
    fromAnchor: ref(0, 0, [134, 33]),
    toAnchor: ref(1, 1, [134, 34]),
    waypoints: [],
    legs: [],
  };
}

/** A continuous section with valid legs but no endpoint POI/anchor metadata. */
function sectionMissingEndpoints(): RouteSection {
  return {
    id: "S4",
    humanSelected: true,
    fromPoi: null,
    toPoi: null,
    fromAnchor: null,
    toAnchor: null,
    waypoints: [],
    legs: [leg("l0", ref(0, 0, [134, 33]), ref(1, 1, [134, 34]), "forward", [[134, 33], [134, 33.5], [134, 34]])],
  };
}

function project(sections: RouteSection[]): EditorProject {
  return {
    schema_version: 1,
    kind: "ohenro_route_editor_project",
    projectId: "proj-1",
    sources: [makeSource()],
    sections,
  };
}

function byType(features: GeoJSONFeature[], type: string): GeoJSONFeature[] {
  return features.filter((f) => f.properties?.type === type);
}

describe("final GeoJSON export (qa=false)", () => {
  it("emits one LineString section feature plus endpoint POI and anchor Points", () => {
    const fc = exportProjectToGeoJSON(project([continuousSection()]));
    const sections = byType(fc.features, "section");
    expect(sections).toHaveLength(1);
    expect(sections[0].geometry).toEqual({
      type: "LineString",
      coordinates: [[134, 33], [134, 33.5], [134, 34]],
    });
    expect(sections[0].id).toBe("section:S1");
    expect(sections[0].properties).toMatchObject({
      section_id: "S1",
      status: "continuous",
      human_selected: true,
      source_ids: [SOURCE_ID],
      feature_ids: ["line"],
    });
    expect(sections[0].properties?.length_m).toBeCloseTo(
      lineLengthM([[134, 33], [134, 33.5], [134, 34]]),
      6,
    );
    // POI + anchor points.
    expect(byType(fc.features, "poi")).toHaveLength(2);
    expect(byType(fc.features, "anchor")).toHaveLength(2);
    // No QA diagnostics in the final export.
    expect(byType(fc.features, "gap")).toHaveLength(0);
    expect(byType(fc.features, "poi_offset")).toHaveLength(0);
  });

  it("merges exact leg boundaries (no duplicated shared coordinate)", () => {
    const fc = exportProjectToGeoJSON(project([continuousSection()]));
    const section = byType(fc.features, "section")[0];
    expect(section.geometry).toEqual({
      type: "LineString",
      coordinates: [[134, 33], [134, 33.5], [134, 34]],
    });
  });

  it("preserves project section order", () => {
    const fc = exportProjectToGeoJSON(project([continuousSection("S1"), continuousSection("S1b")]));
    const ids = byType(fc.features, "section").map((f) => f.id);
    expect(ids).toEqual(["section:S1", "section:S1b"]);
  });

  it("rejects a has_gaps section", () => {
    expect(() => exportProjectToGeoJSON(project([gappedSection()]))).toThrow(/has gaps/);
  });

  it("rejects an empty section", () => {
    expect(() => exportProjectToGeoJSON(project([emptySection()]))).toThrow(/no legs/);
  });

  it("rejects a project with no sections at all", () => {
    expect(() => exportProjectToGeoJSON(project([]))).toThrow(/no sections/);
  });
});

describe("QA GeoJSON export (qa=true)", () => {
  it("emits a gapped section as MultiLineString", () => {
    const fc = exportProjectToGeoJSON(project([gappedSection()]), { qa: true });
    const section = byType(fc.features, "section")[0];
    expect(section.geometry).toEqual({
      type: "MultiLineString",
      coordinates: [[[134, 33], [134, 33.5]], [[134, 33.6], [134, 34]]],
    });
    expect(section.properties).toMatchObject({ section_id: "S2", status: "has_gaps" });
  });

  it("emits visualization-only gap LineStrings with explicit properties", () => {
    const fc = exportProjectToGeoJSON(project([gappedSection()]), { qa: true });
    const gaps = byType(fc.features, "gap");
    expect(gaps).toHaveLength(1);
    expect(gaps[0].geometry).toEqual({
      type: "LineString",
      coordinates: [[134, 33.5], [134, 33.6]],
    });
    expect(gaps[0].properties).toMatchObject({
      section_id: "S2",
      between_leg_index: 0,
      visualization_only: true,
    });
    expect(typeof gaps[0].properties?.distance_m).toBe("number");
  });

  it("emits visualization-only POI offset LineStrings", () => {
    const fc = exportProjectToGeoJSON(project([gappedSection()]), { qa: true });
    const offsets = byType(fc.features, "poi_offset");
    expect(offsets).toHaveLength(2);
    for (const o of offsets) {
      expect(o.properties?.visualization_only).toBe(true);
      expect(o.properties?.role).toMatch(/^(from|to)$/);
      expect((o.geometry as { type: "LineString"; coordinates: Position[] }).coordinates).toHaveLength(2);
    }
  });

  it("still exports a continuous section cleanly in QA mode", () => {
    const fc = exportProjectToGeoJSON(project([continuousSection()]), { qa: true });
    expect(byType(fc.features, "section")[0].geometry).toEqual({
      type: "LineString",
      coordinates: [[134, 33], [134, 33.5], [134, 34]],
    });
  });

  it("exports a valid route even when endpoint POI/anchors are missing", () => {
    const fc = exportProjectToGeoJSON(project([sectionMissingEndpoints()]), { qa: true });
    // The route legs are still useful QA output.
    const sections = byType(fc.features, "section");
    expect(sections).toHaveLength(1);
    expect(sections[0].geometry).toEqual({
      type: "LineString",
      coordinates: [[134, 33], [134, 33.5], [134, 34]],
    });
    // Missing endpoint metadata simply omits those Point/offset features.
    expect(byType(fc.features, "poi")).toHaveLength(0);
    expect(byType(fc.features, "anchor")).toHaveLength(0);
    expect(byType(fc.features, "poi_offset")).toHaveLength(0);
  });

  it("reconstructs a leg's derived geometry from the source (invalid saved length ignored)", () => {
    const bad = sectionMissingEndpoints();
    bad.legs[0].lengthM = -5; // stale/invalid saved number
    const fc = exportProjectToGeoJSON(project([bad]), { qa: true });
    // The leg's geometry/length are recomputed from the authoritative source.
    const section = byType(fc.features, "section")[0];
    expect(section).toBeDefined();
    expect(section.geometry).toEqual({
      type: "LineString",
      coordinates: [[134, 33], [134, 33.5], [134, 34]],
    });
  });

  it("emits both POI offset diagnostics for a continuous section in QA", () => {
    const fc = exportProjectToGeoJSON(project([continuousSection()]), { qa: true });
    const offsets = byType(fc.features, "poi_offset");
    expect(offsets).toHaveLength(2);
    expect(offsets.map((o) => o.properties?.role).sort()).toEqual(["from", "to"]);
    for (const o of offsets) expect(o.properties?.visualization_only).toBe(true);
  });

  it("allows an empty QA export", () => {
    const fc = exportProjectToGeoJSON(project([]), { qa: true });
    expect(fc.features).toEqual([]);
  });

  it("QA also rejects a dangling source ref", () => {
    const sec = continuousSection();
    sec.legs[0].featureId = "does-not-exist";
    expect(() => exportProjectToGeoJSON(project([sec]), { qa: true })).toThrow(
      /unknown featureId "does-not-exist"/,
    );
  });
});

describe("final export validation and round-trip", () => {
  it("rejects a reversed single leg whose endpoint anchors are stale", () => {
    const legs = [
      leg("r0", ref(1, 1, [134, 34]), ref(0, 0, [134, 33]), "reverse", [[134, 34], [134, 33.5], [134, 33]]),
    ];
    const section: RouteSection = {
      id: "Srev",
      humanSelected: true,
      fromPoi: { sourceId: SOURCE_ID, featureId: "poi_end", coordinate: [134, 34] },
      toPoi: { sourceId: SOURCE_ID, featureId: "poi_start", coordinate: [134, 33] },
      // Anchors still point at the forward endpoints (stale after reversal),
      // so they disagree with the reversed leg's derived endpoints.
      fromAnchor: ref(0, 0, [134, 33]),
      toAnchor: ref(1, 1, [134, 34]),
      waypoints: [],
      legs,
    };
    expect(() => exportProjectToGeoJSON(project([section]))).toThrow(/not exportable/);
  });

  it("round-trips a valid source-backed project through parse(serialize()) and exports", () => {
    const normalized = parseProject(serializeProject(project([continuousSection()])));
    const fc = exportProjectToGeoJSON(normalized);
    expect(byType(fc.features, "section")).toHaveLength(1);
    expect(byType(fc.features, "poi_offset")).toHaveLength(0);
  });

  it("does not mutate the caller's project", () => {
    const original = project([continuousSection()]);
    const snapshot = serializeProject(original);
    exportProjectToGeoJSON(original, { qa: true });
    expect(serializeProject(original)).toBe(snapshot);
  });
});