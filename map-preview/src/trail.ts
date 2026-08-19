import type { Map as MapLibreMap } from "maplibre-gl";

export interface TrailRoute {
  routeId: string;
  name: string | null;
  pref: string;
  kind: string;
  courseNumber: string | null;
  layerId: string;
  labelLayerId: string;
}

export interface TrailGroup {
  pref: string;
  routes: TrailRoute[];
}

export const TRAIL_SOURCE_LAYER = "shikoku_nature_trail";

const PREF_LABEL: Record<string, string> = {
  tokushima: "徳島",
  kagawa: "香川",
  ehime: "愛媛",
  kochi: "高知",
};

function layerIdForRoute(routeId: string): string {
  return `trail-${routeId}`;
}

function labelLayerIdForRoute(routeId: string): string {
  return `trail-label-${routeId}`;
}

export function prefLabel(pref: string): string {
  return PREF_LABEL[pref] ?? pref;
}

export interface TrailRouteData {
  route_id: string;
  name: string | null;
  pref: string;
  kind: string;
  course_number?: string | null;
}

/** Fetch the trail route index GeoJSON and return distinct routes grouped by pref. */
export async function loadTrailRoutes(
  url: string,
): Promise<TrailGroup[]> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`trail list fetch failed: ${res.status}`);
  const fc = (await res.json()) as {
    features: Array<{ properties: TrailRouteData }>;
  };

  const byKey = new Map<string, TrailRouteData>();
  for (const f of fc.features) {
    const p = f.properties;
    byKey.set(`${p.pref}\u0000${p.route_id}`, p);
  }

  const groups = new Map<string, TrailRoute[]>();
  for (const p of byKey.values()) {
    const list = groups.get(p.pref) ?? [];
    list.push({
      routeId: p.route_id,
      name: p.name,
      pref: p.pref,
      kind: p.kind,
      courseNumber: p.course_number ?? null,
      layerId: layerIdForRoute(p.route_id),
      labelLayerId: labelLayerIdForRoute(p.route_id),
    });
    groups.set(p.pref, list);
  }

  const prefOrder = ["tokushima", "kagawa", "ehime", "kochi"];
  return [...groups.entries()]
    .sort(
      (a, b) => prefOrder.indexOf(a[0]) - prefOrder.indexOf(b[0]),
    )
    .map(([pref, routes]) => ({
      pref,
      routes: routes.sort((a, b) =>
        (Number(a.courseNumber) || Infinity) - (Number(b.courseNumber) || Infinity) ||
        a.routeId.localeCompare(b.routeId)),
    }));
}

/**
 * Create one line layer per distinct route on the shared vector source, each
 * filtered to a single route_id so individual routes can be toggled.
 * Layers start hidden; the selector applies its initial checked state.
 */
export function addTrailRouteLayers(
  map: MapLibreMap,
  groups: TrailGroup[],
  beforeId: string | undefined,
): void {
  for (const group of groups) {
    for (const route of group.routes) {
      map.addLayer(
        {
          id: route.layerId,
          type: "line",
          source: "trail",
          "source-layer": TRAIL_SOURCE_LAYER,
          filter: ["==", ["get", "route_id"], route.routeId],
          layout: {
            "line-cap": "round",
            "line-join": "round",
            visibility: "none",
          },
          paint: {
            "line-color": "#2a7d4f",
            "line-width": ["interpolate", ["linear"], ["zoom"], 8, 2, 14, 5],
            "line-opacity": 0.9,
          },
        },
        beforeId,
      );

      map.addLayer(
        {
          id: route.labelLayerId,
          type: "symbol",
          source: "trail",
          "source-layer": TRAIL_SOURCE_LAYER,
          filter: ["==", ["get", "route_id"], route.routeId],
          layout: {
            "symbol-placement": "line",
            "text-field": ["coalesce", ["get", "name"], ""],
            "text-font": ["Noto Sans Regular"],
            "text-size": 11,
            "text-letter-spacing": 0.05,
            "text-rotation-alignment": "map",
            "symbol-spacing": 400,
            visibility: "none",
          },
          paint: {
            "text-color": "#1b5e38",
            "text-halo-color": "#ffffff",
            "text-halo-width": 1.4,
          },
        },
        beforeId,
      );
    }
  }
}

export function setTrailRouteVisible(
  map: MapLibreMap,
  route: TrailRoute,
  visible: boolean,
): void {
  const value = visible ? "visible" : "none";
  for (const id of [route.layerId, route.labelLayerId]) {
    if (map.getLayer(id)) {
      map.setLayoutProperty(id, "visibility", value);
    }
  }
}
