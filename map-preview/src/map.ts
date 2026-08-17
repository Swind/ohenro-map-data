import maplibregl, {
  type Map as MapLibreMap,
  type StyleSpecification,
} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { Protocol } from "pmtiles";
import basemapStyle from "./style/style.json";

export interface HenroLayers {
  labels: string[];
  templeMarker: string;
  templeLabel: string;
  routeCasing: string;
  routeForeground: string;
  lodgingMarker: string;
  lodgingLabel: string;
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

function applyHenroSources(map: MapLibreMap): void {
  const templesUrl = import.meta.env.VITE_TEMPLES_URL;
  if (templesUrl) {
    map.addSource("henro-temples", { type: "geojson", data: templesUrl });
  }

  const lodgingUrl = import.meta.env.VITE_LODGING_URL;
  if (lodgingUrl) {
    map.addSource("lodging", { type: "geojson", data: lodgingUrl });
  }

  const henroUrl = import.meta.env.VITE_HENRO_URL;
  if (henroUrl) {
    map.addSource("henro-route", {
      type: "vector",
      url: `pmtiles://${henroUrl}`,
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

  map.addControl(new maplibregl.NavigationControl(), "top-left");

  map.on("load", () => {
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

    if (map.getSource("lodging")) {
      map.addLayer({
        id: "lodging",
        type: "circle",
        source: "lodging",
        minzoom: 0,
        paint: {
          "circle-radius": [
            "interpolate",
            ["linear"],
            ["zoom"],
            6,
            4,
            13,
            7,
          ],
          "circle-color": [
            "match",
            ["get", "subtype"],
            "hotel", "#e74c3c",
            "hostel", "#e67e22",
            "guest_house", "#16a085",
            "camp_site", "#8e44ad",
            "motel", "#95a5a6",
            "apartment", "#3498db",
            "chalet", "#2c3e50",
            "#7f8c8d",
          ],
          "circle-stroke-color": "#ffffff",
          "circle-stroke-width": 1.5,
        },
      });

      map.addLayer({
        id: "lodging-label",
        type: "symbol",
        source: "lodging",
        minzoom: 11,
        layout: {
          "text-field": ["coalesce", ["get", "name_ja"], ["get", "name"]],
          "text-font": ["Noto Sans Regular"],
          "text-size": 11,
          "text-offset": [0, 1.1],
          "text-anchor": "top",
          "text-max-width": 8,
        },
        paint: {
          "text-color": "#3a2a1e",
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
    lodgingMarker: "lodging",
    lodgingLabel: "lodging-label",
  };

  return { map, henro };
}
