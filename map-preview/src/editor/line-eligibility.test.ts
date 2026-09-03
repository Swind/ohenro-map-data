import { describe, expect, it } from "vitest";
import type { GeoJSONFeature } from "./model";
import {
  isRouteEligibleFeature,
  ROUTE_ELIGIBLE_LINE_FILTER,
  LINE_GEOMETRY_FILTER,
} from "./line-eligibility";

function feature(properties: Record<string, unknown> | null): GeoJSONFeature {
  return { type: "Feature", geometry: { type: "LineString", coordinates: [[134, 33], [134, 34]] }, properties };
}

describe("isRouteEligibleFeature", () => {
  it("accepts an ordinary line (no diagnostic markers)", () => {
    expect(isRouteEligibleFeature(feature({ kind: "section" }))).toBe(true);
    expect(isRouteEligibleFeature(feature({}))).toBe(true);
  });

  it("accepts a feature with null properties", () => {
    expect(isRouteEligibleFeature(feature(null))).toBe(true);
  });

  it("rejects visualization_only: true", () => {
    expect(isRouteEligibleFeature(feature({ visualization_only: true }))).toBe(false);
  });

  it("rejects review_visualization_only: true", () => {
    expect(isRouteEligibleFeature(feature({ review_visualization_only: true }))).toBe(false);
  });

  it("rejects kind == poi_offset / gap", () => {
    expect(isRouteEligibleFeature(feature({ kind: "poi_offset" }))).toBe(false);
    expect(isRouteEligibleFeature(feature({ kind: "gap" }))).toBe(false);
  });

  it("rejects type == poi_offset / gap", () => {
    expect(isRouteEligibleFeature(feature({ type: "poi_offset" }))).toBe(false);
    expect(isRouteEligibleFeature(feature({ type: "gap" }))).toBe(false);
  });

  it("accepts non-boolean/other values for the flags", () => {
    expect(isRouteEligibleFeature(feature({ visualization_only: "true" }))).toBe(true);
    expect(isRouteEligibleFeature(feature({ review_visualization_only: 1 }))).toBe(true);
    expect(isRouteEligibleFeature(feature({ kind: "section" }))).toBe(true);
  });
});

describe("ROUTE_ELIGIBLE_LINE_FILTER", () => {
  it("is a valid expression that includes the line-geometry filter", () => {
    expect(Array.isArray(ROUTE_ELIGIBLE_LINE_FILTER)).toBe(true);
    // The combined filter starts with "all" and embeds the line-geometry filter.
    expect((ROUTE_ELIGIBLE_LINE_FILTER as unknown[])[0]).toBe("all");
    const nested = (ROUTE_ELIGIBLE_LINE_FILTER as unknown[]).slice(1);
    expect(nested).toContainEqual(LINE_GEOMETRY_FILTER);
  });

  it("includes the diagnostic property rejections", () => {
    const json = JSON.stringify(ROUTE_ELIGIBLE_LINE_FILTER);
    expect(json).toContain("visualization_only");
    expect(json).toContain("review_visualization_only");
    expect(json).toContain("poi_offset");
    expect(json).toContain("gap");
  });
});
