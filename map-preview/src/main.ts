import maplibregl, { type FilterSpecification, type Map as MapLibreMap } from "maplibre-gl";
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

  const arukihenroRouteCheckboxes = new Map<string, HTMLInputElement>();
  const arukihenroControls = document.getElementById("arukihenro-controls");
  const disableArukihenroControls = (): void => {
    for (const id of [
      "toggle-arukihenro",
      "toggle-arukihenro-labels",
      "toggle-arukihenro-pois",
    ]) {
      const el = document.getElementById(id) as HTMLInputElement | null;
      if (el) {
        el.disabled = true;
        el.checked = false;
        el.parentElement?.classList.add("disabled");
      }
    }
    arukihenroControls?.classList.add("disabled");
  };
  const applyArukihenroVisibility = (): void => {
    const masterEl = document.getElementById("toggle-arukihenro") as HTMLInputElement | null;
    const labelsEl = document.getElementById("toggle-arukihenro-labels") as HTMLInputElement | null;
    const poisEl = document.getElementById("toggle-arukihenro-pois") as HTMLInputElement | null;
    if (!masterEl || !labelsEl || !poisEl) return;
    const master = masterEl.checked;
    const labels = labelsEl.checked;
    const showPois = poisEl.checked;
    const visibleRouteIds: string[] = [];
    for (const [routeId, checkbox] of arukihenroRouteCheckboxes) {
      if (checkbox.checked) visibleRouteIds.push(routeId);
    }
    toggleLayer(map, [henro.arukihenroLineCasing, henro.arukihenroLine], master);
    toggleLayer(map, [henro.arukihenroLabel], master && labels);
    toggleLayer(map, [henro.arukihenroPoints, henro.arukihenroPointLabels], master && showPois);
    for (const id of [henro.arukihenroLineCasing, henro.arukihenroLine, henro.arukihenroLabel]) {
      if (map.getLayer(id)) {
        map.setFilter(id, [
          "all",
          ["==", ["get", "kind"], "line"],
          ["in", ["get", "route_id"], ["literal", visibleRouteIds]],
        ]);
      }
    }
    for (const id of [henro.arukihenroPoints, henro.arukihenroPointLabels]) {
      if (map.getLayer(id)) {
        map.setFilter(id, [
          "all",
          ["==", ["get", "kind"], "point"],
          ["in", ["get", "route_id"], ["literal", visibleRouteIds]],
        ]);
      }
    }
  };
  if (!henro.arukihenroAvailable) disableArukihenroControls();
  bindToggle("toggle-arukihenro", applyArukihenroVisibility);
  bindToggle("toggle-arukihenro-labels", applyArukihenroVisibility);
  bindToggle("toggle-arukihenro-pois", applyArukihenroVisibility);
  void henro.arukihenroReady.then((groups) => {
    if (groups.length === 0) {
      disableArukihenroControls();
      return;
    }
    const container = document.getElementById("arukihenro-routes");
    if (!container) return;
    for (const group of groups) {
      const details = document.createElement("details");
      const summary = document.createElement("summary");
      summary.textContent = `${prefLabel(group.region)} (${group.routes.length})`;
      details.append(summary);
      for (const route of group.routes) {
        const label = document.createElement("label");
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.checked = route.hasGeometry;
        checkbox.disabled = !route.hasGeometry;
        checkbox.addEventListener("change", applyArukihenroVisibility);
        arukihenroRouteCheckboxes.set(route.routeId, checkbox);
        label.append(checkbox, ` ${route.title ?? route.routeId}${route.hasGeometry ? "" : "（無 KML）"}`);
        details.append(label);
      }
      container.append(details);
    }
    applyArukihenroVisibility();
  });

  bindToggle("toggle-henroyado-lodging", (v) =>
    toggleLayer(map, [henro.henroyadoLodgingMarker, henro.henroyadoLodgingLabel], v),
  );
  bindToggle("toggle-min88-lodging", (v) =>
    toggleLayer(map, [henro.min88LodgingMarker, henro.min88LodgingLabel], v),
  );

  const henroHelperCheckboxes = new Map<string, HTMLInputElement>();
  const henroHelperDayCheckboxes = new Map<string, Set<HTMLInputElement>>();
  const henroHelperSetMasters = new Map<string, HTMLInputElement>();
  const applyHenroHelperVisibility = (): void => {
    const masterEl = document.getElementById("toggle-henro-helper") as HTMLInputElement | null;
    if (!masterEl) return;
    const master = masterEl.checked;
    for (const group of henro.henroHelper.groups) {
      const checkbox = henroHelperCheckboxes.get(group.layer);
      const visible = master && (checkbox?.checked ?? group.checked);
      toggleLayer(map, [group.casing, group.line], visible);
    }
    for (const set of henro.henroHelper.itinerarySets) {
      const setMaster = henroHelperSetMasters.get(set.layer);
      const dayBoxes = henroHelperDayCheckboxes.get(set.layer) ?? new Set();
      const checkedDays = [...dayBoxes]
        .filter((box) => box.checked)
        .map((box) => box.value);
      let visible = false;
      let filter: FilterSpecification | null = null;
      if (master && setMaster?.checked) {
        visible = true; // set master: show all days
      } else if (master && checkedDays.length > 0) {
        visible = true;
        filter = ["in", ["get", "day_label"], ["literal", checkedDays]];
      }
      toggleLayer(map, [set.casing, set.line, set.labelLayer], visible);
      for (const id of [set.casing, set.line, set.labelLayer]) {
        if (map.getLayer(id)) map.setFilter(id, filter);
      }
    }
  };
  bindToggle("toggle-henro-helper", applyHenroHelperVisibility);
  void henro.henroHelperReady.then((data) => {
    const container = document.getElementById("henro-helper-routes");
    if (!container) return;
    for (const group of data.groups) {
      const label = document.createElement("label");
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = group.checked;
      checkbox.addEventListener("change", applyHenroHelperVisibility);
      henroHelperCheckboxes.set(group.layer, checkbox);
      label.append(checkbox, ` ${group.label}`);
      container.append(label);
    }
    for (const set of data.itinerarySets) {
      const details = document.createElement("details");
      const summary = document.createElement("summary");
      summary.textContent = `${set.label} (${set.days.length})`;
      details.append(summary);
      const masterLabel = document.createElement("label");
      const setMaster = document.createElement("input");
      setMaster.type = "checkbox";
      setMaster.addEventListener("change", applyHenroHelperVisibility);
      henroHelperSetMasters.set(set.layer, setMaster);
      masterLabel.append(setMaster, " 全部 (all)");
      details.append(masterLabel);
      const dayBoxes = new Set<HTMLInputElement>();
      henroHelperDayCheckboxes.set(set.layer, dayBoxes);
      for (const day of set.days) {
        const label = document.createElement("label");
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.value = day.dayLabel;
        checkbox.addEventListener("change", applyHenroHelperVisibility);
        dayBoxes.add(checkbox);
        label.append(checkbox, ` ${day.dayLabel}`);
        details.append(label);
      }
      container.append(details);
    }
    applyHenroHelperVisibility();
  });

  const sekaiisanControls = document.getElementById("sekaiisan-controls");
  if (!henro.sekaiisanAvailable) {
    for (const input of sekaiisanControls?.querySelectorAll<HTMLInputElement>("input") ?? []) {
      input.disabled = true;
      input.checked = false;
    }
    sekaiisanControls?.classList.add("disabled");
  }
  bindToggle("toggle-sekaiisan-routes", (v) =>
    toggleLayer(map, [henro.sekaiisanRouteCasing, henro.sekaiisanRoute], v),
  );

  const mizutaniControls = document.getElementById("mizutani-controls");
  if (!henro.mizutaniAvailable) {
    for (const input of mizutaniControls?.querySelectorAll<HTMLInputElement>("input") ?? []) {
      input.disabled = true;
      input.checked = false;
    }
    mizutaniControls?.classList.add("disabled");
  }
  const applyMizutaniPois = (): void => {
    const master = (document.getElementById("toggle-mizutani-pois") as HTMLInputElement).checked;
    const categories = [...document.querySelectorAll<HTMLInputElement>("input[data-mizutani-category]")]
      .filter((input) => input.checked)
      .map((input) => input.dataset.mizutaniCategory as string);
    toggleLayer(map, [henro.mizutaniPoi], master && categories.length > 0);
    if (map.getLayer(henro.mizutaniPoi)) {
      map.setFilter(henro.mizutaniPoi, ["in", ["get", "category"], ["literal", categories]]);
    }
  };
  bindToggle("toggle-mizutani-routes", (v) =>
    toggleLayer(map, [henro.mizutaniRouteCasing, henro.mizutaniRoute], v),
  );
  bindToggle("toggle-mizutani-pois", applyMizutaniPois);
  for (const input of document.querySelectorAll<HTMLInputElement>("input[data-mizutani-category]")) {
    input.addEventListener("change", applyMizutaniPois);
  }
  applyMizutaniPois();

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
    const escapeHtml = (value: unknown): string => String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
    const propLines = Object.entries(props)
      .map(([k, v]) => `${escapeHtml(k)}: ${escapeHtml(v)}`)
      .join("<br/>");

    const content = [
      `<b>${escapeHtml(f.layer.id)}</b>`,
      `id: ${escapeHtml(f.id ?? props.source_id ?? "(none)")}`,
      `source: ${escapeHtml(f.source)}`,
      `source-layer: ${escapeHtml(f.sourceLayer ?? "(geojson)")}`,
      `coords: ${escapeHtml(coords)}`,
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
