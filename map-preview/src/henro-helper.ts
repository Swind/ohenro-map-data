import type { FilterSpecification, Map as MapLibreMap } from "maplibre-gl";

// Henro Helper (com.henrohelper100.app) route layers, extracted from the
// APK's Dart AOT literals into a single GeoJSON (datasets/henro_helper/output/).
// Each feature carries `layer` (black/red/green/blue/purple/special/
// eighty88to1/connection/itinerary_*) and `route_type` (road/trail/special/
// connection/itinerary) properties that preserve the app's own classification.
// Itinerary features additionally carry per-day metadata (day_label like
// "DAY 1A", title, distance/elevation/time) merged from the app's day records.
export interface HenroHelperLayerDef {
  layer: string; // GeoJSON properties.layer value
  label: string; // UI checkbox label
  color: string; // line/circle color
  checked: boolean; // default checked in the selector
  isPoint?: boolean; // connection points (Point geometry)
}

export interface HenroHelperGroup {
  layer: string;
  label: string;
  color: string;
  casing: string; // line casing layer id
  line: string; // line / circle layer id
  checked: boolean;
}

export interface HenroHelperDay {
  dayLabel: string; // "DAY 1A"
}

export interface HenroHelperItinerarySet {
  layer: string; // "itinerary_56"
  label: string;
  color: string;
  casing: string;
  line: string;
  labelLayer: string;
  days: HenroHelperDay[];
}

export interface HenroHelperFeature {
  type: "Feature";
  geometry:
    | { type: "LineString"; coordinates: number[][] }
    | { type: "Point"; coordinates: number[] };
  properties: Record<string, unknown>;
}

export interface HenroHelperFeatureCollection {
  type: "FeatureCollection";
  features: HenroHelperFeature[];
}

export const HENRO_HELPER_ATTRIBUTION =
  '<a href="https://apkpure.com/henro-helper-shikoku-88/com.henrohelper100.app">Henro Helper</a>';

export const HENRO_HELPER_LAYER_DEFS: HenroHelperLayerDef[] = [
  { layer: "black", label: "black (road)", color: "#262626", checked: true },
  { layer: "red", label: "red (road)", color: "#d93025", checked: false },
  { layer: "green", label: "green (road)", color: "#188038", checked: false },
  { layer: "blue", label: "blue (trail)", color: "#1a73e8", checked: false },
  { layer: "purple", label: "purple (trail)", color: "#9334e6", checked: false },
  { layer: "special", label: "special (ferry/ropeway)", color: "#e37400", checked: false },
  { layer: "eighty88to1", label: "88→1 loop", color: "#6b6b6b", checked: false },
  { layer: "connection", label: "connection points", color: "#8e3b37", checked: false, isPoint: true },
];

export const HENRO_HELPER_ITINERARY_DEFS: HenroHelperLayerDef[] = [
  { layer: "itinerary_56", label: "56-day itinerary", color: "#7b5ea7", checked: false },
  { layer: "itinerary_49", label: "49-day itinerary", color: "#3d8b8b", checked: false },
  { layer: "itinerary_42", label: "42-day itinerary", color: "#a05a2c", checked: false },
];

function lineFilter(layer: string): FilterSpecification {
  return [
    "all",
    ["==", ["geometry-type"], "LineString"],
    ["==", ["get", "layer"], layer],
  ];
}

function pointFilter(layer: string): FilterSpecification {
  return [
    "all",
    ["==", ["geometry-type"], "Point"],
    ["==", ["get", "layer"], layer],
  ];
}

/**
 * Fetch the Henro Helper GeoJSON. Throws on non-OK response.
 */
export async function fetchHenroHelper(url: string): Promise<HenroHelperFeatureCollection> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`henro helper fetch failed: ${res.status}`);
  return (await res.json()) as HenroHelperFeatureCollection;
}

/**
 * Derive the per-day selector lists for each itinerary set from the features.
 * Day order follows feature order (which matches the app's day-record order).
 */
export function convertHenroHelper(
  data: HenroHelperFeatureCollection,
): {
  featureCollection: HenroHelperFeatureCollection;
  itinerarySets: HenroHelperItinerarySet[];
} {
  if (!Array.isArray(data.features)) {
    throw new Error("henro helper features is not an array");
  }
  const sets: HenroHelperItinerarySet[] = [];
  for (const def of HENRO_HELPER_ITINERARY_DEFS) {
    const labels: string[] = [];
    for (const f of data.features) {
      if (f.properties.layer === def.layer) {
        const label = f.properties.day_label;
        if (typeof label === "string" && label && !labels.includes(label)) {
          labels.push(label);
        }
      }
    }
    sets.push({
      layer: def.layer,
      label: def.label,
      color: def.color,
      casing: `henro-helper-${def.layer}-casing`,
      line: `henro-helper-${def.layer}`,
      labelLayer: `henro-helper-${def.layer}-label`,
      days: labels.map((dayLabel) => ({ dayLabel })),
    });
  }
  return { featureCollection: data, itinerarySets: sets };
}

/**
 * Add the shared henro-helper GeoJSON source (inline FeatureCollection) and one
 * casing+line (or circle for the connection points) layer per route layer.
 * Itinerary sets also get a line-label layer (day_label). Layers start hidden;
 * the selector in main.ts applies master + per-layer + per-day toggles.
 */
export function addHenroHelperLayers(
  map: MapLibreMap,
  featureCollection: HenroHelperFeatureCollection,
  beforeId: string | undefined,
): { groups: HenroHelperGroup[]; itinerarySets: HenroHelperItinerarySet[] } {
  map.addSource("henro-helper", {
    type: "geojson",
    data: featureCollection,
    attribution: HENRO_HELPER_ATTRIBUTION,
  });

  const groups: HenroHelperGroup[] = [];
  for (const def of HENRO_HELPER_LAYER_DEFS) {
    const casing = `henro-helper-${def.layer}-casing`;
    const line = `henro-helper-${def.layer}`;
    if (def.isPoint) {
      map.addLayer(
        {
          id: line,
          type: "circle",
          source: "henro-helper",
          filter: pointFilter(def.layer),
          minzoom: 8,
          layout: { visibility: "none" },
          paint: {
            "circle-radius": ["interpolate", ["linear"], ["zoom"], 8, 3, 14, 6],
            "circle-color": def.color,
            "circle-stroke-color": "#ffffff",
            "circle-stroke-width": 1.2,
          },
        },
        beforeId,
      );
    } else {
      map.addLayer(
        {
          id: casing,
          type: "line",
          source: "henro-helper",
          filter: lineFilter(def.layer),
          layout: { "line-cap": "round", "line-join": "round", visibility: "none" },
          paint: {
            "line-color": "#ffffff",
            "line-width": ["interpolate", ["linear"], ["zoom"], 8, 5.5, 14, 10],
            "line-opacity": 0.85,
          },
        },
        beforeId,
      );
      map.addLayer(
        {
          id: line,
          type: "line",
          source: "henro-helper",
          filter: lineFilter(def.layer),
          layout: { "line-cap": "round", "line-join": "round", visibility: "none" },
          paint: {
            "line-color": def.color,
            "line-width": ["interpolate", ["linear"], ["zoom"], 8, 2.5, 14, 5.5],
            "line-opacity": 0.9,
          },
        },
        beforeId,
      );
    }
    groups.push({ layer: def.layer, label: def.label, color: def.color, casing, line, checked: def.checked });
  }

  const itinerarySets = convertHenroHelper(featureCollection).itinerarySets;
  for (const set of itinerarySets) {
    const filter = lineFilter(set.layer);
    map.addLayer(
      {
        id: set.casing,
        type: "line",
        source: "henro-helper",
        filter,
        layout: { "line-cap": "round", "line-join": "round", visibility: "none" },
        paint: {
          "line-color": "#ffffff",
          "line-width": ["interpolate", ["linear"], ["zoom"], 8, 5.5, 14, 10],
          "line-opacity": 0.85,
        },
      },
      beforeId,
    );
    map.addLayer(
      {
        id: set.line,
        type: "line",
        source: "henro-helper",
        filter,
        layout: { "line-cap": "round", "line-join": "round", visibility: "none" },
        paint: {
          "line-color": set.color,
          "line-width": ["interpolate", ["linear"], ["zoom"], 8, 2.5, 14, 5.5],
          "line-opacity": 0.9,
        },
      },
      beforeId,
    );
    map.addLayer(
      {
        id: set.labelLayer,
        type: "symbol",
        source: "henro-helper",
        filter,
        layout: {
          "symbol-placement": "line",
          "text-field": ["coalesce", ["get", "day_label"], ""],
          "text-font": ["Noto Sans CJK JP Regular"],
          "text-size": 10,
          "text-letter-spacing": 0.05,
          "text-rotation-alignment": "map",
          "symbol-spacing": 800,
          visibility: "none",
        },
        paint: {
          "text-color": set.color,
          "text-halo-color": "#ffffff",
          "text-halo-width": 1.3,
        },
      },
      beforeId,
    );
  }

  return { groups, itinerarySets };
}