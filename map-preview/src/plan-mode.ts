import type { GeoJSONSource, Map as MapLibreMap } from "maplibre-gl";
import type { Feature, FeatureCollection, Position } from "geojson";
import { planRoute, type PlanGraph } from "./planner";
import { TerrainElevationSampler } from "./terrain";
import { buildElevationProfile, renderElevationProfile } from "./profile";

const GRAPH_URL = import.meta.env.VITE_PLAN_GRAPH_URL as string | undefined;
const TERRAIN_URL = import.meta.env.VITE_TERRAIN_URL as string | undefined;

const SOURCE_ID = "plan-live";
const LIVE_COLOR = "#2e7d32";

function emptyCollection(): FeatureCollection {
  return { type: "FeatureCollection", features: [] };
}

function waypointsFc(points: Array<{ lon: number; lat: number }>): FeatureCollection {
  return {
    type: "FeatureCollection",
    features: points.map((p, index) => ({
      type: "Feature",
      properties: { kind: "waypoint", index },
      geometry: { type: "Point", coordinates: [p.lon, p.lat] },
    })),
  };
}

/**
 * Interactive client-side planner: click points on the map (plan mode on),
 * run Dijkstra in the browser over the compact routing graph, sample terrain
 * elevation per vertex, and draw the path + elevation profile.
 */
export function setupPlanMode(map: MapLibreMap): void {
  const toggle = document.getElementById("toggle-plan-mode") as HTMLInputElement | null;
  const clearBtn = document.getElementById("plan-clear") as HTMLButtonElement | null;
  const undoBtn = document.getElementById("plan-undo") as HTMLButtonElement | null;
  const status = document.getElementById("plan-mode-status");
  const profile = document.getElementById("plan-profile");
  if (!toggle || !status || !profile) return;

  let graph: PlanGraph | null = null;
  let graphError: string | null = null;
  const sampler = TERRAIN_URL ? new TerrainElevationSampler(TERRAIN_URL) : null;
  const points: Array<{ lon: number; lat: number }> = [];
  let ready = false;

  // Source/layers can only be added after the style is loaded; registering
  // them too early throws and would abort the whole setup (no click handler).
  const setupLayers = (): void => {
    if (ready) return;
    ready = true;
    map.addSource(SOURCE_ID, { type: "geojson", data: emptyCollection() });
    map.addLayer({
      id: "plan-live-route-casing",
      type: "line",
      source: SOURCE_ID,
      filter: ["==", ["get", "kind"], "planned_route"],
      layout: { "line-cap": "round", "line-join": "round" },
      paint: {
        "line-color": "#ffffff",
        "line-width": ["interpolate", ["linear"], ["zoom"], 8, 7, 14, 12],
        "line-opacity": 0.95,
      },
    });
    map.addLayer({
      id: "plan-live-route",
      type: "line",
      source: SOURCE_ID,
      filter: ["==", ["get", "kind"], "planned_route"],
      layout: { "line-cap": "round", "line-join": "round" },
      paint: {
        "line-color": LIVE_COLOR,
        "line-width": ["interpolate", ["linear"], ["zoom"], 8, 4, 14, 8],
        "line-opacity": 0.95,
      },
    });
    map.addLayer({
      id: "plan-live-points",
      type: "circle",
      source: SOURCE_ID,
      filter: ["==", ["get", "kind"], "waypoint"],
      paint: {
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 8, 6, 14, 9],
        "circle-color": LIVE_COLOR,
        "circle-stroke-color": "#ffffff",
        "circle-stroke-width": 2,
      },
    });
    map.addLayer({
      id: "plan-live-point-labels",
      type: "symbol",
      source: SOURCE_ID,
      filter: ["==", ["get", "kind"], "waypoint"],
      layout: {
        "text-field": ["to-string", ["get", "index"]],
        "text-font": ["Noto Sans CJK JP Regular"],
        "text-size": 13,
        "text-offset": [0, 1.4],
        "text-anchor": "top",
      },
      paint: {
        "text-color": LIVE_COLOR,
        "text-halo-color": "#ffffff",
        "text-halo-width": 1.6,
      },
    });
  };

  const render = (fc: FeatureCollection): void => {
    const source = map.getSource(SOURCE_ID) as GeoJSONSource;
    source.setData(fc);
  };

  const refresh = async (): Promise<void> => {
    if (!ready) {
      status.textContent = "地圖載入中…";
      return;
    }
    if (points.length === 0) {
      render(emptyCollection());
      profile.textContent = "（未規劃）";
      status.textContent = "勾選規劃模式後，點擊地圖加入起點 A";
      return;
    }
    if (points.length === 1) {
      render(waypointsFc(points));
      status.textContent = "已加入 A，再點一下加入終點 B（A/B 之間可先點中間點）";
      return;
    }
    if (graphError) {
      status.textContent = graphError;
      return;
    }
    if (!graph) {
      status.textContent = "規劃圖尚未載入…";
      return;
    }
    let result;
    try {
      result = planRoute(graph, points);
    } catch (err) {
      status.textContent = String(err);
      return;
    }
    if (result.status === "disconnected") {
      render(waypointsFc(points));
      profile.textContent = "disconnected（不同 component，無路徑）";
      status.textContent = "不同 component：起終點不連通";
      return;
    }

    // Attach per-vertex elevation (Terrain-RGB from the existing PMTiles).
    const coords3: Array<[number, number] | [number, number, number]> = [];
    if (sampler) {
      const elevations = await Promise.all(
        result.coords.map(([lon, lat]) => sampler.sample(lat, lon)),
      );
      result.coords.forEach(([lon, lat], i) => {
        const elev = elevations[i];
        coords3.push(elev === null ? [lon, lat] : [lon, lat, elev]);
      });
    } else {
      result.coords.forEach(([lon, lat]) => coords3.push([lon, lat]));
    }

    const stats = buildElevationProfile(coords3 as Position[]);
    const routeFeature: Feature = {
      type: "Feature",
      properties: {
        kind: "planned_route",
        status: result.status,
        length_m: Math.round((result.lengthM ?? 0) * 1000) / 1000,
        gain_m: stats ? Math.round(stats.gainM) : undefined,
        loss_m: stats ? Math.round(stats.lossM) : undefined,
        min_m: stats?.minM,
        max_m: stats?.maxM,
      },
      geometry: { type: "LineString", coordinates: coords3 },
    };
    const fc: FeatureCollection = {
      type: "FeatureCollection",
      features: [
        routeFeature,
        ...result.points.map((p) => ({
          type: "Feature" as const,
          properties: { kind: "waypoint" as const, index: p.index },
          geometry: { type: "Point" as const, coordinates: [p.lon, p.lat] },
        })),
      ],
    };
    render(fc);
    renderElevationProfile(profile, fc);
    const km = ((result.lengthM ?? 0) / 1000).toFixed(1);
    status.textContent =
      `${km} km · ↑${stats ? Math.round(stats.gainM) : "?"} ` +
      `↓${stats ? Math.round(stats.lossM) : "?"} m（再點可加中間點；清除重來）`;
  };

  map.on("click", (e) => {
    if (!toggle.checked || !ready) return;
    points.push({ lon: e.lngLat.lng, lat: e.lngLat.lat });
    void refresh();
  });

  clearBtn?.addEventListener("click", () => {
    points.length = 0;
    void refresh();
  });

  undoBtn?.addEventListener("click", () => {
    points.pop();
    void refresh();
  });

  toggle.addEventListener("change", () => void refresh());

  if (!GRAPH_URL) {
    status.textContent = "未設定 VITE_PLAN_GRAPH_URL，互動規劃停用";
    return;
  }
  fetch(GRAPH_URL)
    .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
    .then((g) => {
      graph = g as PlanGraph;
      if (ready) {
        status.textContent = "規劃圖已載入；勾選規劃模式後點擊地圖加入 A";
      }
    })
    .catch((err) => {
      graphError = `規劃圖載入失敗: ${String(err)}`;
      status.textContent = graphError;
    });

  if (map.isStyleLoaded()) {
    setupLayers();
  } else {
    map.on("load", setupLayers);
  }
}