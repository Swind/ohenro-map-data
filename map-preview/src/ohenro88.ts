import type { Map as MapLibreMap } from "maplibre-gl";

// OHenro 88 (com.sallyzzz.ohenroapp) route layers, extracted from the APK's
// bundled GeoJSON into output/ohenro88-routes/ohenro88-routes.geojson.
// Each line feature carries a stable `route_id` (e.g. OH88_1_2), the app's
// original `name` (e.g. "Walking (1-2)") and a `route_type`
// (main/skip/bekkaku/bekkaku_extra/extra). Temple points carry `temple_number`
// and a `bekkaku` flag.
export interface Ohenro88Route {
  routeId: string;
  name: string;
  routeType: string;
  hasGeometry: boolean;
}

export interface Ohenro88Group {
  routeType: string;
  label: string;
  color: string;
  routes: Ohenro88Route[];
}

export interface Ohenro88Feature {
  type: "Feature";
  id?: string;
  geometry:
    | { type: "LineString"; coordinates: number[][] }
    | { type: "MultiLineString"; coordinates: number[][][] }
    | { type: "Point"; coordinates: number[] };
  properties: Record<string, string | number | boolean | null>;
}

export interface Ohenro88FeatureCollection {
  type: "FeatureCollection";
  features: Ohenro88Feature[];
}

export const OHENRO88_ATTRIBUTION =
  '<a href="https://apkpure.com/ohenro-88/com.sallyzzz.ohenroapp">OHenro 88</a>';

export const OHENRO88_GROUP_DEFS: { routeType: string; label: string; color: string }[] = [
  { routeType: "main", label: "main walking (88 sections)", color: "#0e7a5f" },
  { routeType: "skip", label: "skip (shortcut)", color: "#b45309" },
  { routeType: "bekkaku", label: "bekkaku (direct)", color: "#7b3fa0" },
  { routeType: "bekkaku_extra", label: "bekkaku extra (loop)", color: "#2563a6" },
  { routeType: "extra", label: "extra", color: "#a33a3a" },
];

/**
 * Fetch the OHenro 88 routes GeoJSON. Throws on non-OK response.
 */
export async function fetchOhenro88(url: string): Promise<Ohenro88FeatureCollection> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`ohenro88 fetch failed: ${res.status}`);
  return (await res.json()) as Ohenro88FeatureCollection;
}

/**
 * Group line features by route_type (main/skip/bekkaku/bekkaku_extra/extra)
 * for the selector tree. Group order and route order follow the fixed
 * OHENRO88_GROUP_DEFS / source order.
 */
export function convertOhenro88(
  data: Ohenro88FeatureCollection,
): { groups: Ohenro88Group[] } {
  if (!Array.isArray(data.features)) {
    throw new Error("ohenro88 features is not an array");
  }
  const byType = new Map<string, Ohenro88Route[]>();
  for (const f of data.features) {
    const props = f.properties ?? {};
    if (props.kind !== "line") continue;
    const routeType = String(props.route_type ?? "other");
    const route: Ohenro88Route = {
      routeId: String(props.route_id ?? ""),
      name: String(props.name ?? props.route_id ?? ""),
      routeType,
      hasGeometry: true,
    };
    if (!route.routeId) continue;
    if (!byType.has(routeType)) byType.set(routeType, []);
    byType.get(routeType)!.push(route);
  }

  const groups: Ohenro88Group[] = [];
  for (const def of OHENRO88_GROUP_DEFS) {
    const routes = byType.get(def.routeType) ?? [];
    groups.push({ routeType: def.routeType, label: def.label, color: def.color, routes });
  }
  const known = new Set(OHENRO88_GROUP_DEFS.map((d) => d.routeType));
  const other: Ohenro88Route[] = [];
  for (const [routeType, routes] of byType) {
    if (!known.has(routeType)) other.push(...routes);
  }
  if (other.length > 0) {
    groups.push({ routeType: "other", label: "other", color: "#6d6d6d", routes: other });
  }
  return { groups };
}

/**
 * Add the shared ohenro88 GeoJSON source and the shared casing / line /
 * label / temple-point layers. Layers start hidden; the selector in main.ts
 * applies the master toggle + per-route route_id filter.
 */
export function addOhenro88Layers(
  map: MapLibreMap,
  featureCollection: Ohenro88FeatureCollection,
  beforeId: string | undefined,
): void {
  map.addSource("ohenro88", {
    type: "geojson",
    data: featureCollection,
    attribution: OHENRO88_ATTRIBUTION,
  });

  map.addLayer(
    {
      id: "ohenro88-casing",
      type: "line",
      source: "ohenro88",
      filter: ["==", ["get", "kind"], "line"],
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
      id: "ohenro88-line",
      type: "line",
      source: "ohenro88",
      filter: ["==", ["get", "kind"], "line"],
      layout: { "line-cap": "round", "line-join": "round", visibility: "none" },
      paint: {
        "line-color": [
          "match", ["get", "route_type"],
          "main", "#0e7a5f",
          "skip", "#b45309",
          "bekkaku", "#7b3fa0",
          "bekkaku_extra", "#2563a6",
          "extra", "#a33a3a",
          "#6d6d6d",
        ],
        "line-width": ["interpolate", ["linear"], ["zoom"], 8, 2.5, 14, 5.5],
        "line-opacity": 0.9,
      },
    },
    beforeId,
  );

  map.addLayer(
    {
      id: "ohenro88-label",
      type: "symbol",
      source: "ohenro88",
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

  map.addLayer(
    {
      id: "ohenro88-points",
      type: "circle",
      source: "ohenro88",
      filter: ["==", ["get", "kind"], "point"],
      minzoom: 8,
      layout: { visibility: "none" },
      paint: {
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 8, 3, 14, 6],
        "circle-color": [
          "match",
          ["to-string", ["get", "bekkaku"]],
          "true",
          "#a33a3a",
          "#c0392b",
        ],
        "circle-stroke-color": "#ffffff",
        "circle-stroke-width": 1.2,
      },
    },
    beforeId,
  );

  map.addLayer(
    {
      id: "ohenro88-point-labels",
      type: "symbol",
      source: "ohenro88",
      filter: ["==", ["get", "kind"], "point"],
      minzoom: 10,
      layout: {
        "text-field": ["coalesce", ["get", "name"], ""],
        "text-font": ["Noto Sans CJK JP Regular"],
        "text-size": 10,
        "text-offset": [0, 0.9],
        "text-anchor": "top",
        "text-max-width": 10,
        visibility: "none",
      },
      paint: {
        "text-color": "#7f1d1d",
        "text-halo-color": "#ffffff",
        "text-halo-width": 1.3,
      },
    },
    beforeId,
  );
}