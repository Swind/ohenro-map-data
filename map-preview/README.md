# Ohenro Map Preview

四國遍路離線地圖的 Web 預覽工具（Vite + TypeScript + MapLibre GL JS）。

用途是**快速視覺迭代**地圖樣式（basemap + Henro 圖層），最終以 Android 端 MapLibre 渲染為驗證目標。共用同一份 MapLibre style 定義。

參考計畫：`reference/web_map_preview.md`。

## 架構

```
shikoku-basemap.pmtiles + temples.geojson + shikoku-henro.pmtiles + lodging.geojson
                        │
                   style.json
                  /          \
        MapLibre GL JS    MapLibre Android
             Web              Android
```

basemap 與 henro 路線皆直接以 PMTiles 載入（`pmtiles://` protocol），寺廟與住宿
（QA 階段）維持 GeoJSON。與 §17 的 `basemap.pmtiles + henro.pmtiles` 目標架構一致。

## 目錄結構

```text
map-preview/
├── index.html
├── vite.config.ts
├── .env.example            # 開發用環境變數範本
├── scripts/
│   └── generate-style.mjs  # 從 @protomaps/basemaps 產生 style.json
├── src/
│   ├── main.ts             # map 初始化、debug panel、點擊 popup
│   ├── map.ts              # PMTiles protocol、Henro sources/layers
│   └── style/
│       └── style.json      # 產生的 basemap style（勿手改，重跑 npm run style:generate）
└── public/
    └── data/               # 本機建立、對 output/ 的 symlink（不進 git）
        ├── temples.geojson
        ├── lodging.geojson       # 住宿 QA 層（由 extract_lodging.py 產生）
        └── shikoku-basemap.pmtiles
```

## 前置需求

- Node.js 20+
- `output/` 下有 `shikoku-basemap.pmtiles` 與 `temples.geojson`（由根目錄 build 管線產生）

## 安裝與執行

```bash
npm install
npm run style:generate   # 產生 src/style/style.json（只改 flavor/lang 時重跑）
npm run dev
```

第一次執行時，在 repository root 建立本機資料連結與環境設定：

```bash
mkdir -p map-preview/public/data
ln -s ../../../output/shikoku-basemap.pmtiles map-preview/public/data/shikoku-basemap.pmtiles
ln -s ../../../output/shikoku-henro.pmtiles map-preview/public/data/shikoku-henro.pmtiles
ln -s ../../../output/shikoku-contours.pmtiles map-preview/public/data/shikoku-contours.pmtiles
ln -s ../../../output/shikoku-terrain.pmtiles map-preview/public/data/shikoku-terrain.pmtiles
ln -s ../../../output/shikoku-trail.pmtiles map-preview/public/data/shikoku-trail.pmtiles
ln -s ../../../output/temples.geojson map-preview/public/data/temples.geojson
ln -s ../../../output/lodging.geojson map-preview/public/data/lodging.geojson
cp map-preview/.env.example map-preview/.env.development
```

開啟 http://localhost:5173

### SSH port forwarding（遠端 Linux 開發）

```bash
ssh -L 5173:localhost:5173 user@server
# 本機開啟 http://localhost:5173
```

若 basemap 由另一 port 提供：

```bash
ssh -L 5173:localhost:5173 -L 8080:localhost:8080 user@server
```

## 環境變數（.env.development / .env.example）

| 變數 | 預設 | 說明 |
|------|------|------|
| `VITE_BASEMAP_URL` | `/data/shikoku-basemap.pmtiles` | basemap 位置，可改遠端 URL，如 `http://localhost:8080/shikoku-basemap.pmtiles` |
| `VITE_TEMPLES_URL` | `/data/temples.geojson` | 寺廟 GeoJSON |
| `VITE_HENRO_URL` | `/data/shikoku-henro.pmtiles` | Henro 路線 PMTiles（`henro_routes` vector layer）；留空停用 |
| `VITE_TRAIL_URL` | `/data/shikoku-trail.pmtiles` | 四國自然步道 PMTiles（`shikoku_trail` vector layer）；留空停用 |
| `VITE_LODGING_URL` | `/data/lodging.geojson` | 住宿 QA GeoJSON（`extract_lodging.py` 產出）；留空停用 |
| `VITE_CONTOURS_URL` | `/data/shikoku-contours.pmtiles` | 20m 等高線 PMTiles（`contours` vector layer）；留空停用 |
| `VITE_TERRAIN_URL` | `/data/shikoku-terrain.pmtiles` | Terrain-RGB 高程 PMTiles（`raster-dem`）；留空停用 |

URL 也可以直接用 query string 指定初始位置：

```
http://localhost:5173/?lat=34.191403&lon=134.206799&zoom=14
```

## 功能

- **basemap**：由 `@protomaps/basemaps` 產生（light flavor、ja lang、71 layers），source 為 `pmtiles://` protocol。
- **寺廟**：GeoJSON source，紅色圓點 marker；z9+ 顯示 `番号 + 寺名` label。
- **遍路路線**：`shikoku-henro.pmtiles` 的 `henro_routes` layer（filter `route_kind=henro_candidate`），白色 casing + 赭色（`#8f4b32`）前景，位於 basemap 之上。
- **四國自然步道**：`shikoku-trail.pmtiles` 的 `shikoku_trail` layer（`scripts/build-shikoku-trail.sh` 產出），綠色（`#2a7d4f`）線段；與遍路 overlay 分別開關。
- **住宿（QA）**：`lodging.geojson` GeoJSON source。依 subtype 著色（hotel 紅 / hostel 橘 / guest_house 綠 / camp_site 紫 / motel 灰 / apartment 藍 / chalet 深灰），z11+ 顯示名稱 label。點擊 feature 可檢視完整 properties 含 `raw_tags`、`address`、`point_method`。
- **高程視覺化**（`scripts/build-elevation-visuals.sh` 產出，資料來源 `output/shikoku-elevation-dem10.sqlite`）：
  - **color relief**：`elevation-dem-style` source 的 `color-relief` 圖層，預設隱藏，可獨立開關。
  - **hillshade**：同一 source 的 `hillshade` 圖層，預設可見。
  - **等高線**：`shikoku-contours.pmtiles` 的 `contours` layer（`elevation_m`），z12–z15；100m 主線較粗，另可切換 `elevation_m % 100 == 0` 的標籤。
  - **3D terrain**：`elevation-dem-terrain` source 經 `map.setTerrain()` 啟用（exaggeration 1）；啟用後點擊地圖顯示該點高程（`map.queryTerrainElevation`），無資料顯示 `elevation: unavailable`。
  - 資料 attribution 為國土地理院（GSI），寫在 PMTiles metadata 與 MapLibre source。
  - 未設定 `VITE_CONTOURS_URL` / `VITE_TERRAIN_URL` 時對應 toggle 停用，basemap 與 Henro 圖層照常載入。
- **點擊檢查**：顯示 feature 的 layer id / id / source / source-layer / 座標 / properties。
- **Debug panel**：zoom、lat/lon、bearing、pitch，以及圖層顯示/隱藏切換。
- **字形/icon**：目前使用 Protomaps 遠端 assets（`protomaps.github.io/basemaps-assets`），僅開發用；正式離線 Android 需改成本地資源。

## 重新產生 basemap style

style 來自 `@protomaps/basemaps`（與 Protomaps Basemaps 一致的定義），避免手寫 70+ layers：

```bash
npm run style:generate          # light flavor, ja
npm run style:generate dark en  # 其他 flavor / 語言
```

產生後可再疊加 Henro layers（在 `src/map.ts` 的 `map.on("load")` 中）。

## 驗證

```bash
npm run build   # tsc + vite build
```

手動驗證重點：

1. 地圖可平移/縮放。
2. 88 座寺廟 marker 都出現；temple-088（大窪寺）在預設中心附近。
3. 點擊寺廟 popup 顯示 `temple-088` 等 canonical ID。
4. 日文字型（靈山寺、大窪寺…）正常渲染。

5. 住宿 QA 層依 subtype 顯示不同顏色；點擊 marker popup 顯示 `lodging-osm-*` canonical ID、`raw_tags`、`point_method`。

6. 高程視覺化（需 `output/shikoku-contours.pmtiles` 與 `output/shikoku-terrain.pmtiles`）：
   - 無 elevation URL 時既有 preview 正常載入。
   - hillshade 預設可見且不蓋掉道路、地名與遍路路線。
   - color relief 可獨立開關。
   - contour 在 z12 以下不出現，z12 以上可讀。
   - 100m 主線較粗且有標籤。
   - 3D terrain 開關可恢復平面地圖。
   - terrain 啟用後點擊可取得合理高程。
   - 海面沒有低高程彩色方塊或尖峰。

## 後續（依 reference 計畫 Phase 5–6）

- 將同一份 style.json 用於 MapLibre Android，比對 Web/Android 渲染差異。
- 寺廟 schema 穩定後以 Planetiler 把 `temples.geojson` 併入 `henro.pmtiles`，移除 GeoJSON source。
