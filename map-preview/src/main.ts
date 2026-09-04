import maplibregl, {
  type FilterSpecification,
  type Map as MapLibreMap,
  type MapGeoJSONFeature,
} from "maplibre-gl";
import type { FeatureCollection, Geometry, Position } from "geojson";
import { createMap, type HenroLayers } from "./map";
import { prefLabel, type TrailRoute } from "./trail";
import { renderElevationProfile } from "./profile";
import { setupPlanMode } from "./plan-mode";

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

/**
 * Wire the sidebar source trees: the header's ▸ button toggles the children
 * (plain div-based collapse, independent from the master checkbox in the same
 * header row, so checking a source never collapses its sub-toggles).
 */
function setupLayerGroups(): void {
  for (const group of document.querySelectorAll<HTMLElement>(".layer-group")) {
    const toggle = group.querySelector<HTMLButtonElement>(
      ":scope > .layer-group-header > .tree-toggle",
    );
    const targetId = toggle?.dataset.treeTarget;
    if (!toggle || !targetId) continue;
    const children = document.getElementById(targetId);
    if (!children) continue;
    toggle.addEventListener("click", () => {
      const collapsed = children.classList.toggle("collapsed");
      toggle.textContent = collapsed ? "▸" : "▾";
      toggle.setAttribute("aria-expanded", String(!collapsed));
    });
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
  const applyTemplesVisibility = (): void => {
    const master = (document.getElementById("toggle-temples") as HTMLInputElement).checked;
    const labels = (document.getElementById("toggle-temple-labels") as HTMLInputElement).checked;
    toggleLayer(map, [henro.templeMarker], master);
    toggleLayer(map, [henro.templeLabel], master && labels);
  };
  bindToggle("toggle-temples", applyTemplesVisibility);
  bindToggle("toggle-temple-labels", applyTemplesVisibility);
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

  const ohenro88Controls = document.getElementById("ohenro88-controls");
  if (!henro.ohenro88Available) {
    for (const input of ohenro88Controls?.querySelectorAll<HTMLInputElement>("input") ?? []) {
      input.disabled = true;
      input.checked = false;
    }
    ohenro88Controls?.classList.add("disabled");
  }
  const ohenro88RouteCheckboxes = new Map<string, HTMLInputElement>();
  const applyOhenro88Visibility = (): void => {
    const masterEl = document.getElementById("toggle-ohenro88") as HTMLInputElement | null;
    const labelsEl = document.getElementById("toggle-ohenro88-labels") as HTMLInputElement | null;
    const pointsEl = document.getElementById("toggle-ohenro88-points") as HTMLInputElement | null;
    if (!masterEl || !labelsEl || !pointsEl) return;
    const master = masterEl.checked;
    const labels = labelsEl.checked;
    const showPoints = pointsEl.checked;
    const visibleRouteIds: string[] = [];
    for (const [routeId, checkbox] of ohenro88RouteCheckboxes) {
      if (checkbox.checked) visibleRouteIds.push(routeId);
    }
    toggleLayer(map, [henro.ohenro88Casing, henro.ohenro88Line], master);
    toggleLayer(map, [henro.ohenro88Label], master && labels);
    toggleLayer(map, [henro.ohenro88Points, henro.ohenro88PointLabels], master && showPoints);
    const filter: FilterSpecification = ["in", ["get", "route_id"], ["literal", visibleRouteIds]];
    for (const id of [henro.ohenro88Casing, henro.ohenro88Line, henro.ohenro88Label]) {
      if (map.getLayer(id)) map.setFilter(id, filter);
    }
  };
  bindToggle("toggle-ohenro88", applyOhenro88Visibility);
  bindToggle("toggle-ohenro88-labels", applyOhenro88Visibility);
  bindToggle("toggle-ohenro88-points", applyOhenro88Visibility);
  void henro.ohenro88Ready.then((groups) => {
    const container = document.getElementById("ohenro88-routes");
    if (!container) return;
    for (const group of groups) {
      const details = document.createElement("details");
      const summary = document.createElement("summary");
      summary.textContent = `${group.label} (${group.routes.length})`;
      details.append(summary);
      for (const route of group.routes) {
        const label = document.createElement("label");
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.checked = true;
        checkbox.addEventListener("change", applyOhenro88Visibility);
        ohenro88RouteCheckboxes.set(route.routeId, checkbox);
        label.append(checkbox, ` ${route.name}`);
        details.append(label);
      }
      container.append(details);
    }
    applyOhenro88Visibility();
  });

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

  const henroHelperPoiCheckboxes = new Map<string, HTMLInputElement>();
  const henroHelperPoiControls = document.getElementById("henro-helper-pois-controls");
  if (!henro.henroHelperPoisAvailable) {
    for (const input of henroHelperPoiControls?.querySelectorAll<HTMLInputElement>("input") ?? []) {
      input.disabled = true;
      input.checked = false;
    }
    henroHelperPoiControls?.classList.add("disabled");
  }
  const applyHenroHelperPoiVisibility = (): void => {
    const masterEl = document.getElementById("toggle-henro-helper-pois") as HTMLInputElement | null;
    const labelsEl = document.getElementById("toggle-henro-helper-poi-labels") as HTMLInputElement | null;
    if (!masterEl || !labelsEl) return;
    const master = masterEl.checked;
    const labels = labelsEl.checked;
    for (const group of henro.henroHelperPois) {
      const checkbox = henroHelperPoiCheckboxes.get(group.kind);
      const visible = master && (checkbox?.checked ?? group.checked);
      toggleLayer(map, [group.circle], visible);
      if (group.labelLayer) {
        toggleLayer(map, [group.labelLayer], visible && labels);
      }
    }
  };
  bindToggle("toggle-henro-helper-pois", applyHenroHelperPoiVisibility);
  bindToggle("toggle-henro-helper-poi-labels", applyHenroHelperPoiVisibility);
  void henro.henroHelperPoisReady.then((groups) => {
    const container = document.getElementById("henro-helper-pois-categories");
    if (!container) return;
    for (const group of groups) {
      const label = document.createElement("label");
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = group.checked;
      checkbox.addEventListener("change", applyHenroHelperPoiVisibility);
      henroHelperPoiCheckboxes.set(group.kind, checkbox);
      label.append(checkbox, ` ${group.label}`);
      container.append(label);
    }
    applyHenroHelperPoiVisibility();
  });

  const ohenroNoAkariControls = document.getElementById("ohenro-no-akari-controls");
  if (!henro.ohenroNoAkariAvailable) {
    for (const input of ohenroNoAkariControls?.querySelectorAll<HTMLInputElement>("input") ?? []) {
      input.disabled = true;
      input.checked = false;
    }
    ohenroNoAkariControls?.classList.add("disabled");
  }
  bindToggle("toggle-ohenro-no-akari", (v) =>
    toggleLayer(map, [henro.ohenroNoAkariCasing, henro.ohenroNoAkariLine], v),
  );

  const sekaiisanControls = document.getElementById("sekaiisan-controls");
  const disableSekaiisanInput = (id: string): void => {
    const el = document.getElementById(id) as HTMLInputElement | null;
    if (el) {
      el.disabled = true;
      el.checked = false;
    }
  };
  if (!henro.sekaiisanAvailable) disableSekaiisanInput("toggle-sekaiisan-routes");
  if (!henro.planAvailable) disableSekaiisanInput("toggle-sekaiisan-plan");
  if (!henro.sekaiisanAvailable && !henro.planAvailable) {
    sekaiisanControls?.classList.add("disabled");
  }
  bindToggle("toggle-sekaiisan-routes", (v) =>
    toggleLayer(map, [henro.sekaiisanRouteCasing, henro.sekaiisanRoute], v),
  );
  bindToggle("toggle-sekaiisan-plan", (v) =>
    toggleLayer(
      map,
      [henro.planRouteCasing, henro.planRoute, henro.planWaypoints, henro.planWaypointLabels],
      v,
    ),
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
    const master = (document.getElementById("toggle-mizutani") as HTMLInputElement).checked;
    const pois = (document.getElementById("toggle-mizutani-pois") as HTMLInputElement).checked;
    const labels = (document.getElementById("toggle-mizutani-poi-labels") as HTMLInputElement).checked;
    const categories = [...document.querySelectorAll<HTMLInputElement>("input[data-mizutani-category]")]
      .filter((input) => input.checked)
      .map((input) => input.dataset.mizutaniCategory as string);
    const show = master && pois && categories.length > 0;
    toggleLayer(map, [henro.mizutaniPoi], show);
    toggleLayer(map, [henro.mizutaniPoiLabel], show && labels);
    for (const id of [henro.mizutaniPoi, henro.mizutaniPoiLabel]) {
      if (map.getLayer(id)) {
        map.setFilter(id, ["in", ["get", "category"], ["literal", categories]]);
      }
    }
  };
  const applyMizutaniVisibility = (): void => {
    const master = (document.getElementById("toggle-mizutani") as HTMLInputElement).checked;
    const routes = (document.getElementById("toggle-mizutani-routes") as HTMLInputElement).checked;
    toggleLayer(map, [henro.mizutaniRouteCasing, henro.mizutaniRoute], master && routes);
    applyMizutaniPois();
  };
  bindToggle("toggle-mizutani", applyMizutaniVisibility);
  bindToggle("toggle-mizutani-routes", applyMizutaniVisibility);
  bindToggle("toggle-mizutani-pois", applyMizutaniPois);
  bindToggle("toggle-mizutani-poi-labels", applyMizutaniPois);
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

// Popup: only overlay features (everything except the basemap `protomaps`
// source) are clickable, and their properties are shown in a curated table
// instead of a raw dump.
const OVERLAY_SOURCE_LABELS: Record<string, string> = {
  "henro-temples": "寺廟",
  "henro-route": "遍路路線 (OSM)",
  "sekaiisan-henro": "世界遺産協議会",
  trail: "四國自然步道",
  "henroyado-lodging": "Henroyado 住宿",
  "min88-lodging": "min88 住宿",
  "mizutani-henro": "水谷遍路",
  arukihenro: "歩き遍路",
  "henro-helper": "Henro Helper 路線",
  "henro-helper-pois": "Henro Helper POI",
  ohenro88: "OHenro 88",
  "ohenro-no-akari": "遍路のあかり",
  "elevation-contours": "等高線",
  "symbol-smoke": "Symbol smoke",
};

// Curated display fields, in display order.
const POPUP_DISPLAY_FIELDS: ReadonlyArray<readonly [string, string]> = [
  ["name", "名稱"],
  ["name_ja", "日文名"],
  ["name_en", "英文名"],
  ["title", "名稱"],
  ["temple_number", "札所番號"],
  ["bekkaku_number", "別格番號"],
  ["temple_name_ja", "寺名"],
  ["number", "番號"],
  ["category", "類別"],
  ["kind", "種類"],
  ["route_type", "路線類型"],
  ["route_kind", "路線類型"],
  ["day_label", "日"],
  ["from_temple", "起點"],
  ["to_temple", "終點"],
  ["distance", "距離"],
  ["elevation", "標高"],
  ["time", "時間"],
  ["elevation_m", "標高 (m)"],
  ["address", "地址"],
  ["url", "網址"],
  ["description", "說明"],
  ["route_id", "路線 ID"],
  ["feature_id", "要素 ID"],
];

const POPUP_DISPLAY_KEYS = new Set(POPUP_DISPLAY_FIELDS.map(([key]) => key));

// Raw properties hidden from the collapsible "other" list.
const POPUP_RAW_SKIP = new Set([
  "source", "source_id", "segment_id", "icon_id", "style_url", "icon",
  "folder", "color", "width", "_color", "_opacity", "_weight", "layer",
  "class", "index", "num_points",
]);

function escapeHtml(value: unknown): string {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function popupValueHtml(key: string, value: unknown): string {
  if (value === null || value === undefined) return "";
  const text = String(value);
  if (key === "url" && /^https?:\/\//.test(text)) {
    return `<a href="${escapeHtml(text)}" target="_blank" rel="noopener">${escapeHtml(text)}</a>`;
  }
  return escapeHtml(text);
}

function popupTitle(source: string, props: Record<string, unknown>): string {
  const label = OVERLAY_SOURCE_LABELS[source] ?? source;
  for (const key of [
    "temple_name_ja",
    "name_ja",
    "name_en",
    "name",
    "title",
    "day_label",
    "route_id",
    "feature_id",
  ]) {
    const v = props[key];
    if (typeof v === "string" && v.trim() !== "") {
      return `${label} · ${v}`;
    }
  }
  return label;
}

function popupCoordinates(geometry: Geometry): string {
  if (geometry.type === "Point") {
    return `${geometry.coordinates[1].toFixed(5)}, ${geometry.coordinates[0].toFixed(5)}`;
  }
  if (geometry.type === "MultiPoint") {
    return `${geometry.coordinates.length} points`;
  }
  return geometry.type;
}

// Click tolerance in pixels: a click within this distance of a rendered
// overlay feature selects that feature instead of requiring an exact hit.
const CLICK_TOLERANCE_PX = 15;

function pointToSegmentDistance(
  px: number,
  py: number,
  ax: number,
  ay: number,
  bx: number,
  by: number,
): number {
  const dx = bx - ax;
  const dy = by - ay;
  const lengthSq = dx * dx + dy * dy;
  if (lengthSq === 0) return Math.hypot(px - ax, py - ay);
  const t = Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / lengthSq));
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
}

function lineDistance(
  map: MapLibreMap,
  x: number,
  y: number,
  coords: Position[],
): number {
  if (coords.length === 0) return Infinity;
  const project = (coord: Position): { x: number; y: number } =>
    map.project([coord[0], coord[1]]);
  if (coords.length === 1) {
    const p = project(coords[0]);
    return Math.hypot(x - p.x, y - p.y);
  }
  let min = Infinity;
  let prev = project(coords[0]);
  for (let i = 1; i < coords.length; i++) {
    const cur = project(coords[i]);
    min = Math.min(min, pointToSegmentDistance(x, y, prev.x, prev.y, cur.x, cur.y));
    prev = cur;
  }
  return min;
}

function screenDistanceToGeometry(
  map: MapLibreMap,
  x: number,
  y: number,
  geometry: Geometry,
): number {
  const project = (coord: Position): { x: number; y: number } =>
    map.project([coord[0], coord[1]]);
  switch (geometry.type) {
    case "Point": {
      const p = project(geometry.coordinates);
      return Math.hypot(x - p.x, y - p.y);
    }
    case "MultiPoint": {
      let min = Infinity;
      for (const coord of geometry.coordinates) {
        const p = project(coord);
        min = Math.min(min, Math.hypot(x - p.x, y - p.y));
      }
      return min;
    }
    case "LineString":
      return lineDistance(map, x, y, geometry.coordinates);
    case "MultiLineString": {
      let min = Infinity;
      for (const line of geometry.coordinates) {
        min = Math.min(min, lineDistance(map, x, y, line));
      }
      return min;
    }
    default:
      return Infinity;
  }
}

interface ClickCandidate {
  feature: MapGeoJSONFeature;
  distance: number;
  isPoint: boolean;
}

function setupClickPopup(map: MapLibreMap): void {
  map.on("click", (e) => {
    // Interactive planning mode owns the click: no feature popup.
    const planMode = document.getElementById("toggle-plan-mode") as HTMLInputElement | null;
    if (planMode?.checked) return;
    const x = e.point.x;
    const y = e.point.y;
    const radius = CLICK_TOLERANCE_PX;

    // queryRenderedFeatures only returns rendered (currently shown) features,
    // so basemap filtering + "shown features only" come for free. Query a
    // small bounding box around the click for the tolerance.
    const features = map
      .queryRenderedFeatures([
        [x - radius, y - radius],
        [x + radius, y + radius],
      ])
      .filter((f) => f.source !== "protomaps");

    // Deduplicate tile-split copies of the same source feature (keep nearest).
    const bestByKey = new Map<string, ClickCandidate>();
    for (const feature of features) {
      const props = feature.properties ?? {};
      const key =
        `${feature.source}:` +
        (feature.id ??
          props.feature_id ??
          props.route_id ??
          props.name ??
          feature.sourceLayer ??
          "");
      const distance = screenDistanceToGeometry(map, x, y, feature.geometry);
      if (distance > radius) continue;
      const isPoint = feature.geometry.type === "Point" || feature.geometry.type === "MultiPoint";
      const prev = bestByKey.get(key);
      if (!prev || distance < prev.distance) {
        bestByKey.set(key, { feature, distance, isPoint });
      }
    }
    const candidates = [...bestByKey.values()];
    if (candidates.length === 0) return;

    // POI (point geometry) takes priority over routes (line geometry); the
    // nearest candidate wins within the same kind.
    const points = candidates.filter((c) => c.isPoint);
    const pool = points.length > 0 ? points : candidates;
    const best = pool.reduce((a, b) => (b.distance < a.distance ? b : a));

    const f = best.feature;
    const props = f.properties ?? {};
    const rows = POPUP_DISPLAY_FIELDS
      .filter(([key]) => props[key] !== undefined && props[key] !== null)
      .map(([key, label]) => {
        const value = popupValueHtml(key, props[key]);
        if (value === "") return "";
        return `<tr><th>${escapeHtml(label)}</th><td>${value}</td></tr>`;
      })
      .join("");

    const other = Object.entries(props)
      .filter(
        ([key]) =>
          !POPUP_DISPLAY_KEYS.has(key) &&
          !POPUP_RAW_SKIP.has(key) &&
          !key.startsWith("field_"),
      )
      .map(([key, value]) => `<span class="raw-line">${escapeHtml(key)}: ${escapeHtml(value)}</span>`)
      .join("");
    const otherSection =
      other.length > 0
        ? `<details class="henro-popup-raw"><summary>其他屬性</summary><div>${other}</div></details>`
        : "";

    const content =
      `<div class="henro-popup">` +
      `<div class="henro-popup-title">${escapeHtml(popupTitle(f.source, props))}</div>` +
      `<div class="henro-popup-coords">${escapeHtml(popupCoordinates(f.geometry))} · zoom ${map.getZoom().toFixed(1)}</div>` +
      (rows.length > 0 ? `<table class="henro-popup-table">${rows}</table>` : "") +
      otherSection +
      `</div>`;

    // Snap the popup to the feature when it is a point; otherwise anchor at
    // the click location.
    const anchor: [number, number] =
      f.geometry.type === "Point"
        ? [f.geometry.coordinates[0], f.geometry.coordinates[1]]
        : [e.lngLat.lng, e.lngLat.lat];

    new maplibregl.Popup({ closeButton: true, maxWidth: "340px" })
      .setLngLat(anchor)
      .setHTML(content)
      .addTo(map);
  });
}

function setupPlanProfile(): void {
  const url = import.meta.env.VITE_PLAN_URL as string | undefined;
  const container = document.getElementById("plan-profile");
  if (!url || !container) return;
  fetch(url)
    .then((r) =>
      r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)),
    )
    .then((fc) => renderElevationProfile(container, fc as FeatureCollection))
    .catch((err) => {
      container.textContent = `plan profile error: ${String(err)}`;
    });
}

const container = document.getElementById("map");
if (container) {
  setupLayerGroups();
  const { map, henro } = createMap(container);
  setupDebugPanel(map, henro);
  setupClickPopup(map);
  setupPlanProfile();
  setupPlanMode(map);
  (window as unknown as { __map: MapLibreMap }).__map = map;
}
