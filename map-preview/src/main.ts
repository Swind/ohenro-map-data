import maplibregl, { type Map as MapLibreMap } from "maplibre-gl";
import { createMap, type HenroLayers } from "./map";

function toggleLayer(
  map: MapLibreMap,
  ids: string[],
  visible: boolean,
): void {
  const value = visible ? "visible" : "none";
  for (const id of ids) {
    if (map.getLayer(id)) {
      map.setLayoutProperty(id, "visibility", value);
    }
  }
}

function setupDebugPanel(map: MapLibreMap, henro: HenroLayers): void {
  const info = document.getElementById("debug-info") as HTMLPreElement;

  const renderInfo = (): void => {
    const c = map.getCenter();
    info.textContent = [
      `zoom: ${map.getZoom().toFixed(2)}`,
      `lat:  ${c.lat.toFixed(5)}`,
      `lon:  ${c.lng.toFixed(5)}`,
      `bearing: ${map.getBearing().toFixed(1)}`,
      `pitch: ${map.getPitch().toFixed(1)}`,
    ].join("\n");
  };

  map.on("move", renderInfo);
  map.on("zoom", renderInfo);
  renderInfo();

  const bindToggle = (
    id: string,
    fn: (visible: boolean) => void,
  ): void => {
    const el = document.getElementById(id) as HTMLInputElement | null;
    if (!el) return;
    el.addEventListener("change", () => fn(el.checked));
  };

  bindToggle("toggle-labels", (v) => toggleLayer(map, henro.labels, v));
  bindToggle("toggle-temples", (v) =>
    toggleLayer(map, [henro.templeMarker], v),
  );
  bindToggle("toggle-temple-labels", (v) =>
    toggleLayer(map, [henro.templeLabel], v),
  );
  bindToggle("toggle-route", (v) =>
    toggleLayer(map, [henro.routeCasing, henro.routeForeground], v),
  );
  bindToggle("toggle-lodging", (v) =>
    toggleLayer(map, [henro.lodgingMarker, henro.lodgingLabel], v),
  );
}

function setupClickPopup(map: MapLibreMap): void {
  map.on("click", (e) => {
    const features = map.queryRenderedFeatures(e.point);
    if (features.length === 0) return;

    const f = features[0];
    const g = f.geometry;
    const coords =
      g.type === "Point"
        ? `${g.coordinates[1].toFixed(5)}, ${g.coordinates[0].toFixed(5)}`
        : g.type;

    const props = f.properties ?? {};
    const propLines = Object.entries(props)
      .map(([k, v]) => `${k}: ${String(v)}`)
      .join("<br/>");

    const content = [
      `<b>${f.layer.id}</b>`,
      `id: ${f.id ?? "(none)"}`,
      `source: ${f.source}`,
      `source-layer: ${f.sourceLayer ?? "(geojson)"}`,
      `coords: ${coords}`,
      props && Object.keys(props).length > 0
        ? `<hr/>${propLines}`
        : "",
    ].join("<br/>");

    new maplibregl.Popup({ closeButton: true, maxWidth: "320px" })
      .setLngLat(e.lngLat)
      .setHTML(content)
      .addTo(map);
  });
}

const container = document.getElementById("map");
if (container) {
  const { map, henro } = createMap(container);
  setupDebugPanel(map, henro);
  setupClickPopup(map);
  (window as unknown as { __map: MapLibreMap }).__map = map;
}
