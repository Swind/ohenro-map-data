import { type Map as MapLibreMap } from "maplibre-gl";
import { createBaseMap } from "./base-map";
import {
  addTrailRouteLayers,
  loadTrailRoutes,
  type TrailGroup,
} from "./trail";
import {
  addArukihenroLayers,
  convertArukihenro,
  fetchArukihenro,
  type ArukihenroGroup,
} from "./arukihenro";
import {
  addHenroHelperLayers,
  fetchHenroHelper,
  type HenroHelperGroup,
  type HenroHelperItinerarySet,
} from "./henro-helper";
import {
  addHenroHelperPoiLayers,
  fetchHenroHelperPois,
  type HenroHelperPoiGroup,
} from "./henro-helper-pois";
import {
  addOhenro88Layers,
  convertOhenro88,
  fetchOhenro88,
  type Ohenro88Group,
} from "./ohenro88";
import {
  addOhenroNoAkariLayers,
  convertOhenroNoAkari,
  fetchOhenroNoAkari,
} from "./ohenro-no-akari";
import {
  addInfoPoiLayers,
  fetchInfoPois,
  type InfoPoiGroup,
} from "./info-pois";
import {
  addHenrohubLayers,
  convertHenrohub,
  fetchHenrohub,
  type HenrohubGroup,
} from "./henrohub";

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
  mizutaniAvailable: boolean;
  mizutaniRouteCasing: string;
  mizutaniRoute: string;
  mizutaniPoi: string;
  mizutaniPoiLabel: string;
  sekaiisanAvailable: boolean;
  sekaiisanRouteCasing: string;
  sekaiisanRoute: string;
  arukihenroAvailable: boolean;
  arukihenroReady: Promise<ArukihenroGroup[]>;
  arukihenro: ArukihenroGroup[];
  arukihenroLineCasing: string;
  arukihenroLine: string;
  arukihenroLabel: string;
  arukihenroPoints: string;
  arukihenroPointLabels: string;
  henroHelperAvailable: boolean;
  henroHelper: HenroHelperData;
  henroHelperReady: Promise<HenroHelperData>;
  henroHelperPoisAvailable: boolean;
  henroHelperPois: HenroHelperPoiGroup[];
  henroHelperPoisReady: Promise<HenroHelperPoiGroup[]>;
  infoPoisAvailable: boolean;
  infoPois: InfoPoiGroup[];
  infoPoisReady: Promise<InfoPoiGroup[]>;
  ohenro88Available: boolean;
  ohenro88Ready: Promise<Ohenro88Group[]>;
  ohenro88: Ohenro88Group[];
  ohenro88Casing: string;
  ohenro88Line: string;
  ohenro88Label: string;
  ohenro88Points: string;
  ohenro88PointLabels: string;
  ohenroNoAkariAvailable: boolean;
  ohenroNoAkariCasing: string;
  ohenroNoAkariLine: string;
  henrohubAvailable: boolean;
  henrohubReady: Promise<HenrohubGroup[]>;
  henrohub: HenrohubGroup[];
  henrohubCasing: string;
  henrohubLine: string;
  henrohubLabel: string;
  elevation: ElevationLayers;
}

export interface HenroHelperLayers {
  available: boolean;
  ready: Promise<HenroHelperData>;
  data: HenroHelperData;
}

export interface HenroHelperData {
  groups: HenroHelperGroup[];
  itinerarySets: HenroHelperItinerarySet[];
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

// Official 四国遍路世界遺産登録推進協議会 (88sekaiisan.org) guiding lines,
// from the KML archives normalized in the sekaiisan_henro pipeline. These are
// raw source linework (source edges), NOT inferred corridors / navigation.
const SEKAIISAN_ATTRIBUTION =
  '<a href="https://88sekaiisan.org/">四国遍路世界遺産登録推進協議会</a>';

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
      layout: { visibility: "none" }, // hidden by default (spec §11.3)
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
        "text-font": ["Noto Sans CJK JP Regular"],
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

  const mizutaniUrl = import.meta.env.VITE_MIZUTANI_HENRO_URL;
  if (mizutaniUrl) {
    map.addSource("mizutani-henro", {
      type: "vector",
      url: `pmtiles://${mizutaniUrl}`,
    });
  }

  const sekaiisanUrl = import.meta.env.VITE_SEKAIISAN_HENRO_URL;
  if (sekaiisanUrl) {
    map.addSource("sekaiisan-henro", {
      type: "geojson",
      data: sekaiisanUrl,
      attribution: SEKAIISAN_ATTRIBUTION,
    });
  }
}

export function createMap(container: HTMLElement): {
  map: MapLibreMap;
  henro: HenroLayers;
} {
  const map = createBaseMap(container);

  // Opt-in symbol smoke mode: renders a tiny inline label layer so glyphs and
  // the townhall icon can be verified against the local assets.
  const params = new URLSearchParams(window.location.search);
  const symbolSmoke = params.get("symbolSmoke") === "1";
  if (symbolSmoke) {
    // Without explicit lat/lon/zoom, frame the two smoke points.
    const noExplicitPosition =
      params.get("lat") === null &&
      params.get("lon") === null &&
      params.get("zoom") === null;
    if (noExplicitPosition) {
      map.jumpTo({ center: [132.765, 33.839], zoom: 13 });
    }
  }

  const trailGroups: TrailGroup[] = [];
  let resolveTrail: (groups: TrailGroup[]) => void = () => undefined;
  const trailReady = new Promise<TrailGroup[]>((resolve) => {
    resolveTrail = resolve;
  });

  const arukihenroGroups: ArukihenroGroup[] = [];
  let resolveArukihenro: (groups: ArukihenroGroup[]) => void = () => undefined;
  const arukihenroReady = new Promise<ArukihenroGroup[]>((resolve) => {
    resolveArukihenro = resolve;
  });

  const henroHelperGroups: HenroHelperGroup[] = [];
  const henroHelperSets: HenroHelperItinerarySet[] = [];
  let resolveHenroHelper: (data: HenroHelperData) => void = () => undefined;
  const henroHelperReady = new Promise<HenroHelperData>((resolve) => {
    resolveHenroHelper = resolve;
  });

  const henroHelperPoiGroups: HenroHelperPoiGroup[] = [];
  let resolveHenroHelperPois: (groups: HenroHelperPoiGroup[]) => void = () => undefined;
  const henroHelperPoisReady = new Promise<HenroHelperPoiGroup[]>((resolve) => {
    resolveHenroHelperPois = resolve;
  });

  const infoPoiGroups: InfoPoiGroup[] = [];
  let resolveInfoPois: (groups: InfoPoiGroup[]) => void = () => undefined;
  const infoPoisReady = new Promise<InfoPoiGroup[]>((resolve) => {
    resolveInfoPois = resolve;
  });

  const ohenro88Groups: Ohenro88Group[] = [];
  let resolveOhenro88: (groups: Ohenro88Group[]) => void = () => undefined;
  const ohenro88Ready = new Promise<Ohenro88Group[]>((resolve) => {
    resolveOhenro88 = resolve;
  });

  const henrohubGroups: HenrohubGroup[] = [];
  let resolveHenrohub: (groups: HenrohubGroup[]) => void = () => undefined;
  const henrohubReady = new Promise<HenrohubGroup[]>((resolve) => {
    resolveHenrohub = resolve;
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
    if (symbolSmoke) {
      map.addSource("symbol-smoke", {
        type: "geojson",
        data: {
          type: "FeatureCollection",
          features: [
            {
              type: "Feature",
              geometry: { type: "Point", coordinates: [132.765, 33.839] },
              properties: { label: "TEST" },
            },
            {
              type: "Feature",
              geometry: { type: "Point", coordinates: [132.774, 33.839] },
              properties: { label: "松山市" },
            },
          ],
        },
      });
      map.addLayer({
        id: "symbol-smoke-label",
        type: "symbol",
        source: "symbol-smoke",
        layout: {
          "text-field": ["get", "label"],
          "text-font": ["Noto Sans CJK JP Regular"],
          "text-size": 14,
          "icon-image": "townhall",
          "icon-allow-overlap": true,
          "text-allow-overlap": true,
          "text-anchor": "top",
          "text-offset": [0, 1],
        },
        paint: {
          "text-color": "#111111",
          "text-halo-color": "#ffffff",
          "text-halo-width": 1.5,
        },
      });
    }

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
          visibility: "none",
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
          visibility: "none",
        },
        paint: {
          "line-color": "#8f4b32",
          "line-width": ["interpolate", ["linear"], ["zoom"], 8, 4, 14, 8],
          "line-opacity": 0.9,
        },
      });
    }

    if (map.getSource("mizutani-henro")) {
      map.addLayer({
        id: "mizutani-henro-route-casing",
        type: "line",
        source: "mizutani-henro",
        "source-layer": "mizutani_henro_routes",
        layout: { "line-cap": "round", "line-join": "round", visibility: "none" },
        paint: {
          "line-color": "#ffffff",
          "line-width": ["interpolate", ["linear"], ["zoom"], 8, 3.5, 14, 7],
          "line-opacity": 0.8,
        },
      });
      map.addLayer({
        id: "mizutani-henro-route",
        type: "line",
        source: "mizutani-henro",
        "source-layer": "mizutani_henro_routes",
        layout: { "line-cap": "round", "line-join": "round", visibility: "none" },
        paint: {
          "line-color": ["coalesce", ["get", "color"], "#765b30"],
          "line-width": ["interpolate", ["linear"], ["zoom"], 8, 2, 14, 4.5],
          "line-opacity": 0.9,
        },
      });
      map.addLayer({
        id: "mizutani-henro-pois",
        type: "circle",
        source: "mizutani-henro",
        "source-layer": "mizutani_henro_pois",
        minzoom: 10,
        layout: { visibility: "none" },
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 10, 3, 14, 6],
          "circle-color": [
            "match", ["get", "category"],
            "temple", "#8e3b37", "lodging", "#744f8f", "food", "#ca6f1e",
            "shop_supply", "#386f50", "transport", "#266ca8", "wayfinding", "#765b30",
            "warning_hazard", "#c5443e", "water_toilet_rest", "#31889c",
            "experience_note", "#7763aa", "#6d6d6d",
          ],
          "circle-stroke-color": "#ffffff",
          "circle-stroke-width": 1.2,
        },
      });
      map.addLayer({
        id: "mizutani-henro-pois-labels",
        type: "symbol",
        source: "mizutani-henro",
        "source-layer": "mizutani_henro_pois",
        minzoom: 10,
        layout: {
          "text-field": ["coalesce", ["get", "name"], ""],
          "text-font": ["Noto Sans CJK JP Regular"],
          "text-size": 11,
          "text-offset": [0, 0.9],
          "text-anchor": "top",
          "text-max-width": 10,
          visibility: "none",
        },
        paint: {
          "text-color": "#5d4a2a",
          "text-halo-color": "#ffffff",
          "text-halo-width": 1.3,
        },
      });
    }

    if (map.getSource("sekaiisan-henro")) {
      map.addLayer({
        id: "sekaiisan-henro-route-casing",
        type: "line",
        source: "sekaiisan-henro",
        layout: { "line-cap": "round", "line-join": "round", visibility: "none" },
        paint: {
          "line-color": "#e0eaf8",
          "line-width": ["interpolate", ["linear"], ["zoom"], 8, 6, 14, 11],
          "line-opacity": 0.9,
        },
      });
      map.addLayer({
        id: "sekaiisan-henro-route",
        type: "line",
        source: "sekaiisan-henro",
        layout: { "line-cap": "round", "line-join": "round", visibility: "none" },
        paint: {
          "line-color": "#1f62c4",
          "line-width": ["interpolate", ["linear"], ["zoom"], 8, 3.5, 14, 7.5],
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
        layout: { visibility: "none" },
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
          "text-font": ["Noto Sans CJK JP Regular"],
          "text-size": 11,
          "text-offset": [0, 0.9],
          "text-anchor": "top",
          "text-max-width": 10,
          visibility: "none",
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
          layout: { "line-cap": "round", "line-join": "round", visibility: "none" },
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
            "text-font": ["Noto Sans CJK JP Regular"],
            "text-size": 11,
            "symbol-spacing": 400,
            visibility: "none",
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
        layout: { visibility: "none" },
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
          "text-font": ["Noto Sans CJK JP Regular"],
          "text-size": 11,
          "text-offset": [0, 1.1],
          "text-anchor": "top",
          "text-max-width": 8,
          visibility: "none",
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
        layout: { visibility: "none" },
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
          "text-font": ["Noto Sans CJK JP Regular"],
          "text-size": 11,
          "text-offset": [0, 1.1],
          "text-anchor": "top",
          "text-max-width": 8,
          visibility: "none",
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
          "text-font": ["Noto Sans CJK JP Regular"],
          "text-size": 13,
          "text-offset": [0, 1.4],
          "text-anchor": "top",
          "text-max-width": 8,
          visibility: "none",
        },
        paint: {
          "text-color": "#3a2a1e",
          "text-halo-color": "#ffffff",
          "text-halo-width": 1.5,
        },
      });
    }

    const henroHelperUrl = import.meta.env.VITE_HENRO_HELPER_URL;
    if (henroHelperUrl) {
      void (async () => {
        try {
          const data = await fetchHenroHelper(henroHelperUrl);
          const beforeId = findInsertionPoint(
            map,
            [
              "henro-route-casing",
              "sekaiisan-henro-route-casing",
              "mizutani-henro-route-casing",
            ],
            LABEL_FALLBACK,
          );
          const { groups, itinerarySets } = addHenroHelperLayers(map, data, beforeId);
          henroHelperGroups.push(...groups);
          henroHelperSets.push(...itinerarySets);
        } catch (error) {
          console.error("henro helper load error:", error);
        } finally {
          resolveHenroHelper({ groups: henroHelperGroups, itinerarySets: henroHelperSets });
        }
      })();
    } else {
      resolveHenroHelper({ groups: henroHelperGroups, itinerarySets: henroHelperSets });
    }

    // Henro Helper POI markers (temples / toilets / convenience / rest areas /
    // accommodations / okunoin-bangai ...): same APK, fetched separately from
    // the route geometry. One circle layer (+ label for named kinds) per kind.
    const henroHelperPoisUrl = import.meta.env.VITE_HENRO_HELPER_POIS_URL;
    if (henroHelperPoisUrl) {
      void (async () => {
        try {
          const data = await fetchHenroHelperPois(henroHelperPoisUrl);
          const beforeId = findInsertionPoint(
            map,
            [
              "henro-route-casing",
              "sekaiisan-henro-route-casing",
              "mizutani-henro-route-casing",
            ],
            LABEL_FALLBACK,
          );
          henroHelperPoiGroups.push(...addHenroHelperPoiLayers(map, data, beforeId));
        } catch (error) {
          console.error("henro helper pois load error:", error);
        } finally {
          resolveHenroHelperPois(henroHelperPoiGroups);
        }
      })();
    } else {
      resolveHenroHelperPois(henroHelperPoiGroups);
    }

    // Consolidated information POIs (toilets / water / food / shops / transport
    // / onsen / sights / wayfinding ...): unified `category` taxonomy from
    // scripts/build-info-pois.py. One circle layer (+ label) per category.
    const infoPoisUrl = import.meta.env.VITE_INFO_POIS_URL;
    if (infoPoisUrl) {
      void (async () => {
        try {
          const data = await fetchInfoPois(infoPoisUrl);
          const beforeId = findInsertionPoint(
            map,
            [
              "henro-route-casing",
              "sekaiisan-henro-route-casing",
              "mizutani-henro-route-casing",
            ],
            LABEL_FALLBACK,
          );
          infoPoiGroups.push(...addInfoPoiLayers(map, data, beforeId));
        } catch (error) {
          console.error("info pois load error:", error);
        } finally {
          resolveInfoPois(infoPoiGroups);
        }
      })();
    } else {
      resolveInfoPois(infoPoiGroups);
    }

    // 歩き遍路 routes: fetch ~5MB normalized JSON (ohenro.jp personal hand-drawn
    // + Google navigation reference lines) as an inline GeoJSON source. Runs
    // non-blocking so it never delays the static lodging/temple layers above.
    const arukihenroUrl = import.meta.env.VITE_ARUKIHENRO_URL;
    if (arukihenroUrl) {
      void (async () => {
        try {
          const data = await fetchArukihenro(arukihenroUrl);
          const { featureCollection, groups } = convertArukihenro(data);
          const beforeId = findInsertionPoint(
            map,
            ["henro-route-casing", "sekaiisan-henro-route-casing"],
            LABEL_FALLBACK,
          );
          addArukihenroLayers(map, featureCollection, beforeId);
          arukihenroGroups.push(...groups);
        } catch (error) {
          console.error("arukihenro load error:", error);
        } finally {
          resolveArukihenro(arukihenroGroups);
        }
      })();
    } else {
      resolveArukihenro(arukihenroGroups);
    }

    // OHenro 88 routes: fetch the per-route GeoJSON extracted from the APK
    // (datasets/ohenro88/output/ohenro88-routes.geojson). Adds shared layers
    // + per-route groups for the selector. Non-blocking.
    const ohenro88Url = import.meta.env.VITE_OHENRO88_URL;
    if (ohenro88Url) {
      void (async () => {
        try {
          const data = await fetchOhenro88(ohenro88Url);
          const { groups } = convertOhenro88(data);
          const beforeId = findInsertionPoint(
            map,
            ["henro-route-casing", "sekaiisan-henro-route-casing", "arukihenro-casing"],
            LABEL_FALLBACK,
          );
          addOhenro88Layers(map, data, beforeId);
          ohenro88Groups.push(...groups);
        } catch (error) {
          console.error("ohenro88 load error:", error);
        } finally {
          resolveOhenro88(ohenro88Groups);
        }
      })();
    } else {
      resolveOhenro88(ohenro88Groups);
    }

    // 遍路のあかり+ routes: fetch the walking route extracted from the web
    // app bundle (datasets/ohenro_no_akari/output/henro-no-akari-route.geojson).
    // Adds shared casing + line layers (source color). Non-blocking.
    const ohenroNoAkariUrl = import.meta.env.VITE_OHENRO_NO_AKARI_URL;
    if (ohenroNoAkariUrl) {
      void (async () => {
        try {
          const data = await fetchOhenroNoAkari(ohenroNoAkariUrl);
          convertOhenroNoAkari(data);
          const beforeId = findInsertionPoint(
            map,
            ["henro-route-casing", "sekaiisan-henro-route-casing", "mizutani-henro-route-casing"],
            LABEL_FALLBACK,
          );
          addOhenroNoAkariLayers(map, data, beforeId);
        } catch (error) {
          console.error("ohenro-no-akari load error:", error);
        }
      })();
    }

    // Henro Hub (henro.app) routes: Henro Hub's own digitised network, grouped
    // by route_role. Fetched as a single inline GeoJSON source (13.5MB). This
    // is NOT the repo's Henro Helper extraction and NOT the official guiding
    // line. Non-blocking.
    const henrohubUrl = import.meta.env.VITE_HENROHUB_URL;
    if (henrohubUrl) {
      void (async () => {
        try {
          const data = await fetchHenrohub(henrohubUrl);
          const { groups } = convertHenrohub(data);
          const beforeId = findInsertionPoint(
            map,
            ["henro-route-casing", "sekaiisan-henro-route-casing", "ohenro88-casing"],
            LABEL_FALLBACK,
          );
          addHenrohubLayers(map, data, beforeId);
          henrohubGroups.push(...groups);
        } catch (error) {
          console.error("henrohub load error:", error);
        } finally {
          resolveHenrohub(henrohubGroups);
        }
      })();
    } else {
      resolveHenrohub(henrohubGroups);
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
    mizutaniAvailable: Boolean(import.meta.env.VITE_MIZUTANI_HENRO_URL),
    mizutaniRouteCasing: "mizutani-henro-route-casing",
    mizutaniRoute: "mizutani-henro-route",
    mizutaniPoi: "mizutani-henro-pois",
    mizutaniPoiLabel: "mizutani-henro-pois-labels",
    sekaiisanAvailable: Boolean(import.meta.env.VITE_SEKAIISAN_HENRO_URL),
    sekaiisanRouteCasing: "sekaiisan-henro-route-casing",
    sekaiisanRoute: "sekaiisan-henro-route",
    arukihenroAvailable: Boolean(import.meta.env.VITE_ARUKIHENRO_URL),
    arukihenroReady,
    arukihenro: arukihenroGroups,
    arukihenroLineCasing: "arukihenro-casing",
    arukihenroLine: "arukihenro-line",
    arukihenroLabel: "arukihenro-label",
    arukihenroPoints: "arukihenro-points",
    arukihenroPointLabels: "arukihenro-point-labels",
    henroHelperAvailable: Boolean(import.meta.env.VITE_HENRO_HELPER_URL),
    henroHelper: { groups: henroHelperGroups, itinerarySets: henroHelperSets },
    henroHelperReady,
    henroHelperPoisAvailable: Boolean(import.meta.env.VITE_HENRO_HELPER_POIS_URL),
    henroHelperPois: henroHelperPoiGroups,
    henroHelperPoisReady,
    infoPoisAvailable: Boolean(import.meta.env.VITE_INFO_POIS_URL),
    infoPois: infoPoiGroups,
    infoPoisReady,
    ohenro88Available: Boolean(import.meta.env.VITE_OHENRO88_URL),
    ohenro88Ready,
    ohenro88: ohenro88Groups,
    ohenro88Casing: "ohenro88-casing",
    ohenro88Line: "ohenro88-line",
    ohenro88Label: "ohenro88-label",
    ohenro88Points: "ohenro88-points",
    ohenro88PointLabels: "ohenro88-point-labels",
    ohenroNoAkariAvailable: Boolean(import.meta.env.VITE_OHENRO_NO_AKARI_URL),
    ohenroNoAkariCasing: "ohenro-no-akari-casing",
    ohenroNoAkariLine: "ohenro-no-akari-line",
    henrohubAvailable: Boolean(import.meta.env.VITE_HENROHUB_URL),
    henrohubReady,
    henrohub: henrohubGroups,
    henrohubCasing: "henrohub-casing",
    henrohubLine: "henrohub-line",
    henrohubLabel: "henrohub-label",
    elevation: elevationLayers,
  };

  return { map, henro };
}
