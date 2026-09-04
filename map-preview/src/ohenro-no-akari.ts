import type { Map as MapLibreMap } from "maplibre-gl";

// 遍路のあかり+ (jp.co.yonden.henronoakari, 四国電力) walking-route overlay,
// extracted from the web app bundle into
// output/ohenro-no-akari-routes/henro-no-akari-route.geojson. The native app
// embeds no route geometry; the web app's Leaflet map bundle (MapPage.js)
// carries the full walking route as inline GeoJSON. Features are 319
// road-level LineString segments (single route, no per-route names); Leaflet
// styling props `_color` / `_opacity` / `_weight` are preserved.
export interface OhenroNoAkariFeature {
  type: "Feature";
  geometry: { type: "LineString"; coordinates: number[][] };
  properties: Record<string, string | number | boolean | null>;
}

export interface OhenroNoAkariFeatureCollection {
  type: "FeatureCollection";
  features: OhenroNoAkariFeature[];
}

export const OHENRO_NO_AKARI_ATTRIBUTION =
  '<a href="https://app.henro-no-akari.com">遍路のあかり+（四国電力）</a>';

/**
 * Fetch the 遍路のあかり+ route GeoJSON. Throws on non-OK response.
 */
export async function fetchOhenroNoAkari(url: string): Promise<OhenroNoAkariFeatureCollection> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`ohenro-no-akari fetch failed: ${res.status}`);
  return (await res.json()) as OhenroNoAkariFeatureCollection;
}

/**
 * Validate the FeatureCollection shape. Returns it unchanged (all features are
 * one continuous walking route; there is no per-route selector).
 */
export function convertOhenroNoAkari(
  data: OhenroNoAkariFeatureCollection,
): OhenroNoAkariFeatureCollection {
  if (!Array.isArray(data.features)) {
    throw new Error("ohenro-no-akari features is not an array");
  }
  return data;
}

/**
 * Add the shared 遍路のあかり+ GeoJSON source and the casing / line layers.
 * The line color honors the source's own `_color` prop (the app renders the
 * route in blue). Layers start hidden; the selector in main.ts applies the
 * master toggle.
 */
export function addOhenroNoAkariLayers(
  map: MapLibreMap,
  featureCollection: OhenroNoAkariFeatureCollection,
  beforeId: string | undefined,
): void {
  map.addSource("ohenro-no-akari", {
    type: "geojson",
    data: featureCollection,
    attribution: OHENRO_NO_AKARI_ATTRIBUTION,
  });

  map.addLayer(
    {
      id: "ohenro-no-akari-casing",
      type: "line",
      source: "ohenro-no-akari",
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
      id: "ohenro-no-akari-line",
      type: "line",
      source: "ohenro-no-akari",
      layout: { "line-cap": "round", "line-join": "round", visibility: "none" },
      paint: {
        "line-color": ["coalesce", ["get", "_color"], "#0000ff"],
        "line-width": ["interpolate", ["linear"], ["zoom"], 8, 2.5, 14, 5.5],
        "line-opacity": ["coalesce", ["get", "_opacity"], 1],
      },
    },
    beforeId,
  );
}