import { describe, expect, it } from "vitest";
import {
  HENRO_HELPER_ITINERARY_DEFS,
  HENRO_HELPER_LAYER_DEFS,
  convertHenroHelper,
  type HenroHelperFeatureCollection,
} from "./henro-helper";

// Layers present in output/henro-helper-routes/henro-helper-routes.geojson
// (extracted from the Henro Helper APK). Kept in sync with extract_routes.py.
const EXTRACTED_LAYERS = [
  "black",
  "red",
  "green",
  "blue",
  "purple",
  "special",
  "eighty88to1",
  "connection",
  "itinerary_56",
  "itinerary_49",
  "itinerary_42",
];

describe("henro-helper layer definitions", () => {
  it("covers every layer present in the extracted GeoJSON", () => {
    const defLayers = [
      ...HENRO_HELPER_LAYER_DEFS.map((d) => d.layer),
      ...HENRO_HELPER_ITINERARY_DEFS.map((d) => d.layer),
    ];
    expect(defLayers).toEqual(EXTRACTED_LAYERS);
  });

  it("has unique layer ids and deterministic casing/line ids", () => {
    const ids = [
      ...HENRO_HELPER_LAYER_DEFS.map((d) => d.layer),
      ...HENRO_HELPER_ITINERARY_DEFS.map((d) => d.layer),
    ];
    expect(new Set(ids).size).toBe(ids.length);
    const casingIds = ids.map((id) => `henro-helper-${id}-casing`);
    const lineIds = ids.map((id) => `henro-helper-${id}`);
    expect(new Set(casingIds).size).toBe(casingIds.length);
    expect(new Set(lineIds).size).toBe(lineIds.length);
    expect(casingIds.some((id) => lineIds.includes(id))).toBe(false);
  });

  it("defaults to black visible and everything else hidden", () => {
    const checked = HENRO_HELPER_LAYER_DEFS.filter((d) => d.checked).map((d) => d.layer);
    expect(checked).toEqual(["black"]);
  });

  it("derives per-day selector lists in feature order", () => {
    const data: HenroHelperFeatureCollection = {
      type: "FeatureCollection",
      features: [
        feature("itinerary_56", "DAY 1A"),
        feature("itinerary_56", "DAY 1A"),
        feature("itinerary_56", "DAY 2"),
        feature("itinerary_49", "DAY 1"),
      ],
    };
    const { itinerarySets } = convertHenroHelper(data);
    const byLayer = new Map(itinerarySets.map((s) => [s.layer, s]));
    expect(byLayer.get("itinerary_56")?.days.map((d) => d.dayLabel)).toEqual([
      "DAY 1A",
      "DAY 2",
    ]);
    expect(byLayer.get("itinerary_49")?.days.map((d) => d.dayLabel)).toEqual([
      "DAY 1",
    ]);
    expect(byLayer.get("itinerary_42")?.days).toEqual([]);
  });
});

function feature(layer: string, dayLabel: string): HenroHelperFeatureCollection["features"][number] {
  return {
    type: "Feature",
    geometry: { type: "LineString", coordinates: [[134, 34], [134.1, 34.1]] },
    properties: { layer, day_label: dayLabel },
  };
}