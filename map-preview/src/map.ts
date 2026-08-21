import maplibregl, {
  type Map as MapLibreMap,
  type StyleSpecification,
} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { Protocol } from "pmtiles";
import basemapStyle from "./style/style.json";
import {
  addTrailRouteLayers,
  loadTrailRoutes,
  type TrailGroup,
} from "./trail";

export interface HenroLayers {
  labels: string[];
  templeMarker: string;
  templeLabel: string;
  routeCasing: string;
  routeForeground: string;
  henroyadoLodgingMarker: string;
  henroyadoLodgingLabel: string;
  min88LodgingMarker: string;
  min88LodgingLabel: string;
  trail: TrailGroup[];
  trailReady: Promise<TrailGroup[]>;
  trailFallback: string;
  trailFallbackLabel: string;
  trailPoi: string;
  trailPoiLabel: string;
  elevation: ElevationLayers;
}

export interface ElevationLayers {
  available: boolean;
  terrain: boolean;
  contours: boolean;
  colorRelief: string[];
  hillshade: string[];
  contour: string[];
  contourIndex: string[];
  contourLabel: string[];
}

const BASEMAP_LABEL_IDS = [
  "address_label",
  "roads_oneway",
  "roads_shields",
  "roads_labels_minor",
  "roads_labels_major",
  "water_waterway_label",
  "water_label_ocean",
  "water_label_lakes",
  "earth_label_islands",
  "pois",
  "places_subplace",
  "places_region",
  "places_locality",
  "places_country",
];

// Stable basemap layer IDs to insert elevation layers between (spec §11.3).
// color-relief + hillshade must render ABOVE the land fills (earth/landcover/
// landuse) or the opaque fills hide the shading; keep them below `water` so
// the sea stays unshaded.
const RELIEF_BEFORE = ["water", "roads_runway"]; // color-relief + hillshade
const CONTOUR_BEFORE = ["roads_tunnels_other_casing", "roads_runway"]; // contours
// Fallback target when the preferred beforeId is missing (first label layer).
const LABEL_FALLBACK = [
  "address_label",
  "places_subplace",
  "places_locality",
  "water_waterway_label",
  "earth_label_islands",
];

const GSI_ATTRIBUTION =
  '<a href="https://maps.gsi.go.jp">国土地理院</a> (GSI)';

function findInsertionPoint(
  map: MapLibreMap,
  candidates: string[],
  fallback: string[],
): string | undefined {
  for (const c of candidates) if (map.getLayer(c)) return c;
  for (const f of fallback) if (map.getLayer(f)) return f;
  return undefined;
}

function elevationEnabled(url: string | undefined): boolean {
  return Boolean(url && url.length > 0);
}

function addElevationSources(
  map: MapLibreMap,
  terrainUrl: string | undefined,
  contoursUrl: string | undefined,
): { terrain: boolean; contours: boolean } {
  const terrain = elevationEnabled(terrainUrl);
  if (terrain) {
    // Two source IDs over the same PMTiles URL: MapLibre warns if the same
    // source backs both terrain and color-relief, so use distinct IDs that
    // share the archive (no data duplication).
    map.addSource("elevation-dem-style", {
      type: "raster-dem",
      url: `pmtiles://${terrainUrl}`,
      encoding: "mapbox",
      tileSize: 256,
      attribution: GSI_ATTRIBUTION,
    });
    map.addSource("elevation-dem-terrain", {
      type: "raster-dem",
      url: `pmtiles://${terrainUrl}`,
      encoding: "mapbox",
      tileSize: 256,
      attribution: GSI_ATTRIBUTION,
    });
  }

  const contours = elevationEnabled(contoursUrl);
  if (contours) {
    map.addSource("elevation-contours", {
      type: "vector",
      url: `pmtiles://${contoursUrl}`,
    });
  }
  return { terrain, contours };
}

function addElevationLayers(
  map: MapLibreMap,
  elevation: ElevationLayers,
): void {
  if (!elevation.terrain) return;

  const colorReliefBefore = findInsertionPoint(map, RELIEF_BEFORE, LABEL_FALLBACK);
  map.addLayer(
    {
      id: "elevation-color-relief",
      type: "color-relief",
      source: "elevation-dem-style",
      layout: { visibility: "none" }, // hidden by default (spec §11.3)
      paint: {
        "color-relief-color": [
          "interpolate",
          ["linear"],
          ["elevation"],
          0, "#d9e8bd",
          100, "#b9d39a",
          300, "#d8c589",
          600, "#b8956e",
          1000, "#8c766b",
          1800, "#e2dfda",
        ],
      },
    },
    colorReliefBefore,
  );

  map.addLayer(
    {
      id: "elevation-hillshade",
      type: "hillshade",
      source: "elevation-dem-style",
      paint: {
        "hillshade-exaggeration": 0.5,
      },
    },
    colorReliefBefore,
  );

  if (!elevation.contours) return;
  const contourBefore = findInsertionPoint(map, CONTOUR_BEFORE, LABEL_FALLBACK);

  map.addLayer(
    {
      id: "elevation-contour-index",
      type: "line",
      source: "elevation-contours",
      "source-layer": "contours",
      filter: ["==", ["%", ["get", "elevation_m"], 100], 0],
      layout: { "line-join": "round", "line-cap": "round", visibility: "none" },
      paint: {
        "line-color": "#7a4a2b",
        "line-width": 1.4,
        "line-opacity": 0.75,
      },
    },
    contourBefore,
  );

  map.addLayer(
    {
      id: "elevation-contour",
      type: "line",
      source: "elevation-contours",
      "source-layer": "contours",
      filter: ["!=", ["%", ["get", "elevation_m"], 100], 0],
      layout: { "line-join": "round", "line-cap": "round", visibility: "none" },
      paint: {
        "line-color": "#b08d6f",
        "line-width": 0.7,
        "line-opacity": 0.55,
      },
    },
    contourBefore,
  );

  map.addLayer(
    {
      id: "elevation-contour-label",
      type: "symbol",
      source: "elevation-contours",
      "source-layer": "contours",
      filter: ["==", ["%", ["get", "elevation_m"], 100], 0],
      layout: {
        visibility: "none",
        "symbol-placement": "line",
        "text-field": ["to-string", ["get", "elevation_m"]],
        "text-font": ["Noto Sans Regular"],
        "text-size": 10,
        "text-letter-spacing": 0.05,
      },
      paint: {
        "text-color": "#5d3a1e",
        "text-halo-color": "#ffffff",
        "text-halo-width": 1.4,
      },
    },
    contourBefore,
  );
}

function applyHenroSources(map: MapLibreMap): void {
  const templesUrl = import.meta.env.VITE_TEMPLES_URL;
  if (templesUrl) {
    map.addSource("henro-temples", { type: "geojson", data: templesUrl });
  }

  const henroyadoLodgingUrl = import.meta.env.VITE_HENROYADO_LODGING_URL;
  if (henroyadoLodgingUrl) {
    map.addSource("henroyado-lodging", {
      type: "vector",
      url: `pmtiles://${henroyadoLodgingUrl}`,
    });
  }

  const min88LodgingUrl = import.meta.env.VITE_MIN88_LODGING_URL;
  if (min88LodgingUrl) {
    map.addSource("min88-lodging", {
      type: "vector",
      url: `pmtiles://${min88LodgingUrl}`,
    });
  }

  const henroUrl = import.meta.env.VITE_HENRO_URL;
  if (henroUrl) {
    map.addSource("henro-route", {
      type: "vector",
      url: `pmtiles://${henroUrl}`,
    });
  }

  const trailUrl = import.meta.env.VITE_TRAIL_URL;
  if (trailUrl) {
    map.addSource("trail", {
      type: "vector",
      url: `pmtiles://${trailUrl}`,
    });
  }
}

export function createMap(container: HTMLElement): {
  map: MapLibreMap;
  henro: HenroLayers;
} {
  const protocol = new Protocol();
  maplibregl.addProtocol("pmtiles", protocol.tile);

  const basemapUrl =
    import.meta.env.VITE_BASEMAP_URL ?? "/data/shikoku-basemap.pmtiles";

  const style = basemapStyle as unknown as StyleSpecification;
  style.sources = {
    ...style.sources,
    protomaps: {
      type: "vector",
      attribution:
        '<a href="https://github.com/protomaps/basemaps">Protomaps</a> © <a href="https://osm.org/copyright">OpenStreetMap</a>',
      url: `pmtiles://${basemapUrl}`,
    },
  };

  const params = new URLSearchParams(window.location.search);
  const lat = Number(params.get("lat"));
  const lon = Number(params.get("lon"));
  const zoom = Number(params.get("zoom"));

  const map = new maplibregl.Map({
    container,
    center: [lon || 134.206799, lat || 34.191403],
    zoom: zoom || 11,
    style,
  });

  const trailGroups: TrailGroup[] = [];
  let resolveTrail: (groups: TrailGroup[]) => void = () => undefined;
  const trailReady = new Promise<TrailGroup[]>((resolve) => {
    resolveTrail = resolve;
  });

  const terrainUrl = import.meta.env.VITE_TERRAIN_URL;
  const contoursUrl = import.meta.env.VITE_CONTOURS_URL;
  const elevation = {
    terrain: elevationEnabled(terrainUrl),
    contours: elevationEnabled(contoursUrl),
  };

  const elevationLayers: ElevationLayers = {
    available: elevation.terrain || elevation.contours,
    terrain: elevation.terrain,
    contours: elevation.contours,
    colorRelief: ["elevation-color-relief"],
    hillshade: ["elevation-hillshade"],
    contour: ["elevation-contour"],
    contourIndex: ["elevation-contour-index"],
    contourLabel: ["elevation-contour-label"],
  };

  map.addControl(new maplibregl.NavigationControl(), "top-left");

  // Elevation source/archive failures must not block basemap + Henro layers
  // (spec §11.5): log source id + error; toggles are left to the caller to
  // disable based on `elevation.available`.
  map.on("error", (e) => {
    const msg = e?.error?.message ?? String(e);
    if (
      terrainUrl &&
      (msg.includes("elevation-dem-style") ||
        msg.includes("elevation-dem-terrain") ||
        msg.includes(terrainUrl))
    ) {
      console.error("elevation terrain source error:", msg);
    }
    if (contoursUrl && (msg.includes("elevation-contours") || msg.includes(contoursUrl))) {
      console.error("elevation contours source error:", msg);
    }
  });

  map.on("load", async () => {
    // Sources/layers must be added after the style is loaded (calling
    // map.addSource before load throws "Style is not done loading").
    addElevationSources(map, terrainUrl, contoursUrl);
    if (elevation.terrain || elevation.contours) {
      addElevationLayers(map, elevationLayers);
    }

    applyHenroSources(map);

    if (map.getSource("henro-route")) {
      map.addLayer({
        id: "henro-route-casing",
        type: "line",
        source: "henro-route",
        "source-layer": "henro_routes",
        filter: ["==", ["get", "route_kind"], "henro_candidate"],
        layout: {
          "line-cap": "round",
          "line-join": "round",
        },
        paint: {
          "line-color": "#e8e0d0",
          "line-width": ["interpolate", ["linear"], ["zoom"], 8, 7, 14, 12],
          "line-opacity": 0.95,
        },
      });
      map.addLayer({
        id: "henro-route",
        type: "line",
        source: "henro-route",
        "source-layer": "henro_routes",
        filter: ["==", ["get", "route_kind"], "henro_candidate"],
        layout: {
          "line-cap": "round",
          "line-join": "round",
        },
        paint: {
          "line-color": "#8f4b32",
          "line-width": ["interpolate", ["linear"], ["zoom"], 8, 4, 14, 8],
          "line-opacity": 0.9,
        },
      });
    }

    if (map.getSource("trail")) {
      map.addLayer({
        id: "trail-pois",
        type: "circle",
        source: "trail",
        "source-layer": "shikoku_nature_trail_pois",
        minzoom: 10,
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 10, 3, 14, 6],
          "circle-color": ["match", ["get", "kind"], "tourism_spot", "#d9822b", "#4c7f68"],
          "circle-stroke-color": "#ffffff",
          "circle-stroke-width": 1.2,
        },
      });
      map.addLayer({
        id: "trail-poi-labels",
        type: "symbol",
        source: "trail",
        "source-layer": "shikoku_nature_trail_pois",
        minzoom: 10,
        layout: {
          "text-field": ["coalesce", ["get", "name"], ""],
          "text-font": ["Noto Sans Regular"],
          "text-size": 11,
          "text-offset": [0, 0.9],
          "text-anchor": "top",
          "text-max-width": 10,
        },
        paint: {
          "text-color": "#274c3a",
          "text-halo-color": "#ffffff",
          "text-halo-width": 1.3,
        },
      });

      const listUrl = import.meta.env.VITE_TRAIL_LIST_URL;
      if (listUrl) {
        try {
          trailGroups.push(...await loadTrailRoutes(listUrl));
          addTrailRouteLayers(map, trailGroups, "trail-pois");
        } catch (error) {
          console.error("trail route index error:", error);
        }
      }
      if (trailGroups.length === 0) {
        map.addLayer({
          id: "trail",
          type: "line",
          source: "trail",
          "source-layer": "shikoku_nature_trail",
          layout: { "line-cap": "round", "line-join": "round" },
          paint: {
            "line-color": "#2a7d4f",
            "line-width": ["interpolate", ["linear"], ["zoom"], 8, 2, 14, 5],
            "line-opacity": 0.9,
          },
        }, "trail-pois");
        map.addLayer({
          id: "trail-label",
          type: "symbol",
          source: "trail",
          "source-layer": "shikoku_nature_trail",
          layout: {
            "symbol-placement": "line",
            "text-field": ["coalesce", ["get", "name"], ""],
            "text-font": ["Noto Sans Regular"],
            "text-size": 11,
            "symbol-spacing": 400,
          },
          paint: {
            "text-color": "#1b5e38",
            "text-halo-color": "#ffffff",
            "text-halo-width": 1.4,
          },
        }, "trail-pois");
      }
    }
    resolveTrail(trailGroups);

    if (map.getSource("henroyado-lodging")) {
      map.addLayer({
        id: "henroyado-lodging",
        type: "circle",
        source: "henroyado-lodging",
        "source-layer": "lodging",
        minzoom: 6,
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 6, 4, 13, 7],
          "circle-color": "#b45309",
          "circle-stroke-color": "#ffffff",
          "circle-stroke-width": 1.5,
        },
      });

      map.addLayer({
        id: "henroyado-lodging-label",
        type: "symbol",
        source: "henroyado-lodging",
        "source-layer": "lodging",
        minzoom: 11,
        layout: {
          "text-field": ["coalesce", ["get", "name"], ""],
          "text-font": ["Noto Sans Regular"],
          "text-size": 11,
          "text-offset": [0, 1.1],
          "text-anchor": "top",
          "text-max-width": 8,
        },
        paint: {
          "text-color": "#6b3410",
          "text-halo-color": "#ffffff",
          "text-halo-width": 1.2,
        },
      });
    }

    if (map.getSource("min88-lodging")) {
      map.addLayer({
        id: "min88-lodging",
        type: "circle",
        source: "min88-lodging",
        "source-layer": "lodging",
        minzoom: 6,
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 6, 4, 13, 7],
          "circle-color": [
            "match", ["get", "lodging_type"],
            "hotel", "#2962a3",
            "ryokan", "#7451a8",
            "guesthouse", "#148f77",
            "temple_lodging", "#b7791f",
            "pilgrim_shelter", "#7b6d5d",
            "campground", "#4f772d",
            "#287d8e",
          ],
          "circle-stroke-color": "#ffffff",
          "circle-stroke-width": 1.5,
        },
      });
      map.addLayer({
        id: "min88-lodging-label",
        type: "symbol",
        source: "min88-lodging",
        "source-layer": "lodging",
        minzoom: 11,
        layout: {
          "text-field": ["coalesce", ["get", "name"], ""],
          "text-font": ["Noto Sans Regular"],
          "text-size": 11,
          "text-offset": [0, 1.1],
          "text-anchor": "top",
          "text-max-width": 8,
        },
        paint: {
          "text-color": "#174c55",
          "text-halo-color": "#ffffff",
          "text-halo-width": 1.2,
        },
      });
    }

    if (map.getSource("henro-temples")) {
      map.addLayer({
        id: "henro-temples",
        type: "circle",
        source: "henro-temples",
        minzoom: 0,
        paint: {
          "circle-radius": [
            "interpolate",
            ["linear"],
            ["zoom"],
            6,
            5,
            13,
            9,
          ],
          "circle-color": "#c0392b",
          "circle-stroke-color": "#ffffff",
          "circle-stroke-width": 2,
        },
      });

      map.addLayer({
        id: "henro-temple-label",
        type: "symbol",
        source: "henro-temples",
        minzoom: 9,
        layout: {
          "text-field": [
            "format",
            ["get", "number"],
            {},
            " ",
            {},
            ["get", "name_ja"],
            {},
          ],
          "text-font": ["Noto Sans Regular"],
          "text-size": 13,
          "text-offset": [0, 1.4],
          "text-anchor": "top",
          "text-max-width": 8,
        },
        paint: {
          "text-color": "#3a2a1e",
          "text-halo-color": "#ffffff",
          "text-halo-width": 1.5,
        },
      });
    }
  });

  const henro: HenroLayers = {
    labels: BASEMAP_LABEL_IDS,
    templeMarker: "henro-temples",
    templeLabel: "henro-temple-label",
    routeCasing: "henro-route-casing",
    routeForeground: "henro-route",
    henroyadoLodgingMarker: "henroyado-lodging",
    henroyadoLodgingLabel: "henroyado-lodging-label",
    min88LodgingMarker: "min88-lodging",
    min88LodgingLabel: "min88-lodging-label",
    trail: trailGroups,
    trailReady,
    trailFallback: "trail",
    trailFallbackLabel: "trail-label",
    trailPoi: "trail-pois",
    trailPoiLabel: "trail-poi-labels",
    elevation: elevationLayers,
  };

  return { map, henro };
}
