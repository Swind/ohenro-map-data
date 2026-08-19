import maplibregl, { type Map as MapLibreMap } from "maplibre-gl";
import { createMap, type HenroLayers } from "./map";
import { prefLabel, type TrailRoute } from "./trail";

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

  // Disable elevation toggles when no elevation source was configured, so the
  // user sees they are unavailable (spec §11.5).
  const elevation = henro.elevation;
  for (const id of [
    "toggle-elevation-color",
    "toggle-hillshade",
    "toggle-contours",
    "toggle-contour-labels",
    "toggle-terrain",
  ]) {
    const el = document.getElementById(id) as HTMLInputElement | null;
    if (el && !elevation.available) {
      el.disabled = true;
      el.checked = false;
      el.parentElement?.classList.add("disabled");
    }
  }

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
  const routeCheckboxes = new Map<TrailRoute, HTMLInputElement>();
  const applyTrailVisibility = (): void => {
    const master = (document.getElementById("toggle-trail") as HTMLInputElement).checked;
    const labels = (document.getElementById("toggle-trail-labels") as HTMLInputElement).checked;
    const showPois = (document.getElementById("toggle-trail-pois") as HTMLInputElement).checked;
    if (routeCheckboxes.size === 0) {
      toggleLayer(map, [henro.trailFallback], master);
      toggleLayer(map, [henro.trailFallbackLabel], master && labels);
      toggleLayer(map, [henro.trailPoi, henro.trailPoiLabel], master && showPois);
      for (const id of [henro.trailPoi, henro.trailPoiLabel]) {
        if (map.getLayer(id)) map.setFilter(id, null);
      }
    }
    const visibleRouteIds: string[] = [];
    for (const [route, checkbox] of routeCheckboxes) {
      toggleLayer(map, [route.layerId], master && checkbox.checked);
      toggleLayer(map, [route.labelLayerId], master && labels && checkbox.checked);
      if (checkbox.checked) visibleRouteIds.push(route.routeId);
    }
    if (routeCheckboxes.size > 0) {
      toggleLayer(map, [henro.trailPoi, henro.trailPoiLabel], master && showPois);
      for (const id of [henro.trailPoi, henro.trailPoiLabel]) {
        if (map.getLayer(id)) {
          map.setFilter(id, [
            "in",
            ["get", "route_id"],
            ["literal", visibleRouteIds],
          ]);
        }
      }
    }
  };
  bindToggle("toggle-trail", applyTrailVisibility);
  bindToggle("toggle-trail-labels", applyTrailVisibility);
  bindToggle("toggle-trail-pois", applyTrailVisibility);

  void henro.trailReady.then((groups) => {
    const container = document.getElementById("trail-routes");
    if (!container) return;
    for (const group of groups) {
      const details = document.createElement("details");
      const summary = document.createElement("summary");
      summary.textContent = `${prefLabel(group.pref)} (${group.routes.length})`;
      details.append(summary);
      for (const route of group.routes) {
        const label = document.createElement("label");
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.checked = true;
        checkbox.addEventListener("change", applyTrailVisibility);
        routeCheckboxes.set(route, checkbox);
        label.append(checkbox, ` ${route.courseNumber ?? "-"} ${route.name ?? route.routeId}`);
        details.append(label);
      }
      container.append(details);
    }
    applyTrailVisibility();
  });
  bindToggle("toggle-lodging", (v) =>
    toggleLayer(map, [henro.lodgingMarker, henro.lodgingLabel], v),
  );

  bindToggle("toggle-elevation-color", (v) =>
    toggleLayer(map, elevation.colorRelief, v),
  );
  bindToggle("toggle-hillshade", (v) =>
    toggleLayer(map, elevation.hillshade, v),
  );
  bindToggle("toggle-contours", (v) =>
    toggleLayer(map, [...elevation.contour, ...elevation.contourIndex], v),
  );
  bindToggle("toggle-contour-labels", (v) =>
    toggleLayer(map, elevation.contourLabel, v),
  );

  bindToggle("toggle-terrain", (v) => {
    if (v) {
      map.setTerrain({ source: "elevation-dem-terrain", exaggeration: 1 });
    } else {
      map.setTerrain(null);
    }
  });
}

function setupClickPopup(map: MapLibreMap, elevationAvailable: boolean): void {
  let terrainActive = false;
  map.on("terrain", () => {
    terrainActive = map.getTerrain() !== null;
  });
  map.on("click", (e) => {
    // When terrain is active, always show the click elevation (spec §11.4).
    if (terrainActive && elevationAvailable) {
      const elevation = map.queryTerrainElevation(e.lngLat);
      const label =
        elevation === null || Number.isNaN(elevation)
          ? "elevation: unavailable"
          : `elevation: ${elevation.toFixed(1)} m`;
      new maplibregl.Popup({ closeButton: true })
        .setLngLat(e.lngLat)
        .setHTML(`<b>${label}</b>`)
        .addTo(map);
      return;
    }

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
  setupClickPopup(map, henro.elevation.available);
  (window as unknown as { __map: MapLibreMap }).__map = map;
}
