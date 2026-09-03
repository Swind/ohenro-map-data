import { describe, expect, it } from "vitest";
import type { EditorProject, EditorSource, RouteSection } from "./model";

describe("editor model", () => {
  it("holds the schema_version-1 project shape", () => {
    const source: EditorSource = {
      id: "src1",
      name: "routes",
      sha256: "aa",
      format: "geojson",
      color: "#ff0000",
      visible: true,
      selectable: true,
      data: { type: "FeatureCollection", features: [] },
      importWarnings: [],
    };
    const project: EditorProject = {
      schema_version: 1,
      kind: "ohenro_route_editor_project",
      projectId: "proj-1",
      sources: [source],
      sections: [] as RouteSection[],
    };
    expect(project.schema_version).toBe(1);
    expect(project.kind).toBe("ohenro_route_editor_project");
    expect(project.sources).toHaveLength(1);
    expect(project.sections).toEqual([]);
  });
});