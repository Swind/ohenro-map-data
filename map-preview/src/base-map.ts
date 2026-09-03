import maplibregl, {
  type Map as MapLibreMap,
  type StyleSpecification,
} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { Protocol } from "pmtiles";
import basemapStyle from "./style/style.json";

// Register the PMTiles protocol exactly once. MapLibre throws when the same
// protocol is added twice, and both the preview and the editor entry points
// (each building a map) share this module, so guard at module scope.
let pmtilesRegistered = false;
function ensurePmtilesProtocol(): void {
  if (pmtilesRegistered) return;
  const protocol = new Protocol();
  maplibregl.addProtocol("pmtiles", protocol.tile);
  pmtilesRegistered = true;
}

const DEFAULT_CENTER: [number, number] = [134.206799, 34.191403];
const DEFAULT_ZOOM = 11;

// Protomaps attribution, preserved on the cloned style's `protomaps` source.
const PROTOMAPS_ATTRIBUTION =
  '<a href="https://github.com/protomaps/basemaps">Protomaps</a> © <a href="https://osm.org/copyright">OpenStreetMap</a>';

/**
 * Create the shared basemap MapLibre map: register the PMTiles protocol,
 * clone the imported style and swap the `protomaps` source onto the configured
 * basemap archive, parse optional `lat`/`lon`/`zoom` query params, build the
 * map, and attach the navigation control.
 *
 * The imported style is cloned (structuredClone) before mutation so repeated
 * calls never share a mutated style object.
 */
export function createBaseMap(container: HTMLElement): MapLibreMap {
  ensurePmtilesProtocol();

  const basemapUrl =
    import.meta.env.VITE_BASEMAP_URL ?? "/data/shikoku-basemap.pmtiles";

  const style = structuredClone(basemapStyle) as unknown as StyleSpecification;
  // MapLibre GL JS requires the sprite URL to be absolute (it builds the
  // per-format URLs with `new URL()`); resolve the configured (root-relative)
  // sprite path against the current origin.
  const spritePath =
    import.meta.env.VITE_SPRITE_URL ?? "/data/app-map-assets/sprites/light";
  style.sprite = new URL(spritePath, window.location.href).href;
  style.glyphs =
    import.meta.env.VITE_GLYPHS_URL ??
    "/data/app-map-assets/fonts/{fontstack}/{range}.pbf";
  style.sources = {
    ...style.sources,
    protomaps: {
      type: "vector",
      attribution: PROTOMAPS_ATTRIBUTION,
      url: `pmtiles://${basemapUrl}`,
    },
  };

  const params = new URLSearchParams(window.location.search);
  // Absent params yield null (and blank params yield ""), both of which
  // Number() would coerce to 0; only parse a param when it is present and
  // non-blank so absent/blank fall back to defaults while an explicit "0"
  // (equator / zoom 0) stays valid.
  const queryParam = (name: string): number | undefined => {
    const raw = params.get(name);
    if (raw === null || raw.trim() === "") return undefined;
    const value = Number(raw);
    return Number.isFinite(value) ? value : undefined;
  };

  const center: [number, number] = [
    queryParam("lon") ?? DEFAULT_CENTER[0],
    queryParam("lat") ?? DEFAULT_CENTER[1],
  ];
  const zoomValue = queryParam("zoom") ?? DEFAULT_ZOOM;

  const map = new maplibregl.Map({
    container,
    center,
    zoom: zoomValue,
    style,
  });

  map.addControl(new maplibregl.NavigationControl(), "top-left");

  return map;
}
