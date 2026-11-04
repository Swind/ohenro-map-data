import { describe, expect, it } from "vitest";
import {
  HENRO_HELPER_POI_DEFS,
  type HenroHelperPoiFeatureCollection,
} from "./henro-helper-pois";

// `kind` values present in datasets/henro_helper/output/henro-helper-pois.geojson
// (extracted from the Henro Helper APK object-pool POI records). Kept in sync
// with extract_routes.py POI_CLASSES.
const EXTRACTED_KINDS = [
  "temple",
  "bekkaku",
  "okunoin",
  "bangai",
  "toilet",
  "shower",
  "convenience_store",
  "rest_area",
  "rest_toilet",
  "tsuyado",
  "onsen",
  "bus_stop",
  "train_station",
  "campground",
  "accommodation",
  "label",
  "poi",
  "important_note",
  "roadside_station",
  "ishizuchi",
];

describe("henro-helper-poi kind definitions", () => {
  it("covers every kind present in the extracted GeoJSON", () => {
    const defKinds = HENRO_HELPER_POI_DEFS.map((d) => d.kind);
    expect(defKinds).toEqual(EXTRACTED_KINDS);
  });

  it("has unique kinds and deterministic circle/label ids", () => {
    const kinds = HENRO_HELPER_POI_DEFS.map((d) => d.kind);
    expect(new Set(kinds).size).toBe(kinds.length);
    const circleIds = kinds.map((kind) => `henro-helper-poi-${kind}`);
    const labelIds = HENRO_HELPER_POI_DEFS.filter((d) => d.hasLabel).map(
      (d) => `henro-helper-poi-${d.kind}-label`,
    );
    expect(new Set(circleIds).size).toBe(circleIds.length);
    expect(new Set(labelIds).size).toBe(labelIds.length);
    expect(circleIds.some((id) => labelIds.includes(id))).toBe(false);
  });

  it("defaults to temples visible and everything else hidden", () => {
    const checked = HENRO_HELPER_POI_DEFS.filter((d) => d.checked).map((d) => d.kind);
    expect(checked).toEqual(["temple"]);
  });

  it("assigns label layers only to named kinds", () => {
    const labeled = HENRO_HELPER_POI_DEFS.filter((d) => d.hasLabel).map((d) => d.kind);
    expect(labeled).toEqual([
      "temple",
      "bekkaku",
      "okunoin",
      "bangai",
      "tsuyado",
      "onsen",
      "campground",
      "accommodation",
      "label",
      "poi",
      "ishizuchi",
    ]);
  });
});

// The combined POI collection is a flat FeatureCollection of Point features
// carrying `kind`; guard the fetch/convert contract used by map.ts.
describe("henro-helper-poi collection shape", () => {
  it("accepts a feature collection with a kind property", () => {
    const data: HenroHelperPoiFeatureCollection = {
      type: "FeatureCollection",
      features: [
        {
          type: "Feature",
          geometry: { type: "Point", coordinates: [134, 34] },
          properties: { kind: "temple", temple_number: 1, name_ja: "霊山寺" },
        },
      ],
    };
    const kinds = new Set(data.features.map((f) => f.properties.kind));
    expect(kinds.has("temple")).toBe(true);
    expect(HENRO_HELPER_POI_DEFS.some((d) => d.kind === "temple")).toBe(true);
  });
});