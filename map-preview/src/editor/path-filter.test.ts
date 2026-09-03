import { describe, expect, it } from "vitest";
import { pathMatchesQuery } from "./path-filter";

describe("pathMatchesQuery", () => {
  it("matches an empty query against every path", () => {
    expect(pathMatchesQuery("route-editor/projects/a.json", "")).toBe(true);
    expect(pathMatchesQuery("route-editor/projects/a.json", "   ")).toBe(true);
  });

  it("matches a case-insensitive substring of the full path", () => {
    expect(pathMatchesQuery("route-editor/projects/henro.json", "HENRO")).toBe(true);
    expect(pathMatchesQuery("route-editor/projects/henro.json", "henro")).toBe(true);
    expect(pathMatchesQuery("output/sekaiisan/temple.geojson", "sekaiisan")).toBe(true);
  });

  it("does not match when the substring is absent", () => {
    expect(pathMatchesQuery("route-editor/projects/henro.json", "lodging")).toBe(false);
    expect(pathMatchesQuery("route-editor/projects/henro.json", "xxxx")).toBe(false);
  });
});
