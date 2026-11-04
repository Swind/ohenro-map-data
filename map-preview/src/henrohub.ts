import type { Map as MapLibreMap } from "maplibre-gl";

// Henro Hub (henro.app) route network, digitised independently by Henro Hub
// (see datasets/henrohub/docs/henro-hub-comparison.md). Each line feature carries a stable
// `route_id` (hrn_/shikoku88-/hh26_*), `route_role`
// (canonical_shikoku88 / unique_alternative / transition_connector /
// continuity_fallback), `route_class` (colour) and `route_sets`. Groups are
// built by route_role (main / alternative / connector / fallback) with a
// per-class colouring applied via the shared line layer. This is Henro Hub's
// own linework, NOT the repo's Henro Helper extraction and NOT the official
// guiding line.
export interface HenrohubRoute {
  routeId: string;
  name: string;
  role: string;
  routeClass: string;
  hasGeometry: boolean;
}

export interface HenrohubGroup {
  role: string;
  label: string;
  color: string;
  routes: HenrohubRoute[];
}

export interface HenrohubFeature {
  type: "Feature";
  id?: string;
  geometry:
    | { type: "LineString"; coordinates: number[][] }
    | { type: "MultiLineString"; coordinates: number[][][] };
  properties: Record<string, unknown>;
}

export interface HenrohubFeatureCollection {
  type: "FeatureCollection";
  features: HenrohubFeature[];
}

export const HENROHUB_ATTRIBUTION =
  '<a href="https://henro.app">Henro Hub</a>';

export const HENROHUB_GROUP_DEFS: { role: string; label: string; color: string }[] = [
  { role: "canonical_shikoku88", label: "main (canonical 88)", color: "#1f8a5f" },
  { role: "unique_alternative", label: "alternative", color: "#b45309" },
  { role: "transition_connector", label: "connector", color: "#2563a6" },
  { role: "continuity_fallback", label: "fallback", color: "#6d6d6d" },
];

export const HENROHUB_CLASS_COLORS: Record<string, string> = {
  black: "#33302c",
  red: "#c0392b",
  green: "#2a7d4f",
  blue: "#2563a6",
  purple: "#7b3fa0",
  special: "#a33a3a",
};

/**
 * Fetch the henrohub routes GeoJSON. Throws on non-OK response.
 */
export async function fetchHenrohub(url: string): Promise<HenrohubFeatureCollection> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`henrohub fetch failed: ${res.status}`);
  return (await res.json()) as HenrohubFeatureCollection;
}

/**
 * Group line features by route_role for the selector tree. Group order follows
 * HENROHUB_GROUP_DEFS; routes keep source order.
 */
export function convertHenrohub(
  data: HenrohubFeatureCollection,
): { groups: HenrohubGroup[] } {
  if (!Array.isArray(data.features)) {
    throw new Error("henrohub features is not an array");
  }
  const byRole = new Map<string, HenrohubRoute[]>();
  for (const f of data.features) {
    const props = f.properties ?? {};
    if (props.kind !== "line") continue;
    const role = String(props.route_role ?? "other");
    const route: HenrohubRoute = {
      routeId: String(props.route_id ?? ""),
      name: String(props.name ?? props.route_id ?? ""),
      role,
      routeClass: String(props.route_class ?? "other"),
      hasGeometry: true,
    };
    if (!route.routeId) continue;
    if (!byRole.has(role)) byRole.set(role, []);
    byRole.get(role)!.push(route);
  }

  const groups: HenrohubGroup[] = [];
  for (const def of HENROHUB_GROUP_DEFS) {
    const routes = byRole.get(def.role) ?? [];
    groups.push({ role: def.role, label: def.label, color: def.color, routes });
  }
  const known = new Set(HENROHUB_GROUP_DEFS.map((d) => d.role));
  const other: HenrohubRoute[] = [];
  for (const [role, routes] of byRole) {
    if (!known.has(role)) other.push(...routes);
  }
  if (other.length > 0) {
    groups.push({ role: "other", label: "other", color: "#6d6d6d", routes: other });
  }
  return { groups };
}

/**
 * Add the shared henrohub GeoJSON source and the shared casing / line layers.
 * Layers start hidden; the selector in main.ts applies the master toggle +
 * per-route role + route_class filter.
 */
export function addHenrohubLayers(
  map: MapLibreMap,
  featureCollection: HenrohubFeatureCollection,
  beforeId: string | undefined,
): void {
  map.addSource("henrohub", {
    type: "geojson",
    data: featureCollection,
    attribution: HENROHUB_ATTRIBUTION,
  });

  map.addLayer(
    {
      id: "henrohub-casing",
      type: "line",
      source: "henrohub",
      filter: ["==", ["get", "kind"], "line"],
      layout: { "line-cap": "round", "line-join": "round" },
      paint: {
        "line-color": "#ffffff",
        "line-width": ["interpolate", ["linear"], ["zoom"], 8, 5.5, 14, 10],
        "line-opacity": 0.8,
      },
    },
    beforeId,
  );

  map.addLayer(
    {
      id: "henrohub-line",
      type: "line",
      source: "henrohub",
      filter: ["==", ["get", "kind"], "line"],
      layout: { "line-cap": "round", "line-join": "round" },
      paint: {
        "line-color": [
          "match", ["get", "route_class"],
          "black", HENROHUB_CLASS_COLORS.black,
          "red", HENROHUB_CLASS_COLORS.red,
          "green", HENROHUB_CLASS_COLORS.green,
          "blue", HENROHUB_CLASS_COLORS.blue,
          "purple", HENROHUB_CLASS_COLORS.purple,
          "special", HENROHUB_CLASS_COLORS.special,
          "#6d6d6d",
        ],
        "line-width": ["interpolate", ["linear"], ["zoom"], 8, 2.2, 14, 5],
        "line-opacity": 0.9,
      },
    },
    beforeId,
  );

  map.addLayer(
    {
      id: "henrohub-label",
      type: "symbol",
      source: "henrohub",
      filter: ["==", ["get", "kind"], "line"],
      layout: {
        "symbol-placement": "line",
        "text-field": ["coalesce", ["get", "name"], ""],
        "text-font": ["Noto Sans CJK JP Regular"],
        "text-size": 10,
        "text-letter-spacing": 0.05,
        "text-rotation-alignment": "map",
        "symbol-spacing": 600,
        visibility: "none",
      },
      paint: {
        "text-color": "#14532d",
        "text-halo-color": "#ffffff",
        "text-halo-width": 1.4,
      },
    },
    beforeId,
  );
}