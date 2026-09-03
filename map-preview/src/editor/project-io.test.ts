import { describe, expect, it } from "vitest";
import { lineLengthM } from "./geometry";
import type {
  EditorProject,
  EditorSource,
  LinePointRef,
  Position,
  RouteLeg,
  RouteSection,
} from "./model";
import { parseProject, serializeJson, serializeProject } from "./project-io";

const SHA = "a".repeat(64);
const SRC_ID = `SRC_${SHA.slice(0, 16)}`;

function mkSource(): EditorSource {
  return {
    id: SRC_ID,
    name: "routes.geojson",
    sha256: SHA,
    format: "geojson",
    color: "#ff0000",
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
        { type: "Feature", id: "poi_start", properties: { id: "poi_start" }, geometry: { type: "Point", coordinates: [134, 33] } },
        { type: "Feature", id: "poi_end", properties: { id: "poi_end" }, geometry: { type: "Point", coordinates: [134, 34] } },
      ],
    },
  };
}

function lineRef(segmentIndex: number, fraction: number, coordinate: Position): LinePointRef {
  return {
    sourceId: SRC_ID,
    featureId: "line",
    partIndex: 0,
    segmentIndex,
    fraction,
    coordinate,
  };
}

function mkLeg(id: string): RouteLeg {
  const start = lineRef(0, 0, [134, 33]);
  const end = lineRef(1, 1, [134, 34]);
  return {
    id,
    sourceId: SRC_ID,
    featureId: "line",
    partIndex: 0,
    start,
    end,
    direction: "forward",
    coordinates: [[134, 33], [134, 33.5], [134, 34]],
    lengthM: lineLengthM([[134, 33], [134, 33.5], [134, 34]]),
  };
}

function mkSection(id: string, leg: RouteLeg): RouteSection {
  return {
    id,
    humanSelected: true,
    fromPoi: { sourceId: SRC_ID, featureId: "poi_start", coordinate: [134, 33] },
    toPoi: { sourceId: SRC_ID, featureId: "poi_end", coordinate: [134, 34] },
    fromAnchor: lineRef(0, 0, [134, 33]),
    toAnchor: lineRef(1, 1, [134, 34]),
    waypoints: [],
    legs: [leg],
  };
}

function mkProject(overrides: Partial<EditorProject> = {}): EditorProject {
  return {
    schema_version: 1,
    kind: "ohenro_route_editor_project",
    projectId: "proj-1",
    sources: [mkSource()],
    sections: [mkSection("S1", mkLeg("l0"))],
    ...overrides,
  };
}

describe("serializeProject", () => {
  it("produces deterministic pretty JSON with sorted keys, trailing newline, no timestamp", () => {
    const text = serializeProject(mkProject());
    expect(text.endsWith("\n")).toBe(true);
    // Pretty-printed (two-space indentation present).
    expect(text).toContain("\n  ");
    // No timestamp anywhere in the serialized form.
    expect(text).not.toMatch(/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/);
  });

  it("recursively sorts object keys while preserving array order", () => {
    const a = mkProject();
    const b = mkProject();
    // Rearrange object-key insertion order at the source level.
    const bSource = { ...b.sources[0] };
    const reordered: Record<string, unknown> = {};
    for (const key of Object.keys(bSource).reverse()) reordered[key] = (bSource as unknown as Record<string, unknown>)[key];
    b.sources = [reordered as unknown as EditorSource];
    expect(serializeProject(a)).toBe(serializeProject(b));
  });

  it("is stable across repeated serializations", () => {
    const p = mkProject();
    expect(serializeProject(p)).toBe(serializeProject(p));
  });
});

describe("parseProject round-trip", () => {
  it("returns a normalized EditorProject equal to the input", () => {
    const p = mkProject();
    const parsed = parseProject(serializeProject(p));
    expect(parsed).toEqual(p);
  });

  it("preserves humanSelected through the round-trip", () => {
    const parsed = parseProject(serializeProject(mkProject()));
    expect(parsed.sections[0].humanSelected).toBe(true);
  });
});

describe("parseProject schema validation", () => {
  it("rejects an unsupported schema_version", () => {
    const bad = { ...mkProject(), schema_version: 2 };
    expect(() => parseProject(JSON.stringify(bad))).toThrow(/schema_version/);
  });

  it("rejects an unexpected kind", () => {
    const bad = { ...mkProject(), kind: "other" };
    expect(() => parseProject(JSON.stringify(bad))).toThrow(/kind/);
  });

  it("rejects a missing/empty projectId", () => {
    expect(() => parseProject(JSON.stringify({ ...mkProject(), projectId: "" }))).toThrow(/projectId/);
  });

  it("rejects project ids that cannot be used in output filenames", () => {
    for (const projectId of ["../escape", "contains space", "日本語", "x".repeat(129)]) {
      expect(() => parseProject(JSON.stringify({ ...mkProject(), projectId }))).toThrow(/filename-safe/);
    }
  });

  it("rejects invalid JSON with a useful error", () => {
    expect(() => parseProject("{ not json")).toThrow(/Invalid project JSON/);
  });
});

describe("parseProject unique id enforcement", () => {
  it("rejects duplicate source ids", () => {
    const p = mkProject();
    p.sources.push(p.sources[0]);
    expect(() => parseProject(JSON.stringify(p))).toThrow(/duplicate source id "SRC_aaaaaaaaaaaaaaaa"/);
  });

  it("rejects duplicate section ids", () => {
    const p = mkProject();
    p.sections.push(mkSection("S1", mkLeg("l1")));
    expect(() => parseProject(JSON.stringify(p))).toThrow(/duplicate section id "S1"/);
  });

  it("rejects duplicate feature ids within a source", () => {
    const p = mkProject();
    const src = p.sources[0];
    src.data.features.push(src.data.features[0]);
    expect(() => parseProject(JSON.stringify(p))).toThrow(/duplicate feature id/);
  });
});

describe("serializeJson", () => {
  it("sorts object keys recursively and preserves array order", () => {
    const value = {
      z: [3, 1, 2],
      a: { y: 1, b: { d: 2, c: 1 } },
    };
    const text = serializeJson(value);
    // Keys sorted recursively; array order untouched.
    expect(text).toBe('{\n  "a": {\n    "b": {\n      "c": 1,\n      "d": 2\n    },\n    "y": 1\n  },\n  "z": [\n    3,\n    1,\n    2\n  ]\n}\n');
  });

  it("produces deterministic output independent of key insertion order", () => {
    const a = { x: 1, y: 2 };
    const b: Record<string, number> = {};
    b.y = 2;
    b.x = 1;
    expect(serializeJson(a)).toBe(serializeJson(b));
  });

  it("always ends with a trailing newline", () => {
    expect(serializeJson({})).toBe("{}\n");
  });

  it("preserves the literal __proto__ key as an own JSON property", () => {
    // Build via JSON.parse so "__proto__" is an own (not prototype) key.
    const value = JSON.parse('{"__proto__": {"payload": 1}, "b": 2}');
    const text = serializeJson(value);
    expect(text).toBe('{\n  "__proto__": {\n    "payload": 1\n  },\n  "b": 2\n}\n');
    // JSON round-trip keeps it an own key, and Object.prototype is unmutated.
    const reparsed = JSON.parse(text) as Record<string, unknown>;
    expect(Object.getOwnPropertyNames(reparsed)).toContain("__proto__");
    expect(Object.getPrototypeOf(reparsed)).toBe(Object.prototype);
  });
});

describe("parseProject source id / sha256 derivation", () => {
  it("accepts a source whose id equals SRC_<first 16 sha256 hex chars>", () => {
    const p = mkProject();
    expect(p.sources[0].id).toBe(SRC_ID);
    expect(() => parseProject(serializeProject(p))).not.toThrow();
  });

  it("rejects a valid-looking id that does not match its sha256", () => {
    const p = mkProject();
    p.sources[0].id = "SRC_ffffffffffffffff"; // valid shape, wrong hash
    expect(() => parseProject(JSON.stringify(p))).toThrow(/does not match sha256/);
  });
});

describe("parseProject source format / color validation", () => {
  it("rejects an unsupported source format", () => {
    const p = mkProject();
    p.sources[0].format = "shp";
    expect(() => parseProject(JSON.stringify(p))).toThrow(/format must be "geojson" or "kml"/);
  });

  it("accepts both supported formats", () => {
    expect(() => parseProject(serializeProject(mkProject()))).not.toThrow();
    const kml = mkProject();
    kml.sources[0].format = "kml";
    expect(() => parseProject(serializeProject(kml))).not.toThrow();
  });

  it("rejects a non-#RRGGBB color", () => {
    const p = mkProject();
    p.sources[0].color = "red";
    expect(() => parseProject(JSON.stringify(p))).toThrow(/color must be a #RRGGBB hex string/);
  });

  it("accepts case-insensitive #RRGGBB hex colors", () => {
    const p = mkProject();
    p.sources[0].color = "#FF00aa";
    expect(() => parseProject(serializeProject(p))).not.toThrow();
  });
});

describe("parseProject malformed / stale refs rejected", () => {
  it("rejects a leg referencing an unknown feature", () => {
    const p = mkProject();
    p.sections[0].legs[0].featureId = "nope";
    expect(() => parseProject(JSON.stringify(p))).toThrow(/unknown featureId "nope"/);
  });

  it("rejects an out-of-range partIndex", () => {
    const p = mkProject();
    p.sections[0].legs[0].partIndex = 3;
    expect(() => parseProject(JSON.stringify(p))).toThrow(/out-of-range partIndex/);
  });

  it("rejects a POI coordinate that matches no authoritative point", () => {
    const p = mkProject();
    p.sections[0].fromPoi = { sourceId: SRC_ID, featureId: "poi_start", coordinate: [134, 33.123] };
    expect(() => parseProject(JSON.stringify(p))).toThrow(/does not match any authoritative point/);
  });

  it("rejects a stale anchor coordinate", () => {
    const p = mkProject();
    p.sections[0].fromAnchor = lineRef(0, 0, [134, 33.5]);
    expect(() => parseProject(JSON.stringify(p))).toThrow(/stale coordinate/);
  });

  it("rejects an invalid fraction", () => {
    const p = mkProject();
    p.sections[0].legs[0].start.fraction = 1.5;
    expect(() => parseProject(JSON.stringify(p))).toThrow(/invalid fraction/);
  });
});

describe("parseProject leg geometry recomputation", () => {
  it("recomputes coordinates, direction and length; never trusts saved values", () => {
    const p = mkProject();
    // Tamper with the saved derived geometry.
    p.sections[0].legs[0].coordinates = [[135, 35], [135, 36], [135, 37]];
    p.sections[0].legs[0].lengthM = 999999;
    p.sections[0].legs[0].direction = "reverse";

    const parsed = parseProject(serializeProject(p));
    const leg = parsed.sections[0].legs[0];
    expect(leg.coordinates).toEqual([[134, 33], [134, 33.5], [134, 34]]);
    expect(leg.lengthM).toBeCloseTo(lineLengthM([[134, 33], [134, 33.5], [134, 34]]), 9);
    expect(leg.direction).toBe("forward");
  });
});
