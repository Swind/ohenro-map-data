import type {
  ExpressionSpecification,
  FilterSpecification,
  Map as MapLibreMap,
} from "maplibre-gl";

// Henro Helper (com.henrohelper100.app) POI markers, extracted from the APK's
// Dart AOT object-pool literals into a single GeoJSON
// (datasets/henro_helper/output/henro-helper-pois.geojson). Each Point feature
// carries `kind` (temple/toilet/convenience_store/...), multilingual fields
// (name_ja / name_en + raw field_XX), and structured extras (temple_number /
// temple_name_ja for the 88 temples, bekkaku_number, okunoin temple_number...).
export interface HenroHelperPoiDef {
  kind: string; // GeoJSON properties.kind value
  label: string; // UI checkbox label
  color: string; // circle / label color
  checked: boolean; // default checked in the selector
  hasLabel: boolean; // whether a symbol label layer is added
}

export interface HenroHelperPoiGroup {
  kind: string;
  label: string;
  color: string;
  checked: boolean;
  hasLabel: boolean;
  circle: string; // circle layer id
  labelLayer?: string; // symbol label layer id (only when hasLabel)
}

export interface HenroHelperPoiFeature {
  type: "Feature";
  geometry: { type: "Point"; coordinates: number[] };
  properties: Record<string, unknown>;
}

export interface HenroHelperPoiFeatureCollection {
  type: "FeatureCollection";
  features: HenroHelperPoiFeature[];
}

export const HENRO_HELPER_POI_ATTRIBUTION =
  '<a href="https://apkpure.com/henro-helper-shikoku-88/com.henrohelper100.app">Henro Helper</a>';

export const HENRO_HELPER_POI_DEFS: HenroHelperPoiDef[] = [
  { kind: "temple", label: "temples (88)", color: "#8e3b37", checked: true, hasLabel: true },
  { kind: "bekkaku", label: "bekkaku (20)", color: "#b06a5a", checked: false, hasLabel: true },
  { kind: "okunoin", label: "okunoin (77)", color: "#9c6b3f", checked: false, hasLabel: true },
  { kind: "bangai", label: "bangai (81)", color: "#a08c3a", checked: false, hasLabel: true },
  { kind: "toilet", label: "toilets (414)", color: "#31889c", checked: false, hasLabel: false },
  { kind: "shower", label: "showers (36)", color: "#2f9bb0", checked: false, hasLabel: false },
  { kind: "convenience_store", label: "convenience stores (313)", color: "#ca6f1e", checked: false, hasLabel: false },
  { kind: "rest_area", label: "rest areas (277)", color: "#4f772d", checked: false, hasLabel: false },
  { kind: "rest_toilet", label: "rest toilets (136)", color: "#31889c", checked: false, hasLabel: false },
  { kind: "tsuyado", label: "tsuyados (27)", color: "#8e6f9c", checked: false, hasLabel: true },
  { kind: "onsen", label: "onsens (59)", color: "#a05a2c", checked: false, hasLabel: true },
  { kind: "bus_stop", label: "bus stops (52)", color: "#266ca8", checked: false, hasLabel: false },
  { kind: "train_station", label: "train stations (38)", color: "#266ca8", checked: false, hasLabel: false },
  { kind: "campground", label: "campgrounds (86)", color: "#4f772d", checked: false, hasLabel: true },
  { kind: "accommodation", label: "accommodations (543)", color: "#744f8f", checked: false, hasLabel: true },
  { kind: "label", label: "place labels (58)", color: "#6d6d6d", checked: false, hasLabel: true },
  { kind: "poi", label: "points of interest (86)", color: "#d9822b", checked: false, hasLabel: true },
  { kind: "important_note", label: "important notes (24)", color: "#c5443e", checked: false, hasLabel: false },
  { kind: "roadside_station", label: "roadside stations (26)", color: "#765b30", checked: false, hasLabel: false },
  { kind: "ishizuchi", label: "Ishizuchi itineraries (3)", color: "#9334e6", checked: false, hasLabel: true },
];

function kindFilter(kind: string): FilterSpecification {
  return ["all", ["==", ["geometry-type"], "Point"], ["==", ["get", "kind"], kind]];
}

function labelTextField(kind: string): ExpressionSpecification {
  if (kind === "temple" || kind === "bekkaku") {
    return [
      "format",
      ["coalesce", ["get", "temple_number"], ["get", "bekkaku_number"], ""],
      {},
      " ",
      ["coalesce", ["get", "temple_name_ja"], ["get", "name_ja"], ["get", "name_en"], ""],
      {},
    ];
  }
  return ["coalesce", ["get", "name_ja"], ["get", "name_en"], ""];
}

/**
 * Fetch the Henro Helper POI GeoJSON. Throws on non-OK response.
 */
export async function fetchHenroHelperPois(
  url: string,
): Promise<HenroHelperPoiFeatureCollection> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`henro helper pois fetch failed: ${res.status}`);
  return (await res.json()) as HenroHelperPoiFeatureCollection;
}

/**
 * Add one circle layer per POI kind (plus an optional symbol label layer for
 * the named kinds). All layers start hidden; the selector in main.ts applies
 * the master + per-kind toggles via layer visibility/filters.
 */
export function addHenroHelperPoiLayers(
  map: MapLibreMap,
  featureCollection: HenroHelperPoiFeatureCollection,
  beforeId: string | undefined,
): HenroHelperPoiGroup[] {
  map.addSource("henro-helper-pois", {
    type: "geojson",
    data: featureCollection,
    attribution: HENRO_HELPER_POI_ATTRIBUTION,
  });

  const groups: HenroHelperPoiGroup[] = [];
  for (const def of HENRO_HELPER_POI_DEFS) {
    const circle = `henro-helper-poi-${def.kind}`;
    const label = `henro-helper-poi-${def.kind}-label`;
    map.addLayer(
      {
        id: circle,
        type: "circle",
        source: "henro-helper-pois",
        filter: kindFilter(def.kind),
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
    const group: HenroHelperPoiGroup = {
      kind: def.kind,
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
          source: "henro-helper-pois",
          filter: kindFilter(def.kind),
          minzoom: 11,
          layout: {
            "text-field": labelTextField(def.kind),
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