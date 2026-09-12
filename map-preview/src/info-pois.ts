import type {
  FilterSpecification,
  Map as MapLibreMap,
} from "maplibre-gl";

// Consolidated information POIs (scripts/build-info-pois.py), one unified
// `category` taxonomy the app filters by. Each Point feature carries
// `category` / `source` / `source_category` / `name` / `poi_id`. No cross-source
// dedup; the selector groups by category with per-category circle layers.
export interface InfoPoiDef {
  category: string; // GeoJSON properties.category value
  label: string; // UI checkbox label
  color: string; // circle / label color
  checked: boolean; // default checked in the selector
  hasLabel: boolean; // whether a symbol label layer is added
}

export interface InfoPoiGroup {
  category: string;
  label: string;
  color: string;
  checked: boolean;
  hasLabel: boolean;
  circle: string; // circle layer id
  labelLayer?: string; // symbol label layer id (only when hasLabel)
}

export interface InfoPoiFeature {
  type: "Feature";
  geometry: { type: "Point"; coordinates: number[] };
  properties: Record<string, unknown>;
}

export interface InfoPoiFeatureCollection {
  type: "FeatureCollection";
  features: InfoPoiFeature[];
}

export const INFO_POI_ATTRIBUTION =
  "Mizutani Henro Guide Map / 四国自然歩道 / 88sekaiisan / arukihenro / OSM";

export const INFO_POI_DEFS: InfoPoiDef[] = [
  { category: "toilet", label: "toilets", color: "#31889c", checked: true, hasLabel: true },
  { category: "water", label: "drinking water", color: "#1d7fae", checked: false, hasLabel: false },
  { category: "rest_area", label: "rest areas", color: "#4f772d", checked: false, hasLabel: false },
  { category: "food", label: "food", color: "#c96a1e", checked: false, hasLabel: false },
  { category: "shop", label: "shops & supplies", color: "#ca6f1e", checked: false, hasLabel: false },
  { category: "onsen", label: "onsens", color: "#a05a2c", checked: false, hasLabel: false },
  { category: "transport", label: "transport", color: "#266ca8", checked: false, hasLabel: false },
  { category: "sightseeing", label: "sightseeing", color: "#9c6b3f", checked: false, hasLabel: false },
  { category: "wayfinding", label: "wayfinding", color: "#6d6d6d", checked: false, hasLabel: false },
  { category: "warning_hazard", label: "warnings", color: "#c5443e", checked: false, hasLabel: false },
  { category: "experience_note", label: "experience notes", color: "#8e6f9c", checked: false, hasLabel: false },
  { category: "shrine", label: "shrines", color: "#8e3b37", checked: false, hasLabel: false },
  { category: "temple", label: "temples", color: "#8e3b37", checked: false, hasLabel: true },
  { category: "route_endpoint", label: "route endpoints", color: "#9a9a9a", checked: false, hasLabel: false },
  { category: "other", label: "other", color: "#6d6d6d", checked: false, hasLabel: false },
];

function categoryFilter(category: string): FilterSpecification {
  return ["all", ["==", ["geometry-type"], "Point"], ["==", ["get", "category"], category]];
}

/**
 * Fetch the consolidated info-POI GeoJSON. Throws on non-OK response.
 */
export async function fetchInfoPois(
  url: string,
): Promise<InfoPoiFeatureCollection> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`info pois fetch failed: ${res.status}`);
  return (await res.json()) as InfoPoiFeatureCollection;
}

/**
 * Add one circle layer per category (plus a label layer for the named kinds).
 * All layers start hidden; the selector in main.ts applies the master +
 * per-category toggles via layer visibility.
 */
export function addInfoPoiLayers(
  map: MapLibreMap,
  featureCollection: InfoPoiFeatureCollection,
  beforeId: string | undefined,
): InfoPoiGroup[] {
  map.addSource("info-pois", {
    type: "geojson",
    data: featureCollection,
    attribution: INFO_POI_ATTRIBUTION,
  });

  const groups: InfoPoiGroup[] = [];
  for (const def of INFO_POI_DEFS) {
    const circle = `info-poi-${def.category}`;
    const label = `info-poi-${def.category}-label`;
    map.addLayer(
      {
        id: circle,
        type: "circle",
        source: "info-pois",
        filter: categoryFilter(def.category),
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
    const group: InfoPoiGroup = {
      category: def.category,
      label: def.label,
      color: def.color,
      checked: def.checked,
      hasLabel: def.hasLabel,
      circle,
    };
    if (def.hasLabel) {
      map.addLayer(
        {
          id: label,
          type: "symbol",
          source: "info-pois",
          filter: categoryFilter(def.category),
          minzoom: 11,
          layout: {
            "text-field": ["coalesce", ["get", "name"], ""],
            "text-font": ["Noto Sans CJK JP Regular"],
            "text-size": 10,
            "text-offset": [0, 0.9],
            "text-anchor": "top",
            "text-max-width": 8,
            visibility: "none",
          },
          paint: {
            "text-color": def.color,
            "text-halo-color": "#ffffff",
            "text-halo-width": 1.3,
          },
        },
        beforeId,
      );
      group.labelLayer = label;
    }
    groups.push(group);
  }
  return groups;
}