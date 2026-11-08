# Shikoku Map Data Catalog（資料目錄）

這份文件是**資料索引**：讓其他 AI agent 或開發者快速知道
**哪裡有資料、是什麼格式、內容大綱、如何存取**。它不是操作手冊
（操作流程在 `AGENTS.md` 與各 `docs/*.md`）；這裡只回答「去哪邊找 + 有什麼可用」。

一律假設以下路徑相對 repo 根目錄（`ohenro-map-data/`）。

**來源目錄**：所有來源已完整搬遷至 `datasets/<來源>/`，原始資料在 `raw/`、
產出在 `output/`，來源專屬程式與文件也在同一目錄。來源總覽與操作入口見
[`datasets/README.md`](../datasets/README.md)。根目錄 `output/` 僅放共用 App
assets／manifest、route packs 與人工編輯成果。

---

## 0. 快速導覽

| 資料 | 主要檔案 | 格式 | 數量 | 一句話 |
|---|---|---|---|---|
| 步行遍路建置報告 | `datasets/arukihenro_routes/reports/pipeline.json` | JSON | 單一 normalized JSON | 來源快照／程式碼／產出 hash、summary；操作見 §2 |
| 統合資訊 POI | `datasets/info_pois/output/pois.geojson` | GeoJSON | 16,763 點 | 精選 POI 統一分類，app 過濾用 |
| 統合 POI 離線 | `datasets/info_pois/output/shikoku-info-pois.pmtiles` | PMTiles (MVT) | 3769 tiles | 單一 `info_pois` layer |
| 88 札所 | `datasets/seichijunrei/output/temples.geojson` / `temples.json` / `content.sqlite` | GeoJSON / JSON / SQLite | 88 | canonical 寺廟資料 |
| 88 札所離線 tiles | `datasets/seichijunrei/output/shikoku-temples.pmtiles` | PMTiles (MVT) | 88 unique IDs | `temples` layer，z0–14，未加入共用 App manifest |
| 協議會（路線+寺+廁所） | `datasets/sekaiisan_henro/output/sekaiisan-henro-normalized.json` | JSON | 1506 線 / 88 寺 / 599 廁所 | 四國遍路世界遺產協議會 |
| 協議會一鍵建置報告 | `datasets/sekaiisan_henro/reports/pipeline.json` | JSON | 核心 15 檔／可選 17 檔 | snapshot、設定、驗證摘要、產出 hash；最新隔離實跑 594 廁所，見 §1.3 |
| Mizutani POI | `datasets/mizutani_henro_map/output/mizutani-henro-pois.geojson` | GeoJSON | 2,572（2026-11-09） | 水谷遍路導覽圖；保留 1 筆未分類 warning |
| 自然步道 POI | `datasets/shikoku_nature_trail/output/shikoku-nature-trail-pois.geojson` | GeoJSON | 1,568 | 四國自然步道 |
| 自然步道來源／建置報告 | `datasets/shikoku_nature_trail/raw/{current.json,snapshots/}`、`datasets/shikoku_nature_trail/reports/pipeline.json` | HTML / images / KML / JSON | 123 courses / 123 KML / 1,040 images | 完整 archive 驗證後切換 current；五份產出整組驗證發布 |
| 步行遍路點 | `datasets/arukihenro_routes/output/arukihenro-routes.json` | JSON | 933 點 | ohenro.jp 步行遍路 |
| 點檢活動路線 | `datasets/omotenashi_henro_inspection/output/omotenashi-henro-inspection-routes.geojson` | GeoJSON | 319 LineString / 28,405 座標 | 一日一斉おもてなし遍路道ウォーク覆蓋；不是通行／維護保證 |
| Henro Hub 更新來源／報告 | `datasets/henrohub/raw/{current.json,snapshots/}`、`datasets/henrohub/reports/pipeline.json` | JSON / GeoJSON | 1,884 routes；release `henro-route-network-20260927-1028` | 公開 channel/manifest 驗證下載；個人使用，不授予再散布權 |
| 遍路のあかり更新來源／報告 | `datasets/ohenro_no_akari/raw/{current.json,snapshots/}`、`datasets/ohenro_no_akari/reports/pipeline.json` | JS / JSON / GeoJSON | 319 線 / 28,405 頂點 | 靜態解析公開網站 bundle，不執行來源 JS；同資料不重發 |
| OHenro 88 更新來源／報告 | `datasets/ohenro88/raw/{current.json,snapshots/}`、`datasets/ohenro88/reports/pipeline.json` | APK/XAPK / JSON | App 1.1.0 / versionCode 24 | 驗證套件／版本／archive／assets hash；只靜態讀取，不執行 App |
| Henro Helper POI | `datasets/henro_helper/output/henro-helper-pois.geojson` | GeoJSON | 2,471（2.26.111） | Henro Helper app，88 札所；另有 5 筆非空間原始記錄 |
| Henro Helper 原始快照／建置報告 | `datasets/henro_helper/raw/{current.json,snapshots/}`、`datasets/henro_helper/reports/pipeline.json` | XAPK/APK / JSON | 最新 ARM64 archive 240,093,231 bytes | API 版本／SHA1、本機 SHA256、native libs、產出 hash 與完整 accounting |
| OSM 住宿 | `datasets/osm/output/lodging.geojson` | GeoJSON | 1,161 | OSM extractor |
| Henroyado 住宿 | `datasets/henroyado/output/*.jsonl` | JSONL | 702 | henroyado.com |
| min88 住宿 | `datasets/min88_lodging/output/*.jsonl` | JSONL | 650 | min88.jp |
| 底圖 | `datasets/osm/output/shikoku-basemap.pmtiles` | PMTiles | ~112MB | Protomaps，10 layers |
| 高程 | `datasets/gsi/output/shikoku-terrain.pmtiles` + `shikoku-contours.pmtiles` | PMTiles | 1.3GB / 211MB | Terrain-RGB + 20m 等高線 |
| 高程原始資料／建置索引 | `datasets/gsi/raw/`、`datasets/gsi/reports/{updates,pipeline}.json` | ZIP / JSON | 692 ZIP（2026-11-04 清單） | 官方四國版本清單、本機 SHA-256 與產出 hash |
| 互動規劃 graph | `output/*-plan-graph.json` ×3 | JSON | — | map-preview 規劃用 |
| App 離線包 manifest | `output/app-map-manifest.json` | JSON | — | Android 安裝清單 |

---

## 1. POI 資料（重點）

### 1.1 統合資訊 POI — `datasets/info_pois/output/`

```text
datasets/info_pois/output/pois.geojson        # FeatureCollection，16,763 點
datasets/info_pois/output/pois-report.json    # per-source / per-category accounting
datasets/info_pois/output/shikoku-info-pois.pmtiles# 離線 tile（單一 info_pois layer，~2.7MB）

> **設計原則**：統合 POI 只放**精選的特別有用點**（廁所/旅館/水/休息/溫泉/
> 主要交通/便利商店 + 各來源核心 POI）。其餘 OSM 點（restaurant/shop/學校/
> 醫院/crossing 等）**留在 basemap 的 `pois` layer 原生顯示**，不重複抽。
```

**統一 `category` taxonomy（app 過濾層級，16 類）**：

`temple / shrine / toilet / water / rest_area / food / shop / transport / onsen / sightseeing / wayfinding / warning_hazard / lodging / experience_note / route_endpoint / other`

每筆 feature properties：

| 欄位 | 說明 |
|---|---|
| `poi_id` | 穩定唯一 ID（如 `MHM_P_...` / `SHT_tokushima_1` / `osm-...`） |
| `source` | `temples` / `sekaiisan` / `mizutani` / `nature_trail` / `arukihenro` / `osm` |
| `source_category` | **原來源分類**（不丟失，如 mizutani 的 `water_toilet_rest` 或 OSM 的 `restaurant`） |
| `category` | 統一分類 |
| `name` | 顯示名稱 |
| 其他 | source 特有：廁所有 `address`/`hours`/`toilet_type`/`washlet`/`prefecture`；temple 有 `number`；arukihenro 有 `photos`；mizutani 有 `description`/`url`/`icon`/`color`；OSM 有 `kind_detail`/`name_ja` |

來源 → 統一 category 對應（詳見 `AGENTS.md`「統合資訊 POI」）：
- `temples.geojson`（88）→ `temple`
- `sekaiisan`：88 札所 → `temple`；599 廁所 → `toilet`
- `mizutani`（exclude lodging）：`temple→temple`、`transport→transport`、`shop_supply→shop`、`food→food`、`wayfinding→wayfinding`、`warning_hazard→warning_hazard`、`experience_note→experience_note`、`other→other`；`water_toilet_rest` 以 name 啟發式拆 `rest_area`/`onsen`/`water`
- `nature_trail`：tourism_spot + kml_poi → `sightseeing`
- `arukihenro`（exclude lodging）：`temple_related→temple`、`shrine→shrine`、`waymarker/route_feature/elevation_mileage→wayfinding`、`food_shop→food`、`onsen→onsen`、`viewpoint/sightseeing→sightseeing`、`rest_area→rest_area`、`route_endpoint→route_endpoint`
- `osm`（basemap `pois` layer，**精選 kind 抽出，11,371 點**）：`toilets→toilet`、
  `drinking_water/water_point/fountain→water`、`hotel/guest_house/hostel/motel/camp_site/chalet→lodging`、
  `shelter/rest_area/picnic_table→rest_area`、`public_bath/hot_spring/sauna→onsen`、
  `station/bus_stop→transport`、`convenience→shop`；**其餘 ~490 種 kind 留在
  basemap 原生 `pois` layer，不抽入統合 POI**。geometry 用 mercantile tile-bounds 內插回經緯度；`--skip-osm` 可跳過

**lodging 註記**：統合 POI 現含 OSM 的 lodging（hotel/guest_house/hostel/motel/camp_site 等 1,276 點）；Henroyado / min88 兩套專屬住宿管線**仍不在此**（各有獨立 JSONL + PMTiles）。**跨來源不去重**（同一寺廟/餐廳可能出現在多個 source，app 端以 source+category 過濾）。

### 1.2 88 札所（canonical）

```text
datasets/seichijunrei/output/temples.geojson   # Point ×88，properties: id/type/number/name_ja/name_en/name_kana
datasets/seichijunrei/output/temples.json      # list ×88，詳盡：full_name{ja,en}、address、history、image、phone、temple{founded,founder,principal_deity,sect}
datasets/seichijunrei/output/content.sqlite    # features table ×88，payload_json 同 temples.json（provider=seichijunrei）
datasets/seichijunrei/output/shikoku-temples.pmtiles # temples layer，z0–14，88 unique canonical IDs，309 tiles（2026-11-04 實跑）
```

入口 `python3 -m datasets.seichijunrei`，自動抓 map/all、驗證來源、保留舊 snapshot，
建置以上四檔並驗證。PMTiles properties 同 GeoJSON（nullable 字串可能省略）；
canonical ID 使用 `properties.id`，不依賴 MVT 的 numeric feature ID。
`reports/pipeline.json` 記錄 source_url/input_sha256/build_config/temple_count/outputs
（size、sha256）；未變則跳過，`--force` 強制重建。操作見
[`datasets/seichijunrei/README.md`](../datasets/seichijunrei/README.md)。首次隔離實跑的
PMTiles 位於 `/tmp/opencode/temples-check/output/`，正式 output 需執行入口產生。

### 1.3 協議會（世界遺産登錄推進協議會）— `datasets/sekaiisan_henro/output/sekaiisan-henro-normalized.json`

一鍵入口 `python3 -m datasets.sekaiisan_henro run`：更新 12 KML 後建置 normalized、
topology inventory、exact/proximity/anchors graph、87 sections/corridors、corridor GeoJSON、
plan graph 與 6 檔 review pack。可選 `--arukihenro PATH` 同時產生兩層 attribution。
`reports/pipeline.json` schema：`inputs`（snapshot_sha256/metadata_sha256）、
`build_config`（bridge_m/arukihenro_sha256/shapely_version/source_sha256）、
`validation`（來源 accounting、區間／corridor status、plan nodes/edges）、
`outputs`（相對 output 路徑 → size/sha256）。全部未變時跳過重建。
操作與 archive 位置見 [`datasets/sekaiisan_henro/README.md`](../datasets/sekaiisan_henro/README.md)。

2026-11-05 全量隔離實跑（`/tmp/opencode/sekaiisan-check/`）：snapshot `dc5c5a86…`，
1494 route Placemarks / 1506 lines / 36,350 vertices / 88 temples / **594 toilets + 1 defect**。
正式 output 尚未替換（上方 599 為既有正式資料）。plan graph 為 2080 nodes /
1744 traversal edges / **443 joins**；新 exporter 去除同一 bridge ID 的重複候選
（舊版 452 joins 中有 9 筆重複），source/exact graph 不受影響。
87 sections：candidate 34 / ambiguous 17 / disconnected 23 / anchor_review_required 13；
87 corridors：corridor 28 / branched_corridor 23 / disconnected 23 / anchor_review_required 13。

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
| Mizutani | `datasets/mizutani_henro_map/output/mizutani-henro-pois.geojson`（2572） | `category`：temple/transport/shop_supply/food/water_toilet_rest/other/experience_note/wayfinding/warning_hazard/lodging | 另有 `icon`/`color`/`url`/`description`；geometry 是 `[lon,lat]` |
| 自然步道 | `datasets/shikoku_nature_trail/output/shikoku-nature-trail-pois.geojson`（1568） | `kind`：`tourism_spot`(394) / `kml_poi`(1174) | `poi_id`(`SNT_...`)、`route_id`、`content_id` |
| 步行遍路 | `datasets/arukihenro_routes/output/arukihenro-routes.json` 的 `routes[].maps[].points[]`（933） | `category`：temple_related/waymarker/food_shop/route_endpoint/lodging/viewpoint/elevation_mileage/onsen/sightseeing/rest_area/shrine/route_feature/other | 385 點帶 `photos` URL |
| Henro Helper | `datasets/henro_helper/output/henro-helper-pois.geojson`（2471，2.26.111） | `kind`：temple/bekkaku/okunoin/bangai/toilet/shower/convenience_store/rest_area/onsen/bus_stop/train_station/campground/accommodation/label/poi/... | 有 `name_ja`/`name_en`/`temple_number`；5 筆純文字／URL 記錄保留於 extraction-report，不猜座標 |

### 1.5 住宿（專屬管線，獨立於統合 POI）

以下住宿**不進**統合 POI（§1.1 的 OSM basemap lodging 除外）；Henroyado / min88 各有獨立 JSONL + PMTiles。

| 來源 | 檔案 | 數量 |
|---|---|---|
| OSM extractor | `datasets/osm/output/lodging.geojson` | 1,161（properties: subtype/address/phone/website/rooms/beds/...） |
| Henroyado | `datasets/henroyado/output/{detect,raw,v1,v1-geocoded}.jsonl` + `map.geojson` | 702 筆（geocoded 582 有座標） |
| min88 | `datasets/min88_lodging/output/{raw,v1,v1-geocoded}.jsonl` + `map.geojson` | 650 筆（geocoded 640 有座標） |

離線 tiles：`datasets/henroyado/output/shikoku-henroyado-lodging.pmtiles`、`datasets/min88_lodging/output/shikoku-min88-lodging.pmtiles`。

---

## 2. 路線資料

步行遍路一鍵入口 `python3 -m datasets.arukihenro_routes run`：重新下載四縣列表、
路線 HTML、My Maps KML，驗證後切換 `raw/current.json` 指向的 immutable
`raw/snapshots/<sha256>/`，再發布既有 schema v1。legacy 平面 archive 仍可離線建置。
`reports/pipeline.json`：archive_sha256/source_sha256/output/output_sha256/size/summary；
summary 沿用 normalized 各數量，再加 degenerate_line_count（單頂點來源線）。
2026-11-05 隔離線上實跑 snapshot `141a6a2d…`：90 routes / 91 maps /
324 lines / 933 points / 385 photo points，0 warnings、degenerate_line_count=1；
獨立驗證與重建未變跳過皆通過。
JSON／程式碼／產出 hash 皆未變則不重發。操作見
[`datasets/arukihenro_routes/README.md`](../datasets/arukihenro_routes/README.md)。

| 資料集 | 檔案 | 格式/數量 | 說明 |
|---|---|---|---|
| 步行遍路 | `datasets/arukihenro_routes/output/arukihenro-routes.json` | JSON，90 routes / 91 maps / 324 lines / 933 points | schema v1：每 route 有 region/title/from/to_temple/temple_range；每 map 有 `lines` + `points` |
| OHenro 88 | `datasets/ohenro88/output/ohenro88-routes.geojson` | GeoJSON，172 線幾何（67 LineString + 105 MultiLineString）＋108 Point | App 1.1.0 / 24 抽取，路線含 `[lon,lat,elev]`；另有 sections、PlanGraph |
| Henro Hub | `datasets/henrohub/output/henrohub-routes.geojson` | GeoJSON，1884 LineString | properties: `route_id`/`route_role`(canonical_shikoku88/unique_alternative/transition_connector/continuity_fallback)/`route_class`(black/red/green/blue/purple/special)/`route_sets`/`name`。自動更新公開 release；**授權未定，個人使用** |
| Henro Helper | `datasets/henro_helper/output/`（`henro-helper-routes.geojson` + 各 `*.geojson`） | GeoJSON，1,586 LineString + 2,501 Point（2.26.111） | 依 App layer 拆分（black/red/...、itinerary_*、accommodations_* 等）；操作見 `datasets/README.md` 的 Henro Helper 一鍵更新 |
| 遍路のあかり | `datasets/ohenro_no_akari/output/henro-no-akari-route.geojson` | GeoJSON，319 LineString / 28,405 頂點 | + `manifest.json`：來源 URL、bundle/HTML/snapshot hash、長度／邊界 accounting |
| 四國自然步道 | `datasets/shikoku_nature_trail/output/shikoku-nature-trail.geojson` / `shikoku-nature-trail.json` | GeoJSON / JSON，123 courses / 145 segments | json 含 tourism_spots + KML Placemarks |
| Mizutani 路線 | `datasets/mizutani_henro_map/output/mizutani-henro-routes.geojson` | GeoJSON，128 LineString | 水谷遍路導覽圖路線；另有 overlay 與 routes-only PMTiles |
| 協議會路線 | `datasets/sekaiisan_henro/output/sekaiisan-henro-normalized.json` 的 `routes`（1506） | JSON LineString | 官方引導線 source edges |
| 點檢活動路線 | `datasets/omotenashi_henro_inspection/output/omotenashi-henro-inspection-routes.geojson` | GeoJSON，319 LineString / 28,405 座標 | 原 Placemark、名稱、folders、description、style、原次序與高度原樣保留；不拼接或簡化 |

自然步道一鍵入口 `python3 -m datasets.shikoku_nature_trail`：重新下載四縣列表、
detail HTML 與全部 KML；僅在 owning detail 與圖片 provenance/檔案 hash 一致時
重用圖片。完整 archive 驗證後保存 immutable snapshot/current，再產出
normalized JSON、routes/POIs/report 與 PMTiles（route + POI 兩層）。
支援 fetch/build/validate、run --local、run/build --force 及路徑／限速覆寫；
既有 normalize/verify/report 分步命令亦會解析 current snapshot。
來源／設定／五份產出 hash 相同才略過；缺課程、缺圖片、KML 錯誤不替換有效資料。
2026-11-09 全量線上更新與離線重建通過：123 courses、145 route segments、
65,753 route vertices、1,568 POIs、686 tourism spots、1,040 images、
0 normalization warnings；22 項來源測試通過，相同選定快照 hash/mtime 不變。

OHenro 88 一鍵入口 `python3 -m datasets.ohenro88`：沿用 APKPure App API
讀取套件 `com.sallyzzz.ohenroapp` 的最新版，驗證 APK/XAPK identity、CRC、
來源雜湊與完整 assets 後保存 immutable snapshot/current，靜態讀取
`trails_all.geojson`、`merged.json`。支援 fetch/build/validate、run --local、
run/build --force、`--archive <本機 APK/XAPK>`；不安裝或執行 App。
完整產出 routes GeoJSON、87 sections + 88→1 closure、schema v2 PlanGraph。
2026-11-09 1.1.0 / 24 全量：172 線／108 點，graph 7,536 nodes、
11,581 edges、749 synthetic joins、1 component。收縮平行 path 的 edge ID
保留來源邊 identity；已在相同 node 的 interior contact 只切邊，不產生 self-join。
15 項邊界測試、線上未變更 skip/hash/mtime，以及實際前端 planRoute
（寺 1→2→5，candidate，9,369m）通過。第三方 APK 不等同開發者簽章可信。

遍路のあかり一鍵入口 `python3 -m datasets.ohenro_no_akari`：從官方 HTML
及同源 module graph 找到唯一完整路線 bundle（不依賴固定檔名），保存已驗證
不可變快照，再靜態抽取 GeoJSON + manifest。支援 fetch/build/validate、
run --local、run/build --force 及 raw/output/reports 路徑覆寫。
來源路線內容 hash 與程式／產出 hash 相同時跳過，只有部署 HTML 變更不重發。
2026-11-09 線上全量建置、獨立驗證與本機快照重跑通過；319 線、28,405 頂點、
1,236,349.47m，8 項邊界測試通過。不是官方或導航保證。

Henro Hub 一鍵入口 `python3 -m datasets.henrohub`：讀取公開 beta channel、
release manifest 及其 planner GeoJSON，驗證 manifest 宣告的 size/SHA256 與
所有 feature，保存 immutable snapshot/current，再產出 routes GeoJSON、
main+alternative-only plan graph（3D 高程保留）與 `shikoku-henrohub.pmtiles`。
支援 fetch/build/validate、run --local、run/build --force、`--source` 手動匯入。
`reports/pipeline.json` 記錄來源 release/hash、設定／程式、三份產出的 hash 與
routes/graph accounting；相同線上 release 實跑確認 skip、hash/mtime 不變。
2026-11-09 全量 1,884 線／301,458 頂點；graph 2,309 nodes、2,840 edges、
152 synthetic joins、4 components（largest 2,303）。修正 degree-2 收縮後
不同平行 path 共用 edge ID 的問題，geometry lookup 不再覆蓋不同路徑。
6 項邊界測試與實際前端 planRoute（寺 1→2→5，candidate，8,246m）通過。
不抓取非本管線的 Supabase POI，不將商業資產視為開放授權。

水谷一鍵入口 `python3 -m datasets.mizutani_henro_map`：更新／驗證 My Maps KML，
保存不可變 snapshot，再產出 normalized JSON、routes/POIs/report/diff，
`shikoku-mizutani-henro.pmtiles`（routes+pois）與 `mizutani-henro-routes.pmtiles`
（單一 routes layer）。`reports/pipeline.json` 包含當前／diff baseline snapshot、
程式／設定與七份產出的 hash；本機來源、設定及所有產出未變才略過。
Google hosted-image URL 每次請求可能輪替：這是真實來源位元組變更，保留新快照、
不以假 URL 遮蔽；相同選定快照的 `run --local` 已確認 hash/mtime 不變。
2026-11-09 全量 2,700 Placemarks（128 線／2,572 點），七份產出、
兩組 PMTiles 實際 z14 feature/fields 驗證通過，10 項來源測試通過。
1 個未分類 Point 以原始值與 warning 保留，非不完整下載。

點檢活動一鍵入口 `python3 -m datasets.omotenashi_henro_inspection`：重新從官方頁
及其地圖程式發現當前 KML，完整解析驗證後更新 immutable snapshot/current，
發布 routes GeoJSON 與 `output/source-metadata.json`；`reports/pipeline.json`
記錄來源／程式與全部產出 hash、feature/line/coordinate counts/bounds。
無參數即 run，另有 fetch/build/validate、run --local、run/build --force。
2026-11-09 snapshot `655ee2eb…` 全量建置與獨立驗證通過；再次線上更新確認
hash/mtime 不變，6 項來源測試及 4 項共用發布邊界測試通過。
權利保留、只代表點檢活動覆蓋；操作見
[`來源說明`](../datasets/omotenashi_henro_inspection/docs/omotenashi_henro_inspection_source.md)。

### Henro Helper 自動更新與產出契約

`python3 -m datasets.henro_helper` 從 APKPure App API 查詢
`com.henrohelper100.app`，選 ARM64 APK/XAPK、驗證後保存
`raw/snapshots/<archive_sha256>/`（`archive.xapk` 或 `archive.apk`、
`api-response.pb`、`metadata.json`、`lib/arm64-v8a/{libapp.so,libflutter.so}`）。
`raw/current.json` 的 `archive_sha256` 選目前快照；`metadata.json` 保存
package_name/version_name/version_code/archive/archive_size/source_sha1/
archive_sha256/libraries（兩個 native lib 的 SHA256）與 source_api。

固定 revision Blutter 靜態反組譯 → 既有來源分類的 per-layer GeoJSON →
`henro-helper-routes.geojson` 與 `henro-helper-pois.geojson`。保留 App 分類、
來源順序、index-based feature ID、路線高程／itinerary metadata、多語 POI 與
raw field offsets；不跨來源去重，不作官方／導航宣稱。
真正只有一個頂點的來源 path 保存為 Point，不偽造 LineString 或丟棄。

`output/extraction-report.json`：`routes[layer]` 的 features/points/
reference_constructors/singleton_path_count；`pois[layer]` 的 records/features/
unresolved_coordinates/nonspatial_records。純文字而非座標的 source record
保留 index/class/原始 fields/reason，不輸出虛構 POI；未知或無法解析的座標會
阻止發布。驗證 per-layer 與 combined 內容相同、座標有限且位於四國、88 札所完整、
records = features + nonspatial_records（unresolved 必須為 0）。

`reports/pipeline.json`：package_name/version_name/version_code/input_sha256、
build_config（Blutter revision／所有抽取程式 hash）、tooling、summary，
及每份 output 的 size/sha256。來源／程式／產出未變則跳過；先驗證整組再逐檔發布。
操作、工具依賴與第三方 APK 的完整性／簽章限制見
[`datasets/README.md`](../datasets/README.md#henro-helper-一鍵更新)。

2026-11-09 全量實跑：2.26.111 / versionCode 26111，snapshot `409336c7…`；
45 份發布檔。路線／接點共 4,087 features、425,397 頂點（含 2,499 connection
points 與 2 個 singleton paths）；POI 2,471（88 札所完整），另保留 5 筆
純文字原始記錄，0 unresolved coordinates。獨立 `validate` 通過，再次線上
更新確認跳過建置且所有產出／報告 hash 與 mtime 不變；損壞 native cache
情境確認不改動已發布檔。33 項來源／抽取／驗證邊界測試通過。

### 協議會 graph / topology（QA 專用，非顯示資料）

```text
datasets/sekaiisan_henro/output/sekaiisan-henro-normalized.json             # normalize（上）
datasets/sekaiisan_henro/output/sekaiisan-henro-topology-inventory.json     # 拓撲診斷
datasets/sekaiisan_henro/output/sekaiisan-henro-graph.json                  # exact graph（source edges）
datasets/sekaiisan_henro/output/sekaiisan-henro-graph-proximity.json        # + proximity joins
datasets/sekaiisan_henro/output/sekaiisan-henro-graph-anchors.json          # + temple anchors（traversal_edges）
datasets/sekaiisan_henro/output/sekaiisan-henro-temple-sections.json        # 87 區間候選（candidate/ambiguous/disconnected）
datasets/sekaiisan_henro/output/sekaiisan-henro-section-corridors.json      # 區間 corridor（edge union）
datasets/sekaiisan_henro/output/sekaiisan-henro-section-corridor-edges.geojson
datasets/sekaiisan_henro/output/sekaiisan-henro-arukihenro-attribution.json # edge→區間空間歸屬
datasets/sekaiisan_henro/output/sekaiisan-henro-review/                     # QGIS 審閱 pack（source-edges/topology/anchors/sections/review-items/report）
```

---

## 3. 互動規劃 graph（map-preview 用）

schema_version 2，**topology/geometry 分離**：`nodes` + `traversal_edges` + `synthetic_joins` 只含參考與權重，折點集中在 `edge_geometry`。

```text
datasets/sekaiisan_henro/output/sekaiisan-henro-plan-graph.json    # 協議會（2080 nodes / 1744 traversal / 452 joins）
datasets/ohenro88/output/ohenro88-plan-graph.json   # OHenro 88（7534 nodes / 11579 edges / 765 joins）
datasets/henrohub/output/henrohub-plan-graph.json   # Henro Hub（2303 nodes；含 3D 高程）
```

前端消費：`map-preview/src/planner.ts`（Dijkstra + snap）。

---

## 4. 底圖與高程

GSI 一鍵管線：`python3 -m datasets.gsi`（官方四國版本清單 → 本機 ZIP 驗證 →
merge → tile → 完整及 DEM10-only SQLite → contours/Terrain-RGB → 驗證後發布）。
下載需登入官方網站後手動放入 `datasets/gsi/raw/DEM5/{5A,5B,5C}/` 與 `DEM10B/`；
`check` 只查更新，`--local` 跳過線上清單。`reports/updates.json` 保存官方 records、
missing_or_updated、obsolete_or_extra；`reports/pipeline.json` 保存 input_sha256 與
outputs 的 size/sha256 與 `build_config`（環境設定、管線程式碼 hash）；輸入、設定、
產出 hash 皆未變時跳過重建，`--force` 強制重建。`merge.json`、`tile.json`、
`validation.json` 為建置 accounting。
操作見 [`datasets/gsi/README.md`](../datasets/gsi/README.md)。

OSM 一鍵管線：`python3 -m datasets.osm`（Geofabrik checksum 更新檢查 → PBF
下載 → 編譯 profiles → 底圖／hiking PMTiles＋住宿抽取 → 驗證後發布）。
手動放檔到 `datasets/osm/raw/shikoku-latest.osm.pbf` 後用 `--local`；舊 PBF
保存在 `datasets/osm/raw/snapshots/<sha256>.osm.pbf`。建置來源與產出 hash 記在
`datasets/osm/reports/pipeline.json`。詳細操作見
[`datasets/osm/README.md`](../datasets/osm/README.md)。

```text
datasets/osm/output/shikoku-basemap.pmtiles    # Protomaps Basemap；z0-15；10 layers：
                                  #   boundaries/buildings/earth/landcover/landuse/places/pois/roads/water
                                  #   pois layer：~500 kinds（restaurant/hotel/station/toilets/...）
                                  #   = 所有 OSM 點的「原生」顯示層；§1.1 只精選抽出少數 kind
datasets/gsi/output/shikoku-contours.pmtiles   # 20m 等高線 MVT，z12-15
datasets/gsi/output/shikoku-terrain.pmtiles    # Terrain-RGB PNG，z6-14（DEM10 基底）
datasets/gsi/output/shikoku-elevation.sqlite   # GSI DEM5+DEM10B 合併 SQLite（metadata/elevation_tiles/source_tiles）
datasets/gsi/output/shikoku-elevation-dem10.sqlite  # DEM10-only（視覺化基底）
```

查詢：`cargo run --manifest-path datasets/gsi/gsi-dem/Cargo.toml --release -- query-db datasets/gsi/output/shikoku-elevation.sqlite --lat .. --lon ..`。

---

## 5. Android App 離線包

```text
output/app-map-manifest.json   # schema_version 5；files[] 含 role/path/url/size/sha256
output/app-map-assets/         # sprites/ + fonts/ + licenses/（glyph 範圍見 scripts/app-map-assets/noto-...-ranges.txt）
datasets/seichijunrei/output/content.sqlite          # 88 寺廟詳細內容（features table）
```

CORE_PACK roles（8 個唯一核心 role）：`style` / `basemap` / `henrohub` / `info_pois` / `nature_trail` / `henroyado` / `temples` / `content`。規格見 `docs/app_map_manifest.md`。

- 依產品政策，核心 App 地圖包只保留 **Henroyado** 住宿；**min88 不在** core pack（min88 資料仍以個人使用 dataset 留在 repo，見 §1.5 / `datasets/min88_lodging/output/shikoku-min88-lodging.pmtiles`）。
- `henrohub` 與 `info_pois` **已納入** core pack，但屬**個人使用／授權受限** asset（Henro Hub 授權未定、info-POI 彙整多個授權來源）；不得未經權利釐清公開轉發。
- 本目錄只是**資料索引**，不是自動化的 app 選料規則；App 實際打包內容以 `scripts/build-app-map-manifest.py` 的 CORE_PACK 與 `docs/app_map_manifest.md` 為準。

---

## 6. 個人使用 overlay（非正式管線）

```text
datasets/henrohub/output/shikoku-henrohub.pmtiles     # Henro Hub 路線（z0-14，henrohub_routes layer，1884 條）
datasets/info_pois/output/shikoku-info-pois.pmtiles    # 統合資訊 POI（見 §1.1）
datasets/mizutani_henro_map/output/shikoku-mizutani-henro.pmtiles  # Mizutani 全圖（routes + pois）
```

- `henrohub` 與 `info_pois`：schema v5 起**已納入** app-manifest CORE_PACK（見 §5），但仍標 `usage: personal-use`、授權受限，不可未經權利釐清公開轉發。
- `shikoku-mizutani-henro.pmtiles`：仍**未加入** app-manifest CORE_PACK，屬非正式個人使用 overlay。
- 本目錄只是**資料索引**，不是自動化的 app 選料規則；是否進 app pack 由 manifest generator 的 CORE_PACK 決定。

---

## 7. 檔案格式速查

| 格式 | 說明 | 產生方式 |
|---|---|---|
| **GeoJSON** | 標準 FeatureCollection；properties 欄位因來源不同 | 各 `scripts/build-*.py` |
| **JSON** | 結構化資料集（routes/points/graph/manifest） | normalize / export |
| **JSONL** | 一筆一列（henroyado / min88 Raw→V1） | `python3 -m datasets.henroyado|min88_lodging` |
| **PMTiles** | 離線地圖 tiles（MVT/PNG）；`pmtiles show --metadata` 看內容 | tippecanoe + `pmtiles convert` |
| **SQLite** | 高程（elevation_tiles）或內容（features table） | `gsi-dem build` / `build-content-sqlite.py` |

讀取 PMTiles 內容：`pmtiles show --metadata <file>`（layer/fields/tilestats）。MVT tile 解碼：python `mapbox_vector_tile` + `pmtiles.reader`（注意 tile gzip：`header["tile_compression"] == Compression.GZIP` 時先 `gzip.decompress`）。

---

## 8. map-preview（web 互動地圖）

資料經 `map-preview/public/data/*` symlink 或 `/data/*` URL 載入（vite `outputApiPlugin` / `public` symlink）。各 layer 由 `.env.development` 的 `VITE_*_URL` 開關。Source code 在 `map-preview/src/`（每資料集一個 module：`henrohub.ts`、`info-pois.ts`、`arukihenro.ts`、`ohenro88.ts`、`henro-helper-pois.ts` ...）。
