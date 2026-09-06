# Ohenro Map Preview

四國遍路離線地圖的 Web 預覽工具（Vite + TypeScript + MapLibre GL JS）。

用途是**快速視覺迭代**地圖樣式（basemap + Henro 圖層），最終以 Android 端 MapLibre 渲染為驗證目標。共用同一份 MapLibre style 定義。

參考計畫：`reference/web_map_preview.md`。

## 架構

```
shikoku-basemap.pmtiles + temples.geojson + shikoku-henro.pmtiles + lodging + Mizutani PMTiles
                        │
                   style.json
                  /          \
        MapLibre GL JS    MapLibre Android
             Web              Android
```

basemap、henro 路線、住宿與水谷遍路導覽圖皆直接以 PMTiles 載入（`pmtiles://` protocol）；寺廟維持
GeoJSON。所有 overlay 都可獨立更新及開關。

## 目錄結構

```text
map-preview/
├── index.html              # 地圖預覽主頁
├── editor.html             # 離線路線編輯器（/editor.html）
├── vite.config.ts          # dev server + build（main / editor 兩個 entry）
├── .env.example            # 開發用環境變數範本
├── scripts/
│   └── generate-style.mjs  # 從 @protomaps/basemaps 產生 style.json
├── src/
│   ├── main.ts             # map 初始化、debug panel、點擊 popup
│   ├── map.ts              # PMTiles protocol、Henro sources/layers
│   ├── base-map.ts         # 共用 MapLibre 地圖建立（preview 與 editor 共用）
│   ├── editor/             # 路線編輯器核心（framework-free、純函式、可測試）
│   │   ├── main.ts         # 編輯器瀏覽器 UI（工具列、側欄、undo/redo、匯入/匯出）
│   │   ├── model.ts        # JSON-safe 資料模型（EditorProject / source / section / leg）
│   │   ├── import.ts       # 檔案匯入（SHA-256、格式偵測、確定性 feature ID）
│   │   ├── import-geojson.ts / import-kml.ts  # 純函式 GeoJSON/KML parser + normalizer
│   │   ├── source-layers.ts   # 匯入 source 的 MapLibre 圖層（visible/selectable/color/remove）
│   │   ├── hit-test.ts        # 點擊命中解析（POI / line point，多候選 chooser）
│   │   ├── geometry.ts        # 投影、line range 抽取、長度計算
│   │   ├── validation.ts      # section 結構驗證、exact-only gap 偵測、summary
│   │   ├── draft-layers.ts    # 編輯中 draft 的視覺化圖層（route/POI/gap/offset）
│   │   ├── line-eligibility.ts # 判定哪些 line feature 可作為 route leg（排除 visual diagnostics）
│   │   ├── hover-layers.ts    # 權威 hover highlight（ephemeral source + line/point layers）
│   │   ├── auto-order-legs.ts # exact-only 自動排序/反向已選 legs（非 routing）
│   │   ├── project-io.ts      # 專案 JSON 序列化/解析（信任邊界、重算 leg）
│   │   ├── export-geojson.ts  # 衍生 GeoJSON 匯出（final / QA）
│   │   ├── export-kml.ts      # 衍生 KML 2.2 匯出（由 GeoJSON 轉換）
│   │   └── history.ts         # 有界 undo/redo（section 快照）
│   └── style/
│       └── style.json      # 產生的 basemap style（勿手改，重跑 npm run style:generate）
└── public/
    └── data/               # 本機建立、對 output/ 的 symlink（不進 git）
        ├── temples.geojson
        ├── shikoku-henroyado-lodging.pmtiles
        ├── shikoku-min88-lodging.pmtiles
        ├── shikoku-mizutani-henro.pmtiles
        ├── shikoku-sekaiisan-henro.geojson
        ├── arukihenro-routes.json
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
ln -s ../../../output/shikoku-nature-trail.pmtiles map-preview/public/data/shikoku-nature-trail.pmtiles
ln -s ../../../output/shikoku-nature-trail.geojson map-preview/public/data/shikoku-nature-trail.geojson
ln -s ../../../output/temples.geojson map-preview/public/data/temples.geojson
ln -s ../../../output/shikoku-henroyado-lodging.pmtiles map-preview/public/data/shikoku-henroyado-lodging.pmtiles
ln -s ../../../output/shikoku-min88-lodging.pmtiles map-preview/public/data/shikoku-min88-lodging.pmtiles
ln -s ../../../output/shikoku-mizutani-henro.pmtiles map-preview/public/data/shikoku-mizutani-henro.pmtiles
ln -s ../../../output/sekaiisan-henro-review/source-edges.geojson map-preview/public/data/shikoku-sekaiisan-henro.geojson
ln -s ../../../output/sekaiisan-henro-plan-graph.json map-preview/public/data/sekaiisan-henro-plan-graph.json
ln -s ../../../output/ohenro88-routes/ohenro88-plan-graph.json map-preview/public/data/ohenro88-plan-graph.json
ln -s ../../../output/arukihenro-routes.json map-preview/public/data/arukihenro-routes.json
ln -s ../../../output/henro-helper-routes/henro-helper-routes.geojson map-preview/public/data/henro-helper-routes.geojson
ln -s ../../../output/henro-helper-routes/henro-helper-pois.geojson map-preview/public/data/henro-helper-pois.geojson
ln -s ../../../output/ohenro88-routes/ohenro88-routes.geojson map-preview/public/data/ohenro88-routes.geojson
ln -s ../../../output/ohenro-no-akari-routes/henro-no-akari-route.geojson map-preview/public/data/henro-no-akari-routes.geojson
ln -s ../../../output/app-map-assets map-preview/public/data/app-map-assets
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
| `VITE_TRAIL_URL` | `/data/shikoku-nature-trail.pmtiles` | 四國自然步道 PMTiles（`shikoku_nature_trail` vector layer）；留空停用 |
| `VITE_TRAIL_LIST_URL` | `/data/shikoku-nature-trail.geojson` | 官方路線索引，用於依縣與課程選擇；留空停用 selector |
| `VITE_HENROYADO_LODGING_URL` | `/data/shikoku-henroyado-lodging.pmtiles` | Henroyado 住宿 PMTiles（`lodging` vector layer）；留空停用 |
| `VITE_MIN88_LODGING_URL` | `/data/shikoku-min88-lodging.pmtiles` | min88 住宿 PMTiles（`lodging` vector layer）；留空停用 |
| `VITE_MIZUTANI_HENRO_URL` | `/data/shikoku-mizutani-henro.pmtiles` | 水谷遍路導覽圖 PMTiles（routes + POIs layers）；留空停用 |
| `VITE_SEKAIISAN_HENRO_URL` | `/data/shikoku-sekaiisan-henro.geojson` | 四国遍路世界遺産登録推進協議会（88sekaiisan.org）引導線 GeoJSON（source edges）；**是原始官方 source linework，不是推論 corridor / 導航保證**；留空停用 |
| `VITE_PLAN_GRAPH_URL` | `/data/sekaiisan-henro-plan-graph.json` | 互動規劃用的 compact routing graph（`output/sekaiisan-henro-plan-graph.json`，由 `python3 -m sekaiisan_henro export-plan-graph` 產生；內建 `--bridge-m` 5m 跨 component 橋接重疊線，53 components → 2，~3.5MB）。規劃模式在瀏覽器直接抓這份做本地 Dijkstra；留空停用互動規劃 |
| `VITE_OHENRO88_PLAN_GRAPH_URL` | `/data/ohenro88-plan-graph.json` | OHenro 88 互動規劃 graph（`output/ohenro88-routes/ohenro88-plan-graph.json`，由 `python3 scripts/build-ohenro88-plan-graph.py` 產生；3m proximity-merge + chain collapse + 端點 join，~4.5MB）。規劃模式可用下拉切換網路；留空停用該網路 |
| `VITE_ARUKIHENRO_URL` | `/data/arukihenro-routes.json` | 歩き遍路 routes 正規化 JSON（`output/arukihenro-routes.json`，~5MB inline GeoJSON）。**ohenro.jp 個人手繪 + Google navigation 空間參考，不是官方／導航保證**；留空停用 |
| `VITE_HENRO_HELPER_URL` | `/data/henro-helper-routes.geojson` | Henro Helper（com.henrohelper100.app）路線 GeoJSON（`output/henro-helper-routes/henro-helper-routes.geojson`，自 APK Dart AOT literals 抽出，~11MB）。保留 App 自家分類（road/trail/special/connection/itinerary），11 個 layer 可獨立開關；留空停用 |
| `VITE_HENRO_HELPER_POIS_URL` | `/data/henro-helper-pois.geojson` | Henro Helper POI 點位 GeoJSON（`output/henro-helper-routes/henro-helper-pois.geojson`，同 APK 的 POI object-pool records，~2MB）。依 `kind` 分類（temples/bekkaku/okunoin/bangai/toilets/convenience/rest areas/tsuyado/onsen/bus/train/campground/accommodations/labels/POIs/important notes/roadside/Ishizuchi），每類圓點（z8+）+ 具名類別 label（z11+）；留空停用 |
| `VITE_OHENRO88_URL` | `/data/ohenro88-routes.geojson` | OHenro 88（com.sallyzzz.ohenroapp）路線 GeoJSON（`output/ohenro88-routes/ohenro88-routes.geojson`）。依 `route_type` 分組（main/skip/bekkaku/bekkaku_extra/extra）做 per-route selector；留空停用 |
| `VITE_OHENRO_NO_AKARI_URL` | `/data/henro-no-akari-routes.geojson` | 遍路のあかり+（jp.co.yonden.henronoakari，四国電力）步行路線 GeoJSON（`output/ohenro-no-akari-routes/henro-no-akari-route.geojson`，自 web app bundle 抽出，319 條 road-level LineString，單一連續路線）。**非官方／導航保證**；留空停用 |
| `VITE_CONTOURS_URL` | `/data/shikoku-contours.pmtiles` | 20m 等高線 PMTiles（`contours` vector layer）；留空停用 |
| `VITE_TERRAIN_URL` | `/data/shikoku-terrain.pmtiles` | Terrain-RGB 高程 PMTiles（`raster-dem`）；留空停用 |
| `VITE_SPRITE_URL` | `/data/app-map-assets/sprites/light` | 本地 sprite 基底（覆寫 style.json 的遠端 sprite） |
| `VITE_GLYPHS_URL` | `/data/app-map-assets/fonts/{fontstack}/{range}.pbf` | 本地 CJK glyph 範本（覆寫 style.json 的遠端 glyphs；`{fontstack}` 由 MapLibre GL JS 以 layer 的 `text-font` 名稱替換） |

URL 也可以直接用 query string 指定初始位置：

```
http://localhost:5173/?lat=34.191403&lon=134.206799&zoom=14
```

**Symbol smoke test**（離線字形/icon 驗證）：以本地 phase-2b assets 渲染一個
內嵌 label layer（`TEST` / `松山市` + townhall icon），重疊全開、不受碰撞隱藏：

```
http://localhost:5173/?symbolSmoke=1
```

未提供 `lat`/`lon`/`zoom` 時，smoke 模式會自動聚焦到那兩個點（松山，z13）。

## 功能

主 preview（`index.html`）預設**只顯示 basemap + 寺廟 markers**，其餘 overlay（henro 路線、
世界遺産協議会、自然步道、歩き遍路、住宿、水谷、temple labels、hillshade 等）皆由 Layers
面板手動開啟。

Layers 面板把同一來源的控制項收進 **tree**：每個來源一行（如「水谷遍路」），左側 ▸/▾
按鈕展開子項（routes / POIs / categories），行首 checkbox 是 **master**——勾選決定整個
來源要不要顯示，子項再個別細調；展開/收合與勾選互不干擾。單一 toggle 的來源（basemap
labels、henro route、世界遺産協議会、住宿、遍路のあかり）維持扁平顯示。

- **basemap**：由 `@protomaps/basemaps` 產生（light flavor、ja lang、71 layers），source 為 `pmtiles://` protocol。
- **寺廟**：GeoJSON source，紅色圓點 marker；z9+ 顯示 `番号 + 寺名` label。
- **遍路路線**：`shikoku-henro.pmtiles` 的 `henro_routes` layer（filter `route_kind=henro_candidate`），白色 casing + 赭色（`#8f4b32`）前景，位於 basemap 之上。
- **四國自然步道**：官方 `shikoku-nature-trail.com` archive 產生的 `shikoku_nature_trail` 路線與 `shikoku_nature_trail_pois` POI（圓點與名稱標籤皆為 z10+）。路線可依縣與課程選擇；每條路線與所屬 POI 一起顯示或隱藏，路線標籤及全體 POI 仍可獨立關閉。
- **Henroyado 住宿**：`shikoku-henroyado-lodging.pmtiles` 的 `lodging` layer。只含 resolved Google Place 座標；同一 Place 的重複 listing 只在地圖層收斂。使用琥珀色 marker，z11+ 顯示名稱。
- **min88 住宿**：`shikoku-min88-lodging.pmtiles` 的 `lodging` layer。只含 resolved Google Place 座標，依住宿類型著色，z11+ 顯示名稱。兩來源各有獨立圖層開關，不做跨來源合併。
- **水谷遍路導覽圖**：`shikoku-mizutani-henro.pmtiles` 的 `mizutani_henro_routes` 與 `mizutani_henro_pois` layers。路線與 POI 可分別開關；POI 從 z10 顯示圓點，名稱 label（`name`）可獨立開關，並可依 10 個 `category` 值個別篩選（label 與圓點一起依 category 篩選）。此資料僅供個人使用，詳見 `docs/mizutani_henro_map_pipeline.md`。
- **世界遺産協議会 routes**：`output/sekaiisan-henro-review/source-edges.geojson`（symlink 至 `public/data/shikoku-sekaiisan-henro.geojson`），即協議會官方四縣 KML 的 source edges（`SHE_` LineString）。藍色 casing + 前景 line layer 疊在 basemap 之上，與 OSM henro、水谷、自然步道明顯區分。這是**原始官方 source linework，不是推論 corridor／合成連線**，也不代表可導航保證；attribution 指向 `https://88sekaiisan.org/`（四国遍路世界遺産登録推進協議会）。未設定 `VITE_SEKAIISAN_HENRO_URL` 時該 toggle 停用。
- **互動規劃（瀏覽器端 planner）**：勾選「規劃模式」後在地圖上點擊加入 A / B（可再加中間點）。側欄「互動規劃」有**網路下拉**（世界遺産協議会 / OHenro 88），選擇後抓取對應的 compact routing graph（`VITE_PLAN_GRAPH_URL` / `VITE_OHENRO88_PLAN_GRAPH_URL`），前端用與 `sekaiisan_henro/planner.py` 相同的演算法（equirectangular snap、virtual sub-edge、weighted Dijkstra、simple paths）在瀏覽器計算最短路徑；高程沿路徑頂點用既有 `shikoku-terrain.pmtiles` 的 Terrain-RGB（`VITE_TERRAIN_URL`，z14）採樣。綠色路徑 + waypoint 圓點畫在地圖，側欄「規劃高度剖面」即時更新（距離 / 爬升 / 下降 / min / max）。**不是導航保證**；規劃模式開啟時 feature click popup 暫停。未設定 `VITE_PLAN_GRAPH_URL` 時停用。
- **歩き遍路 routes**：`output/arukihenro-routes.json`（symlink 至 `public/data/arukihenro-routes.json`，~5MB，瀏覽器直接 fetch 成單一 inline GeoJSON source）。90 routes / 91 maps，展平 324 lines + 933 POIs。紫色 line casing + line，route title line-label，POI circles + labels（z10/11+）。每條 route 可獨立開關（lines 與 POIs 一起消失）；master、labels、POIs 各別控制。40→41 與 68→69 來源無 KML，故 checkbox disabled（「無 KML」）。attribution 指向 `https://ohenro.jp/blog/arukihenro/`；**是 ohenro.jp 個人手繪 + Google navigation 空間參考，不是官方／導航保證**。未設定 `VITE_ARUKIHENRO_URL` 時該 toggle 停用。
- **Henro Helper routes**：`output/henro-helper-routes/henro-helper-routes.geojson`（symlink 至 `public/data/henro-helper-routes.geojson`，~11MB）。自 Henro Helper App（com.henrohelper100.app）APK 的 Dart AOT 座標 literals 抽出，保留 App 自家分類：`black/red/green`（road）、`blue/purple`（trail）、`special`（渡輪/纜車）、`eighty88to1`（88→1 閉環）、`connection`（接點，Point）、`itinerary_56/49/42`（三套每日行程線）。非 itinerary 的 8 個 layer 各自獨立 checkbox（預設只開 black）；itinerary 三套各自 `<details>` 展開，**可逐日勾選**（如 `DAY 1A`、`DAY 27C`）或「全部」，line + label 一起顯示。座標含海拔（`[lon,lat,elevation]`），每條 polyline 有 `elevation_start/end/min/max/mean`；itinerary feature 另帶 `day_label` / `title` / `from_temple` / `to_temple` / `distance` / `elevation` / `time`。未設定 `VITE_HENRO_HELPER_URL` 時該 toggle 停用。
- **Henro Helper POIs**：`output/henro-helper-routes/henro-helper-pois.geojson`（symlink 至 `public/data/henro-helper-pois.geojson`，~2MB）。同一個 APK 的 POI 點位（2,475 Point），座標來自 App PP pool 的 `Obj!LatLng` 預建物件（`off_8`=lat / `off_10`=lon），多語欄位保留於 `field_XX`。依 `kind` 分 20 類獨立開關（master + labels + 每類 checkbox）：temples（88，圓點 + 「番号 寺名」label）、bekkaku/okunoin/bangai、toilets/shower、convenience stores（含座位）、rest areas / rest toilets / tsuyado、onsens、bus / train stations、campgrounds（正式+非正式）、accommodations（宿坊/民宿/旅館…）、place labels、points of interest、important notes（路線封閉等提示）、roadside stations、Ishizuchi 行程。具名類別 z11+ 顯示 label（`name_ja`/`name_en`）。未設定 `VITE_HENRO_HELPER_POIS_URL` 時該 toggle 停用。
- **遍路のあかり+ routes**：`output/ohenro-no-akari-routes/henro-no-akari-route.geojson`（symlink 至 `public/data/henro-no-akari-routes.geojson`）。自遍路のあかり+ web app（`app.henro-no-akari.com`，四国電力）的 Leaflet map bundle 抽出（`MapPage.js` 內嵌 GeoJSON）。319 條 road-level LineString 分段、28,405 點、全長約 1,236 km，構成單一連續步行路線（316/319 段端點與鄰段相接）；line color 沿用來源 `_color`（App 渲染為藍色）。原生 APK 本身不含任何路線幾何，此為 web 端資料。**非官方／導航保證**；attribution 指向 `https://app.henro-no-akari.com`。未設定 `VITE_OHENRO_NO_AKARI_URL` 時該 toggle 停用。
- **高程視覺化**（`scripts/build-elevation-visuals.sh` 產出，資料來源 `output/shikoku-elevation-dem10.sqlite`）：
  - **color relief**：`elevation-dem-style` source 的 `color-relief` 圖層，預設隱藏，可獨立開關。
  - **hillshade**：同一 source 的 `hillshade` 圖層，預設隱藏，可獨立開關。
  - **等高線**：`shikoku-contours.pmtiles` 的 `contours` layer（`elevation_m`），預設隱藏；z12–z15 可手動開啟，100m 主線較粗，標籤可獨立切換。
  - **3D terrain**：`elevation-dem-terrain` source 經 `map.setTerrain()` 啟用（exaggeration 1）。
  - 資料 attribution 為國土地理院（GSI），寫在 PMTiles metadata 與 MapLibre source。
  - 未設定 `VITE_CONTOURS_URL` / `VITE_TERRAIN_URL` 時對應 toggle 停用，basemap 與 Henro 圖層照常載入。
- **點擊檢查**：只對 overlay 資料（非 basemap `protomaps` source）的 feature 回應。popup 以來源標籤 + 主要名稱作標題，`名稱/類別/番號/路線 ID/距離/標高等` 精選欄位以表格顯示，座標與 zoom 標在標題下；其餘未整理屬性收進可展開的「其他屬性」（`field_XX` 多語 raw 欄位與已知雜訊 key 會略過）。點擊 basemap（道路、水系、地名…）不顯示任何資訊。
- **Debug panel**：zoom、lat/lon、bearing、pitch，以及圖層顯示/隱藏切換。
- **字形/icon**：預設改為本地 phase-2b assets（`public/data/app-map-assets`，symlink 到 `output/app-map-assets`），`VITE_SPRITE_URL` / `VITE_GLYPHS_URL` 可覆寫；不再依賴 Protomaps 遠端 assets。可用 `?symbolSmoke=1` 驗證字形與 icon。

## 重新產生 basemap style

style 來自 `@protomaps/basemaps`（與 Protomaps Basemaps 一致的定義），避免手寫 70+ layers：

```bash
npm run style:generate          # light flavor, ja
npm run style:generate dark en  # 其他 flavor / 語言
```

產生後可再疊加 Henro layers（在 `src/map.ts` 的 `map.on("load")` 中）。

## 路線編輯器（Route Editor）

離線手動建置遍路區間路線的編輯器，於 `http://localhost:5173/editor.html`。它是獨立的
框架-free TypeScript 模組（`src/editor/`），**不做自動路由**：所有 geometry 都來自使用者
明確選取的已匯入 source，且連續性只認**座標完全相等**。這對應根目錄 `sekaiisan_henro`
管線的 section 手動審查/補建需求——先以編輯器建好每段路線，再匯出成後續管線輸入。

### 輸出 API（dev server 專用）

Vite dev server 透過 `configureServer` 中間件（`output-api-plugin.ts`）在本機暴露一個受限的
output 檔案 API，讓編輯器直接讀寫根目錄的 `output/`，不再需要手動下載/上傳檔案：

- dev server 預設只綁定 `127.0.0.1`；遠端使用請走 SSH port forwarding，不把寫入 API
  直接暴露到區網。PUT 另要求同源 client header，避免其他網站對 localhost 發動跨站寫入。
- **List / Read**：`GET /api/output/files` 列出 `output/` 下所有 `.json` / `.geojson` /
  `.kml` 檔案（path + size）；`GET /api/output/file?path=...` 讀取單一檔。讀取**拒絕
  symlink 與 path traversal**（`..`/絕對路徑/反斜線），且檔案大小上限 **64 MiB**。
- **Write（受限）**：`PUT /api/output/file?path=...` 只允許寫到
  `route-editor/{projects,final,qa}/` 下的檔名（`[A-Za-z0-9._-]`，`Content-Length` 亦受限）。
  寫入是 **atomic**（同目錄暫存檔 → fsync → rename），失敗不留殘檔。
- **無 delete API**：輸出檔只能覆寫或由本機手動移除。
- **Static build 無此 API**：`configureServer` 只在 dev server 生效，production build
  沒有 filesystem 能力；靜態部署時輸出瀏覽器/寫入按鈕失效（`Output API unavailable`），
  仍可退回本地檔案讀取。

### 匯入與圖層控制

- 每個 source（GeoJSON / JSON / KML，可多選）經 `importSourceFile` 讀取：算 SHA-256
  （`SRC_<hash前16>` 即 source id）、偵測格式、正規化 geometry、指派確定性 feature ID
  （prefer `Feature.id` → `properties.id` → `F_<hash>_<index>`，duplicate ID 直接拒絕）、
  以 hash 決定顏色。
- source 為**不可變**輸入：只儲存一次正規化 FeatureCollection，含 `importWarnings`
  （非致命問題），geometry 是唯一權威來源。
- 每個 source 五個 runtime layer（fill / outline / line / hitbox / poi），側欄可
  **Visible**（顯示/隱藏）、**Selectable**（是否參與點擊命中）、**Color**（換色）、
  **Remove**（被任一 section 參考時禁止移除）。polygon 僅供顯示 context，永不 selectable。

### 建置 workflow

1. **Create section**：在側欄輸入 ID（如 `SEC_1_2`）→ Create，產生 `humanSelected: true`
   的空 section（含 from/to POI、from/to anchor、waypoints、legs）。
2. **Explicit POI**：點 `Set start/end POI`（arming）後點擊地圖，從命中候選 chooser 選一個
   POI 點。POI 是離散的 reference（source/feature/座標），**不會**加到 route geometry 或長度。
3. **Explicit anchor / line-range**：`Set start/end anchor` 或 `Line range` 工具點兩次同一
   source feature part，`extractLineRange` 抽出區間成為一條 leg。anchor 是線上點 reference
   （part/segment/fraction），leg 的 `coordinates`/`direction`/`lengthM` 由權威 source
   geometry 抽出。line-range 兩端必須在同一 source feature part；零長度 range 會被拒絕。
4. **leg 操作**：每個 leg 可 Reverse / 上移 / 下移 / Delete，全部經 undo/redo checkpoint。

### Hover 高亮（authoritative）

- 滑鼠移到地圖上時，依目前工具 hover 對應的可操作 kind：`Line range` 或 armed
  anchor → hover line；armed POI → hover POI；`Pan` 或未 armed → 清除。多候選時只
  **視覺高亮**確定性的第一筆，點擊仍會開 chooser 讓使用者選，hover 永不自動 commit。
- 高亮一律從**權威 source feature** 重建：line hit 只高亮 `hit.partIndex` 對應的**整段**
  line part（`enumerateLineParts`），並顯示該 part 首尾的 start/end marker
  （綠色起點、橘色終點）；POI hit 只高亮 `hit.coordinate`（黃色）。這些 marker 只是
  **ephemeral 視覺標示**，方便辨識 Line range 的可選範圍 —— 不做 endpoint snapping、
  不寫 project/model/history，實際 leg 仍由兩次 click 的 nearest authoritative
  positions 決定，不改變點擊/擷取語義。絕不用 rendered/tiled 候選 geometry。hover
  只寫入一個 ephemeral GeoJSON source（放在 imported source 之上、draft route 之下），
  不修改 project/model/history，也不會增加 undo checkpoint。

### Auto-order selected legs（exact only）

- Active Section 的 refs/summary 與 legs 列表旁有 **`Auto-order selected legs (exact only)`**
  按鈕：只**重排 / 反向**目前已選的 `section.legs`，使它們形成單一 from-anchor → to-anchor
  的 unique simple chain。
- **不是 auto-routing**：不會從所有 source features 選 path / subset、不會新增 leg/join、
  不會 snapping/proximity、不會用 POI offset 距離。方向以 **exact anchors** 為準（POI 可能
  偏離 route，所以不能用 `fromPoi`/`toPoi` 排序；概念上由 start/end POI 指定區間，實際方向
  以對應 anchors 為準）。
- 安全判定全為 **exact WGS84 座標相等**：要求 from/toAnchor、每條 leg 消耗一次、id 唯一、
  geometry>=2 且首尾與 start/end.coordinate exact 一致；拒絕 self-loop/cycle、不同 component
  （含極小座標差）、branch（degree>2）、額外 terminals、parallel ambiguity，以及落在 leg
  interior 的 anchor（不自動 split）。需反向的 leg 會 swap start/end、reverse coordinates、
  flip direction，保留 id/sourceId/featureId/partIndex/lengthM。
- 成功且 `changed` 才用一次 `applySectionChange` 取代 `section.legs`（只一個 undo checkpoint）；
  成功但已正確則只 report（`changed=false`，不多餘建 checkpoint）；失敗完全不 mutation 並
  report 清楚 reason。

### 直接輸出 workflow（dev server）

`editor.html` 開啟後自動列出 `output/` 的檔案（`refreshOutputLists`）：

- **Load Selected from Output**（來源瀏覽器，多選）：把 output 內的 `.json` / `.geojson` /
  `.kml` 當作 source 直接匯入（同樣經 SHA-256 / 格式偵測 / 確定性 feature ID）。
- **Open from Output**（專案瀏覽器）：直接讀取 `route-editor/projects/*.json` 開啟專案。
- **Save Project to Output** 與 **Final / QA 按鈕**不再下載檔案，而是 atomic 寫入
  `output/route-editor/{projects,final,qa}/`（檔名依專案 ID 而定），寫完自動刷新列表。
- 本地檔案輸入（`<input type=file>`）仍是 fallback：API 不可用或想從任意路徑讀取時照常可用。

### Exact-only 連續性 / gap 語義

- 兩條相鄰 leg 之間**唯一**的自動銜接判準是**座標完全相等**（WGS84 位元相等）。端點座標
  不相等即視為 gap，報出 metric distance。
- POI 偏移（POI→anchor 的 offset）與 gap **永不**成為 leg，因此**自動排除**在 route length
  之外；`routeLengthM` 是各 leg 長度總和，`totalGapM` 是各 gap 距離總和。
- section status：`empty`（無 leg）/ `continuous`（無 gap）/ `has_gaps`。

### Undo / Redo

- 每個變更 section 的操作前會 `structuredClone` 快照 sections 陣列（source 不快照，編輯期間
  固定）；undo/redo 在 bounded（100 層）undo/redo 堆疊間交換並重繪。Ctrl/⌘+Z undo、
  Ctrl/⌘+Shift+Z redo。開啟/取代專案時重置 history。

### 專案 JSON（canonical、self-contained）

- **Save Project** 產出確定性、pretty、遞迴 key-sorted 的 JSON（trailing newline、無
  timestamp），`kind: ohenro_route_editor_project`、schema_version 1。來源 geometry 與 section
  全部內嵌，故是**自包含**單一檔案。在 dev server 下直接 atomic 寫入
  `output/route-editor/projects/ohenro-project-<projectId>.json`（不再下載檔案）。
- **Open Project JSON** 把 JSON 視為 untrusted 信任邊界：重新驗證內嵌 source
  FeatureCollection、source hash/ID/basic fields、每個 POI/line ref 必須能解析到內嵌權威
  feature，並**重算**每個 leg 的 coordinates/direction/length（`extractLineRange` +
  `lineLengthM`）——**絕不信賴**存檔的 derived 值，stale/malformed 一律 throw、不猜測。
- 未通過 parse 的專案不會改動 live 專案。

### Final vs QA 匯出（GeoJSON / KML）

- **Final**（qa=false）：只有 `continuous` 且無 validation issue、無缺 POI/anchor 的 section
  才匯出；任何 empty / has_gaps / 有 issue / 缺端點的 section 或空專案會**直接 throw**，不產
  出壞結果。連續 leg 只在 exact 共享邊界合併為單一 LineString，另附 from/to POI 與 anchor
  Point。
- **QA**（qa=true）：可匯出 has_gaps 的 section（leg 作為 MultiLineString），並加
  `visualization_only: true` 的 gap 與 POI-offset LineString 診斷；structurally invalid leg
  即使 QA 也不匯出。
- **KML** 是從同一個衍生 GeoJSON FeatureCollection 轉換而來（DOM + XMLSerializer，非字串
  拼接）：`Sections` / `POIs` / `QA Diagnostics` 三個 folder，`lon,lat,0` 座標，ExtendedData
  帶 properties。KML/GeoJSON 都是**衍生匯出**，不是 canonical 格式。在 dev server 下 Final /
  QA 按鈕 atomic 寫入 `output/route-editor/{final,qa}/ohenro-<final|qa>-<projectId>.{geojson,kml}`
  （不再下載檔案）。

### 明確的 MVP 限制

- **無自動路由**：沒有 routing graph、沒有導航實體、沒有自動 joining；每個 leg 都是使用者
  明確選取。
- **visualization-only 診斷不可選成 leg**：從 QA/GeoJSON 匯入的 POI-offset 與 gap
  LineString（`visualization_only` / `review_visualization_only`，或 `kind`/`type` 為
  `poi_offset`/`gap`）仍會作為 context 顯示，但**不能**被選成 leg、不會被 hover 高亮、也不回報
  為權威 line hit（hitbox filter 與 authoritative hit-test 同時排除）。
- **無隱式 crossing / proximity joins**：跨線交叉或近距端點不會被自動連接；連續性只有 exact
  座標相等一種判準，其餘都只是「有距離的 gap」供審查。
- **KML / GeoJSON 是衍生匯出**：唯一的真相是 self-contained project JSON；重新開啟專案會
  重算 leg，導出的 GeoJSON/KML 是唯讀審查或後續管線輸入，不是可回寫的來源。

## 驗證

```bash
npm run build   # tsc + vite build
npm test        # vitest run（editor 核心單元測試）
```

手動驗證重點：

1. 地圖可平移/縮放。
2. 88 座寺廟 marker 都出現；temple-088（大窪寺）在預設中心附近。
3. 點擊寺廟 popup 顯示 `temple-088` 等 canonical ID。
4. 日文字型（靈山寺、大窪寺…）正常渲染。

5. Henroyado 與 min88 住宿各自顯示，並可分別開關；點擊 marker popup 顯示 provider、stable `source_id`、聯絡方式與價格等 PMTiles properties。

6. 高程視覺化（需 `output/shikoku-contours.pmtiles` 與 `output/shikoku-terrain.pmtiles`）：
   - 無 elevation URL 時既有 preview 正常載入。
   - hillshade 預設隱藏；開啟後不蓋掉道路、地名與遍路路線。
   - color relief 可獨立開關。
   - contour 在 z12 以下不出現，z12 以上可讀。
   - 100m 主線較粗且有標籤。
   - 3D terrain 開關可恢復平面地圖。
   - terrain 啟用後點擊可取得合理高程。
    - 海面沒有低高程彩色方塊或尖峰。

7. 水谷遍路導覽圖（需 `output/shikoku-mizutani-henro.pmtiles`）：
   - routes 與 POIs 可分別開關。
   - 關閉任一 POI category 後，該類別 marker 消失，其餘類別保持顯示。
   - 點擊 marker popup 顯示 `category`、`icon_id`、來源 style 與純文字 description。

8. 路線編輯器（`/editor.html`）：
   - 載入 GeoJSON/KML，側欄可切換 Visible / Selectable / Color / Remove。
   - 建立 section，arm start/end POI 與 anchor，用 line-range 點兩次同一 feature part 產生 leg。
   - `continuous` 顯示 route length；製造一個 gap（不同座標的兩 leg）後狀態變 `has_gaps` 且顯示 gap 距離。
   - Undo / Redo（Ctrl/⌘+Z）可回復/重做 leg 與 section 變更。
   - Save Project 後可 Open 回讀（leg 由內嵌 source 重算）；Export Final 在有 gap 時應 fail，
     Export QA 應產出含 gap/offset 診斷的檔案。

## 後續（依 reference 計畫 Phase 5–6）

- 將同一份 style.json 用於 MapLibre Android，比對 Web/Android 渲染差異。
- 寺廟 schema 穩定後以 Planetiler 把 `temples.geojson` 併入 `henro.pmtiles`，移除 GeoJSON source。
