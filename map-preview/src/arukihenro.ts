import type { Map as MapLibreMap } from "maplibre-gl";

// Schema v1 input interfaces (output/arukihenro-routes.json).
export interface ArukihenroLine {
  name: string | null;
  folder: string | null;
  source: string | null;
  coordinates: [number, number][];
}

export interface ArukihenroPoint {
  name: string | null;
  folder: string | null;
  category: string | null;
  coordinates: [number, number];
  photos?: string[] | null;
}

export interface ArukihenroMap {
  map_id: string;
  map_name: string | null;
  map_description: string | null;
  from_temple: number | null;
  to_temple: number | null;
  temple_range: number[] | null;
  lines: ArukihenroLine[];
  points: ArukihenroPoint[];
}

export interface ArukihenroRouteInput {
  id: string;
  region: string;
  title: string | null;
  url: string | null;
  from_temple: number | null;
  to_temple: number | null;
  temple_range: number[] | null;
  maps: ArukihenroMap[];
}

export interface ArukihenroData {
  schema_version: number;
  source?: unknown;
  summary?: unknown;
  warnings?: unknown;
  routes: ArukihenroRouteInput[];
}

// UI interfaces used by the map selector tree.
export interface ArukihenroRoute {
  routeId: string;
  title: string | null;
  region: string;
  hasGeometry: boolean;
}

export interface ArukihenroGroup {
  region: string;
  routes: ArukihenroRoute[];
}

export interface ArukihenroFeature {
  type: "Feature";
  id: string;
  geometry: { type: "LineString"; coordinates: [number, number][] } | { type: "Point"; coordinates: [number, number] };
  properties: Record<string, string | number | null>;
}

export interface ArukihenroFeatureCollection {
  type: "FeatureCollection";
  features: ArukihenroFeature[];
}

export const ARUKIHENRO_ATTRIBUTION =
  '<a href="https://ohenro.jp/blog/arukihenro/">歩き遍路 routes (arukihenro)</a>';

/**
 * Fetch the arukihenro normalized JSON. Throws on non-OK response.
 */
export async function fetchArukihenro(url: string): Promise<ArukihenroData> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`arukihenro fetch failed: ${res.status}`);
  return (await res.json()) as ArukihenroData;
}

/**
 * Flatten the normalized arukihenro JSON (routes -> maps -> lines/points) into
 * a single inline GeoJSON FeatureCollection plus route groups for the selector.
 *
 * Feature ids are deterministic: `${route.id}:${map.map_id}:M${mapIndex}:L${lineIndex}`
 * (or `:P...` for points). The map index guards against non-globally-unique
 * map_id values and duplicate maps within the same route.
 */
export function convertArukihenro(data: ArukihenroData): {
  featureCollection: ArukihenroFeatureCollection;
  groups: ArukihenroGroup[];
} {
  if (data.schema_version !== 1) {
    throw new Error(`arukihenro unsupported schema_version: ${data.schema_version}`);
  }
  if (!Array.isArray(data.routes)) {
    throw new Error("arukihenro routes is not an array");
  }

  const features: ArukihenroFeature[] = [];
  const groups: ArukihenroGroup[] = [];
  const groupByRegion = new Map<string, ArukihenroGroup>();

  for (const route of data.routes) {
    let hasGeometry = false;
    const maps = Array.isArray(route.maps) ? route.maps : [];
    maps.forEach((map, mapIndex) => {
      const mapRef = `${route.id}:${map?.map_id ?? "null"}:M${mapIndex}`;
      const base: Record<string, string | number | null> = {
        route_id: route.id,
        route_title: route.title ?? null,
        region: route.region ?? null,
        map_id: map?.map_id ?? null,
        map_name: map?.map_name ?? null,
        map_description: map?.map_description ?? null,
      };

      const lines = Array.isArray(map?.lines) ? map.lines : [];
      lines.forEach((line, lineIndex) => {
        if (!line || !Array.isArray(line.coordinates) || line.coordinates.length < 2) return;
        hasGeometry = true;
        features.push({
          type: "Feature",
          id: `${mapRef}:L${lineIndex}`,
          geometry: { type: "LineString", coordinates: line.coordinates },
          properties: {
            ...base,
            kind: "line",
            name: line.name ?? null,
            folder: line.folder ?? null,
            line_source: line.source ?? null,
          },
        });
      });

      const points = Array.isArray(map?.points) ? map.points : [];
      points.forEach((point, pointIndex) => {
        if (!point || !Array.isArray(point.coordinates) || point.coordinates.length < 2) return;
        hasGeometry = true;
        const photos = Array.isArray(point.photos)
          ? point.photos.filter((p): p is string => typeof p === "string")
          : [];
        features.push({
          type: "Feature",
          id: `${mapRef}:P${pointIndex}`,
          geometry: { type: "Point", coordinates: point.coordinates },
          properties: {
            ...base,
            kind: "point",
            name: point.name ?? null,
            folder: point.folder ?? null,
            category: point.category ?? null,
            photo_count: photos.length,
            photos: photos.length > 0 ? photos.join("\n") : null,
          },
        });
      });
    });

    let group = groupByRegion.get(route.region);
    if (!group) {
      group = { region: route.region, routes: [] };
      groupByRegion.set(route.region, group);
    }
    group.routes.push({
      routeId: route.id,
      title: route.title ?? null,
      region: route.region,
      hasGeometry,
    });
  }

  for (const group of groupByRegion.values()) {
    groups.push(group);
  }

  return { featureCollection: { type: "FeatureCollection", features }, groups };
}

/**
 * Add the shared arukihenro source (single inline GeoJSON FeatureCollection)
 * and the five shared layers: line casing, line, route-title line label,
 * point circles and point labels. Layers start hidden (visibility "none"); the
 * selector applies the route_id/kind filter and master toggles.
 */
export function addArukihenroLayers(
  map: MapLibreMap,
  featureCollection: ArukihenroFeatureCollection,
  beforeId: string | undefined,
): void {
  map.addSource("arukihenro", {
    type: "geojson",
    data: featureCollection,
    attribution: ARUKIHENRO_ATTRIBUTION,
  });

  map.addLayer(
    {
      id: "arukihenro-casing",
      type: "line",
      source: "arukihenro",
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
      id: "arukihenro-line",
      type: "line",
      source: "arukihenro",
      filter: ["==", ["get", "kind"], "line"],
      layout: { "line-cap": "round", "line-join": "round", visibility: "none" },
      paint: {
        "line-color": "#8e44ad",
        "line-width": ["interpolate", ["linear"], ["zoom"], 8, 2.5, 14, 5.5],
        "line-opacity": 0.9,
      },
    },
    beforeId,
  );

  map.addLayer(
    {
      id: "arukihenro-label",
      type: "symbol",
      source: "arukihenro",
      filter: ["==", ["get", "kind"], "line"],
      layout: {
        "symbol-placement": "line",
        "text-field": ["coalesce", ["get", "route_title"], ""],
        "text-font": ["Noto Sans CJK JP Regular"],
        "text-size": 11,
        "text-letter-spacing": 0.05,
        "text-rotation-alignment": "map",
        "symbol-spacing": 500,
        visibility: "none",
      },
      paint: {
        "text-color": "#5b2d75",
        "text-halo-color": "#ffffff",
        "text-halo-width": 1.4,
      },
    },
    beforeId,
  );

  map.addLayer(
    {
      id: "arukihenro-points",
      type: "circle",
      source: "arukihenro",
      filter: ["==", ["get", "kind"], "point"],
      minzoom: 10,
      layout: { visibility: "none" },
      paint: {
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 10, 3, 14, 6],
        "circle-color": [
          "match", ["get", "category"],
          "route_endpoint", "#8e44ad",
          "waymarker", "#7d3c98",
          "temple_related", "#c0392b",
          "lodging", "#744f8f",
          "food_shop", "#ca6f1e",
          "rest_area", "#148f77",
          "shrine", "#b7791f",
          "viewpoint", "#2980b9",
          "onsen", "#1abc9c",
          "#8e44ad",
        ],
        "circle-stroke-color": "#ffffff",
        "circle-stroke-width": 1.2,
      },
    },
    beforeId,
  );

  map.addLayer(
    {
      id: "arukihenro-point-labels",
      type: "symbol",
      source: "arukihenro",
      filter: ["==", ["get", "kind"], "point"],
      minzoom: 11,
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
        "text-color": "#5b2d75",
        "text-halo-color": "#ffffff",
        "text-halo-width": 1.3,
      },
    },
    beforeId,
  );
}
