# Shikoku Map Data Catalog（資料目錄）

這份文件是**資料索引**：讓其他 AI agent 或開發者快速知道
**哪裡有資料、是什麼格式、內容大綱、如何存取**。它不是操作手冊
（操作流程在 `AGENTS.md` 與各 `docs/*.md`）；這裡只回答「去哪邊找 + 有什麼可用」。

一律假設以下路徑相對 repo 根目錄（`ohenro-map-data/`）。

---

## 0. 快速導覽

| 資料 | 主要檔案 | 格式 | 數量 | 一句話 |
|---|---|---|---|---|
| 統合資訊 POI | `output/pois/pois.geojson` | GeoJSON | 15,159 點 | 全來源 POI 統一分類，app 過濾用 |
| 統合 POI 離線 | `output/shikoku-info-pois.pmtiles` | PMTiles (MVT) | 3538 tiles | 單一 `info_pois` layer |
| 88 札所 | `output/temples.geojson` / `temples.json` / `content.sqlite` | GeoJSON / JSON / SQLite | 88 | canonical 寺廟資料 |
| 協議會（路線+寺+廁所） | `output/sekaiisan-henro-normalized.json` | JSON | 1506 線 / 88 寺 / 599 廁所 | 四國遍路世界遺產協議會 |
| Mizutani POI | `output/mizutani-henro-pois.geojson` | GeoJSON | 2,680 | 水谷遍路導覽圖 |
| 自然步道 POI | `output/shikoku-nature-trail-pois.geojson` | GeoJSON | 1,568 | 四國自然步道 |
| 步行遍路點 | `output/arukihenro-routes.json` | JSON | 933 點 | ohenro.jp 步行遍路 |
| Henro Helper POI | `output/henro-helper-routes/henro-helper-pois.geojson` | GeoJSON | 2,475 | Henro Helper app |
| OSM 住宿 | `output/lodging.geojson` | GeoJSON | 1,161 | OSM extractor |
| Henroyado 住宿 | `output/henroyado/*.jsonl` | JSONL | 702 | henroyado.com |
| min88 住宿 | `output/min88-lodging/*.jsonl` | JSONL | 650 | min88.jp |
| 底圖 | `output/shikoku-basemap.pmtiles` | PMTiles | ~112MB | Protomaps，10 layers |
| 高程 | `output/shikoku-terrain.pmtiles` + `shikoku-contours.pmtiles` | PMTiles | 1.3GB / 211MB | Terrain-RGB + 20m 等高線 |
| 互動規劃 graph | `output/*-plan-graph.json` ×3 | JSON | — | map-preview 規劃用 |
| App 離線包 manifest | `output/app-map-manifest.json` | JSON | — | Android 安裝清單 |

---

## 1. POI 資料（重點）

### 1.1 統合資訊 POI — `output/pois/`

```text
output/pois/pois.geojson        # FeatureCollection，15,159 點
output/pois/pois-report.json    # per-source / per-category accounting
output/shikoku-info-pois.pmtiles# 離線 tile（單一 info_pois layer）
```

**統一 `category` taxonomy（app 過濾層級，15 類）**：

`temple / shrine / toilet / water / rest_area / food / shop / transport / onsen / sightseeing / wayfinding / warning_hazard / experience_note / route_endpoint / other`

每筆 feature properties：

| 欄位 | 說明 |
|---|---|
| `poi_id` | 穩定唯一 ID（如 `MHM_P_...` / `SHT_tokushima_1` / `osm-...`） |
| `source` | `temples` / `sekaiisan` / `mizutani` / `nature_trail` / `arukihenro` / `osm` |
| `source_category` | **原來源分類**（不丟失，如 mizutani 的 `water_toilet_rest`） |
| `category` | 統一分類 |
| `name` | 顯示名稱 |
| 其他 | source 特有：廁所有 `address`/`hours`/`toilet_type`/`washlet`/`prefecture`；temple 有 `number`；arukihenro 有 `photos`；mizutani 有 `description`/`url`/`icon`/`color` |

來源 → 統一 category 對應（詳見 `AGENTS.md`「統合資訊 POI」）：
- `temples.geojson`（88）→ `temple`
- `sekaiisan`：88 札所 → `temple`；599 廁所 → `toilet`
- `mizutani`（exclude lodging）：`temple→temple`、`transport→transport`、`shop_supply→shop`、`food→food`、`wayfinding→wayfinding`、`warning_hazard→warning_hazard`、`experience_note→experience_note`、`other→other`；`water_toilet_rest` 以 name 啟發式拆 `rest_area`/`onsen`/`water`
- `nature_trail`：tourism_spot + kml_poi → `sightseeing`
- `arukihenro`（exclude lodging）：`temple_related→temple`、`shrine→shrine`、`waymarker/route_feature/elevation_mileage→wayfinding`、`food_shop→food`、`onsen→onsen`、`viewpoint/sightseeing→sightseeing`、`rest_area→rest_area`、`route_endpoint→route_endpoint`
- `osm`（basemap 抽取）：`station/bus_stop→transport`、`toilets→toilet`、`drinking_water→water`、`shelter→rest_area`、`convenience→shop`

**lodging 一律不在這裡**（有獨立 henroyado / min88 / OSM 管線）；**跨來源不去重**（同一寺廟可能出現在多個 source，app 端以 source+category 過濾）。

### 1.2 88 札所（canonical）

```text
output/temples.geojson   # Point ×88，properties: id/type/number/name_ja/name_en/name_kana
output/temples.json      # list ×88，詳盡：full_name{ja,en}、address、history、image、phone、temple{founded,founder,principal_deity,sect}
output/content.sqlite    # features table ×88，payload_json 同 temples.json（provider=seichijunrei）
```

### 1.3 協議會（世界遺産登錄推進協議會）— `output/sekaiisan-henro-normalized.json`

```jsonc
{
  "schema_version": 1,
  "routes":    [/* 1506 條 LineString，含 prefecture/part/source_fid/raw_name */],
  "temples":   [/* 88 座，id=TEMPLE_N, number, name_jp */],
  "toilets":   [/* 599 個，見下 */],
  "toilet_defects": [/* 1 個 kochi 座標 typo（1330000212,32.7873752），不臆測修正 */],
  "accounting": { "routes":1506, "temples":88, "toilets":599, "toilet_defects":1, ... }
}
```

廁所 schema：`id`(`SHT_<pref>_<n>`)、`prefecture`、`raw_type`（如「公衆トイレ」「施設内トイレ」）、`facility_name`、`address`、`hours`、`available_days`、`open`、`close`、`toilet_type`、`washlet`、`notes`、`geometry`。

### 1.4 各來源 POI 細節

| 來源 | 檔案 | category 欄位 | 備註 |
|---|---|---|---|
| Mizutani | `output/mizutani-henro-pois.geojson`（2680） | `category`：temple/transport/shop_supply/food/water_toilet_rest/other/experience_note/wayfinding/warning_hazard/lodging | 另有 `icon`/`color`/`url`/`description`；geometry 是 `[lon,lat]` |
| 自然步道 | `output/shikoku-nature-trail-pois.geojson`（1568） | `kind`：`tourism_spot`(394) / `kml_poi`(1174) | `poi_id`(`SNT_...`)、`route_id`、`content_id` |
| 步行遍路 | `output/arukihenro-routes.json` 的 `routes[].maps[].points[]`（933） | `category`：temple_related/waymarker/food_shop/route_endpoint/lodging/viewpoint/elevation_mileage/onsen/sightseeing/rest_area/shrine/route_feature/other | 385 點帶 `photos` URL |
| Henro Helper | `output/henro-helper-routes/henro-helper-pois.geojson`（2475） | `kind`：temple/bekkaku/okunoin/bangai/toilet/shower/convenience_store/rest_area/onsen/bus_stop/train_station/campground/accommodation/label/poi/... | 有 `name_ja`/`name_en`/`temple_number` |

### 1.5 住宿（獨立管線，**不在**統合 POI）

| 來源 | 檔案 | 數量 |
|---|---|---|
| OSM | `output/lodging.geojson` | 1,161（properties: subtype/address/phone/website/rooms/beds/...） |
| Henroyado | `output/henroyado/{detect,raw,v1,v1-geocoded}.jsonl` + `map.geojson` | 702 筆（geocoded 582 有座標） |
| min88 | `output/min88-lodging/{raw,v1,v1-geocoded}.jsonl` + `map.geojson` | 650 筆（geocoded 640 有座標） |

離線 tiles：`output/shikoku-henroyado-lodging.pmtiles`、`output/shikoku-min88-lodging.pmtiles`。

---

## 2. 路線資料

| 資料集 | 檔案 | 格式/數量 | 說明 |
|---|---|---|---|
| 步行遍路 | `output/arukihenro-routes.json` | JSON，90 routes / 91 maps / 324 lines / 933 points | schema v1：每 route 有 region/title/from/to_temple/temple_range；每 map 有 `lines` + `points` |
| OHenro 88 | `output/ohenro88-routes/ohenro88-routes.geojson` | GeoJSON，280 LineString | App 抽取，`[lon,lat,elev]` |
| Henro Hub | `output/henrohub-routes/henrohub-routes.geojson` | GeoJSON，1884 LineString | properties: `route_id`/`route_role`(canonical_shikoku88/unique_alternative/transition_connector/continuity_fallback)/`route_class`(black/red/green/blue/purple/special)/`route_sets`/`name`。**授權未定，非正式管線** |
| Henro Helper | `output/henro-helper-routes/`（`henro-helper-routes.geojson` 11MB + 各 `*.geojson`） | GeoJSON | 依 category 拆分（black/red/...、itinerary_*、accommodations_* 等）；含該目錄的 `README.md` |
| 遍路のあかり | `output/ohenro-no-akari-routes/henro-no-akari-route.geojson` | GeoJSON，319 | + `manifest.json` |
| 四國自然步道 | `output/shikoku-nature-trail.geojson` / `shikoku-nature-trail.json` | GeoJSON / JSON，123 courses / 145 segments | json 含 tourism_spots + KML Placemarks |
| Mizutani 路線 | `output/mizutani-henro-routes.geojson` | GeoJSON | 水谷遍路導覽圖路線 |
| 協議會路線 | `output/sekaiisan-henro-normalized.json` 的 `routes`（1506） | JSON LineString | 官方引導線 source edges |

### 協議會 graph / topology（QA 專用，非顯示資料）

```text
output/sekaiisan-henro-normalized.json             # normalize（上）
output/sekaiisan-henro-topology-inventory.json     # 拓撲診斷
output/sekaiisan-henro-graph.json                  # exact graph（source edges）
output/sekaiisan-henro-graph-proximity.json        # + proximity joins
output/sekaiisan-henro-graph-anchors.json          # + temple anchors（traversal_edges）
output/sekaiisan-henro-temple-sections.json        # 87 區間候選（candidate/ambiguous/disconnected）
output/sekaiisan-henro-section-corridors.json      # 區間 corridor（edge union）
output/sekaiisan-henro-section-corridor-edges.geojson
output/sekaiisan-henro-arukihenro-attribution.json # edge→區間空間歸屬
output/sekaiisan-henro-review/                     # QGIS 審閱 pack（source-edges/topology/anchors/sections/review-items/report）
```

---

## 3. 互動規劃 graph（map-preview 用）

schema_version 2，**topology/geometry 分離**：`nodes` + `traversal_edges` + `synthetic_joins` 只含參考與權重，折點集中在 `edge_geometry`。

```text
output/sekaiisan-henro-plan-graph.json    # 協議會（2080 nodes / 1744 traversal / 452 joins）
output/ohenro88-routes/ohenro88-plan-graph.json   # OHenro 88（7534 nodes / 11579 edges / 765 joins）
output/henrohub-routes/henrohub-plan-graph.json   # Henro Hub（2303 nodes；含 3D 高程）
```

前端消費：`map-preview/src/planner.ts`（Dijkstra + snap）。

---

## 4. 底圖與高程

```text
output/shikoku-basemap.pmtiles    # Protomaps Basemap；z0-15；10 layers：
                                  #   boundaries/buildings/earth/landcover/landuse/places/pois/roads/water
                                  #   pois layer kind：station/bus_stop/toilets/drinking_water/shelter/convenience/...
output/shikoku-contours.pmtiles   # 20m 等高線 MVT，z12-15
output/shikoku-terrain.pmtiles    # Terrain-RGB PNG，z6-14（DEM10 基底）
output/shikoku-elevation.sqlite   # GSI DEM5+DEM10B 合併 SQLite（metadata/elevation_tiles/source_tiles）
output/shikoku-elevation-dem10.sqlite  # DEM10-only（視覺化基底）
```

查詢：`cargo run --manifest-path gsi-dem/Cargo.toml --release -- query-db output/shikoku-elevation.sqlite --lat .. --lon ..`。

---

## 5. Android App 離線包

```text
output/app-map-manifest.json   # schema_version 3；files[] 含 role/path/url/size/sha256
output/app-map-assets/         # sprites/ + fonts/ + licenses/（glyph 範圍見 scripts/app-map-assets/noto-...-ranges.txt）
output/content.sqlite          # 88 寺廟詳細內容（features table）
```

CORE_PACK roles：`style` / `basemap` / `mizutani` / `nature_trail` / `henroyado` / `min88` / `temples` / `content`。規格見 `docs/app_map_manifest.md`。

---

## 6. 個人使用 overlay（非正式管線）

```text
output/shikoku-henrohub.pmtiles     # Henro Hub 路線（z0-14，henrohub_routes layer，1884 條）
output/shikoku-info-pois.pmtiles    # 統合資訊 POI（見 §1.1）
output/shikoku-mizutani-henro.pmtiles  # Mizutani 全圖（routes + pois）
```

這些 metadata 標 `usage: personal-use`，**未加入** app-manifest CORE_PACK；Henro Hub 授權未定。

---

## 7. 檔案格式速查

| 格式 | 說明 | 產生方式 |
|---|---|---|
| **GeoJSON** | 標準 FeatureCollection；properties 欄位因來源不同 | 各 `scripts/build-*.py` |
| **JSON** | 結構化資料集（routes/points/graph/manifest） | normalize / export |
| **JSONL** | 一筆一列（henroyado / min88 Raw→V1） | `python3 -m henroyado|min88_lodging` |
| **PMTiles** | 離線地圖 tiles（MVT/PNG）；`pmtiles show --metadata` 看內容 | tippecanoe + `pmtiles convert` |
| **SQLite** | 高程（elevation_tiles）或內容（features table） | `gsi-dem build` / `build-content-sqlite.py` |

讀取 PMTiles 內容：`pmtiles show --metadata <file>`（layer/fields/tilestats）。MVT tile 解碼：python `mapbox_vector_tile` + `pmtiles.reader`（注意 tile gzip：`header["tile_compression"] == Compression.GZIP` 時先 `gzip.decompress`）。

---

## 8. map-preview（web 互動地圖）

資料經 `map-preview/public/data/*` symlink 或 `/data/*` URL 載入（vite `outputApiPlugin` / `public` symlink）。各 layer 由 `.env.development` 的 `VITE_*_URL` 開關。Source code 在 `map-preview/src/`（每資料集一個 module：`henrohub.ts`、`info-pois.ts`、`arukihenro.ts`、`ohenro88.ts`、`henro-helper-pois.ts` ...）。