import type { GeoJSONSource, Map as MapLibreMap } from "maplibre-gl";
import type { Feature, FeatureCollection, Position } from "geojson";
import { planRoute, type PlanGraph } from "./planner";
import { TerrainElevationSampler } from "./terrain";
import { buildElevationProfile, renderElevationProfile } from "./profile";

const SEKAIISAN_GRAPH_URL = import.meta.env.VITE_PLAN_GRAPH_URL as string | undefined;
const OHENRO88_GRAPH_URL = import.meta.env.VITE_OHENRO88_PLAN_GRAPH_URL as string | undefined;
const TERRAIN_URL = import.meta.env.VITE_TERRAIN_URL as string | undefined;

interface NetworkConfig {
  id: string;
  label: string;
  url?: string;
}

const NETWORKS: NetworkConfig[] = [
  { id: "sekaiisan", label: "世界遺産協議会", url: SEKAIISAN_GRAPH_URL },
  { id: "ohenro88", label: "OHenro 88", url: OHENRO88_GRAPH_URL },
];

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

  const setStatus = (text: string, kind?: "error" | "warn"): void => {
    status.textContent = text;
    status.classList.toggle("plan-error", kind === "error");
    status.classList.toggle("plan-warn", kind === "warn");
  };

  const refresh = async (): Promise<void> => {
    try {
      if (!ready) {
        setStatus("地圖載入中…");
        return;
      }
      if (points.length === 0) {
        render(emptyCollection());
        profile.textContent = "（未規劃）";
        setStatus("勾選規劃模式後，點擊地圖加入起點 A");
        return;
      }
      if (points.length === 1) {
        render(waypointsFc(points));
        setStatus("已加入 A，再點一下加入終點 B（A/B 之間可先點中間點）");
        return;
      }
      if (graphError) {
        setStatus(graphError, "error");
        return;
      }
      if (!graph) {
        setStatus("規劃圖尚未載入…", "warn");
        return;
      }
      const result = planRoute(graph, points);
      if (result.status === "disconnected") {
        render(waypointsFc(points));
        profile.textContent = "disconnected（不同 component，無路徑）";
        setStatus(
          "不同 component：起終點不在同一連通區塊（官方引導線本身有缺口）。" +
            "可換點或改用 OHenro 88 網路。",
          "warn",
        );
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
      setStatus(
        `${km} km · ↑${stats ? Math.round(stats.gainM) : "?"} ` +
          `↓${stats ? Math.round(stats.lossM) : "?"} m（再點可加中間點；清除重來）`,
      );
    } catch (err) {
      console.error("interactive plan failed:", err);
      setStatus(`規劃失敗：${String(err)}`, "error");
    }
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

  // Network selector: choose which route network to plan on. Switching loads
  // that network's routing graph and clears the current points.
  const networkSelect = document.getElementById("plan-network") as HTMLSelectElement | null;
  if (networkSelect) {
    const available = NETWORKS.filter((n) => n.url);
    for (const n of available) {
      const option = document.createElement("option");
      option.value = n.id;
      option.textContent = n.label;
      networkSelect.append(option);
    }
  }
  const selectedUrl = (): string | undefined =>
    NETWORKS.find((n) => n.id === networkSelect?.value)?.url;
  const currentNetworkLabel = (): string =>
    NETWORKS.find((n) => n.id === networkSelect?.value)?.label ?? "?";

  const loadGraph = (url: string): void => {
    graph = null;
    graphError = null;
    points.length = 0;
    void refresh();
    setStatus("載入規劃圖…", "warn");
    fetch(url)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((g) => {
        graph = g as PlanGraph;
        setStatus(
          `${currentNetworkLabel()} 規劃圖已載入；勾選規劃模式後點擊地圖加入 A`,
        );
      })
      .catch((err) => {
        graphError = `規劃圖載入失敗: ${String(err)}`;
        setStatus(graphError, "error");
      });
  };
  networkSelect?.addEventListener("change", () => {
    const url = selectedUrl();
    if (url) loadGraph(url);
  });

  const firstUrl = selectedUrl();
  if (!firstUrl) {
    setStatus("未設定規劃圖 URL（VITE_PLAN_GRAPH_URL），互動規劃停用", "error");
    return;
  }
  loadGraph(firstUrl);

  if (map.isStyleLoaded()) {
    setupLayers();
  } else {
    map.on("load", setupLayers);
  }
}