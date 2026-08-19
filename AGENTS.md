# Shikoku Map Data Pipeline

四國遍路 App 的離線地圖資料管線。從同一份 OSM PBF 產生兩份獨立的 PMTiles：

```text
shikoku-latest.osm.pbf
        |
        +--> Protomaps Basemaps profile --> shikoku-basemap.pmtiles (通用底圖)
        |
        +--> Custom Henro profile        --> shikoku-henro.pmtiles  (遍路 overlay)
        |
        +--> Official Nature Trail pipeline --> shikoku-nature-trail.pmtiles（見下）
```

## 目錄結構

```text
ohenro-map-data/
├── source/                    原始資料（immutable）：OSM PBF、網站快照、GSI DEM ZIPs、shikoku-nature-trail/ 官方 archive
├── basemaps/                  Protomaps Basemaps repo（外部 git clone，勿放入自訂檔案）
├── henro/                     自訂 Henro Planetiler 專案（schema 見 henro/schema.md）
│   └── scripts/               遍路寺廟資料管線（extract / normalize / generate）
├── henroyado/                 Henroyado 住宿爬蟲（Python package，Phase 1：fetcher→parse→normalize）
│   └── tests/                 regression fixtures + 單元測試
├── min88_lodging/             min88 住宿 archive / parser / normalizer / optional geocoder
│   └── tests/                 parser、normalizer、crawler I/O 與 pipeline regression tests
├── shikoku_nature_trail/      四國自然步道網站爬蟲（Python，Phase 1 raw archive；見 reference/shikoku-nature-trail-crawler-plan.md）
│   ├── crawler/               index / detail / assets / kml / manifest 子命令
│   ├── parser/                course_list + course_detail HTML parser
│   └── tests/                 fixtures + parser 單元測試
├── gsi-dem/                   GSI DEM 轉換工具（Rust，Phase 1 Inspector 完成）
├── output/                    所有產出：henroyado/{detect,raw,v1}.jsonl、temples.*、lodging.*、shikoku-nature-trail.*、五份 PMTiles（basemap/henro/contours/terrain/nature-trail）
├── scripts/                   build / validate 腳本
├── docs/                      操作文件（lodging_data_pipeline.md 等）
├── reference/                 計畫與操作文件
└── reports/                   build log 與 metadata 報告
```

遍路寺廟資料管線詳見 `reference/henro_data_pipeline.md`（更新資料時依該文件執行）。
住宿資料管線詳見 `docs/lodging_data_pipeline.md`（OSM lodging extractor，
`python3 henro/scripts/extract_lodging.py` → `output/lodging.geojson` + `lodging-report.json`）。
Henroyado 住宿爬蟲（Phase 1）詳見 `reference/henroyado-parser-standardization-plan.md`。
min88 住宿管線操作詳見 `docs/min88_lodging_pipeline.md`（規劃：
`reference/min88-lodging-parser-standardization-plan.md`）。
GSI DEM 轉換詳見 `gsi-dem/README.md`（規劃：`reference/gis-dem-converter.md`）。

## GSI DEM（Phase 1-6：Inspector + Raster correctness + DEM5 merge + DEM10B fallback + Final tiling + SQLite）

```bash
cargo run --manifest-path gsi-dem/Cargo.toml --release -- inspect source/GSI/DEM5/5A/FG-GML-513462-DEM5A-20251208.zip
cargo test --manifest-path gsi-dem/Cargo.toml
cargo run --manifest-path gsi-dem/Cargo.toml --release -- validate \
  source/GSI/DEM5/5A/FG-GML-513462-DEM5A-20251208.zip \
  source/GSI/DEM10B/FG-GML-513462-DEM10B-20161001.zip
# Phase 3+4：per-mesh merge + DEM10B fallback（20,362 meshes 全量約 57 秒）
cargo run --manifest-path gsi-dem/Cargo.toml --release -- merge \
  --input source/GSI/DEM5 --dem10b-input source/GSI/DEM10B --report /tmp/merge-report.json
# 示範 fallback 查詢路徑（DEM5 無資料 → DEM10B）
cargo run --manifest-path gsi-dem/Cargo.toml --release -- merge \
  --input source/GSI/DEM5 --dem10b-input source/GSI/DEM10B \
  --region 503354 --query-lat 33.754 --query-lon 133.544
# Phase 5：先 merge 落盤（~3.8GB），再切成 256x256 zstd tile（~1.4GB）
cargo run --manifest-path gsi-dem/Cargo.toml --release -- merge \
  --input source/GSI/DEM5 --dem10b-input source/GSI/DEM10B --out-dir work/merged
cargo run --manifest-path gsi-dem/Cargo.toml --release -- tile \
  --merged work/merged --dem10b source/GSI/DEM10B --out work/tiles \
  --check-lat 33.754 --check-lon 133.544
# Phase 6：tiles -> SQLite（540MB），並用 runtime query 查詢
cargo run --manifest-path gsi-dem/Cargo.toml --release -- build \
  --tiles work/tiles --grid /tmp/tile-report.json --output output/shikoku-elevation.sqlite
cargo run --manifest-path gsi-dem/Cargo.toml --release -- query-db \
  output/shikoku-elevation.sqlite --lat 33.754 --lon 133.544
# Phase 7：golden coordinates regression + coverage/source report
cargo run --manifest-path gsi-dem/Cargo.toml --release -- validate-db \
  output/shikoku-elevation.sqlite --golden gsi-dem/tests/golden/elevation.json
# 高程視覺化：export-vrt（raw Int16 + VRT）→ build-elevation-visuals.sh（Docker: GDAL/tippecanoe/rgbify）
cargo run --manifest-path gsi-dem/Cargo.toml --release -- export-vrt \
  output/shikoku-elevation-dem10.sqlite --layer 10 --output work/elevation/dem10.vrt
./scripts/build-elevation-visuals.sh   # -> output/shikoku-contours.pmtiles + output/shikoku-terrain.pmtiles
```

#### 高程視覺化 build（build-elevation-visuals.sh）

```bash
# 前置需求：cargo、pmtiles CLI、docker；DEM10-only SQLite（預設 output/shikoku-elevation-dem10.sqlite）

# 第一次使用：build 工具 Docker 映像（host 不需安裝 GDAL/tippecanoe/rgbify）
docker build -t ohenro-elevation-visuals -f docker/Dockerfile.elevation .

# 之後每次：從 DEM10 SQLite 一次重建兩份 PMTiles
./scripts/build-elevation-visuals.sh
# -> output/shikoku-contours.pmtiles（20m 等高線, MVT, z12-15）
# -> output/shikoku-terrain.pmtiles（Terrain-RGB, PNG, z6-14）
# 完整流程：export-vrt -> gdal_translate COG -> gdalinfo 驗證 -> gdal_contour ->
#   tippecanoe -> gdalwarp 3857 -> rgbify_dem -> pmtiles convert -> 嚴格驗證 -> npm build
# 全部 stdout/stderr 寫入 reports/elevation-visuals-build.log；
# metadata 寫入 reports/{contours,terrain}-metadata.txt；GSI attribution 寫入 PMTiles。

# 可調環境變數（只有需要時才設）
#   ELEVATION_DB=...          DEM10 SQLite 路徑（預設 output/shikoku-elevation-dem10.sqlite）
#   WORK_DIR=...              中間檔目錄（預設 work/elevation）
#   CONTOUR_INTERVAL=20       等高線間隔
#   TERRAIN_MIN_ZOOM=6 / TERRAIN_MAX_ZOOM=14
#   RGBIFY_WORKERS=4
```

- 直接從 ZIP 讀 XML entry，不將 XML 解壓到磁碟；支援 nested ZIP。
- streaming XML parser（quick-xml），tupleList → SoA（elevation f32 + mask u8）。
- 關鍵資料結構發現（詳見 `gsi-dem/README.md`）：
  - DEM5 沿海 mesh 的 sample count **不固定**（partial coverage，非損壞），
    且最後一列也可能 partial（merge 需 bounds-check）。
  - Grid row 0 = 北（north-up），與 envelope lowerCorner（SW）不同。
  - DEM10B 用 `その他,-9999.00` sentinel，無 sea 語義；DEM5 用 `海水面`/`内水面`。
  - DEM5B/5C（`数値地形`）是**混合 schema**（その他/地表面/海水面/データなし），
    且 partial mesh 常有真實資料缺口（DEM10B fallback 的用途）。
  - `内水面`（內陸水）帶真實高程，非 sentinel；`海水底面`/`内水底面`（海底/內水底）
    同樣帶真實（負）高程。全資料集 tuple label 共 7 種，全部支援。
  - 8 個 2008–2010 的 5B archive 是 **Shift_JIS 編碼**（其餘全 UTF-8），parser 依
    XML declaration 用 encoding_rs 解碼。
- Phase 2 驗證通過：`validate` 交叉比對 DEM5A/5B vs DEM10B（median |diff| ~4m、
  sea 一致性 100%、無 land-over-sea 方向錯誤）。
- Phase 3 完成：`merge` 依 primary region 群組、per-mesh A>B>C pixel-level merge，
  per-pixel 保留 source code（§16：0=NODATA, 2=DEM5C, 3=DEM5B, 4=DEM5A）。
  2026-08-17 全量結果：A=626.7M / B=6.4M / C=17.5k / nodata=54.1M pixels。
- Phase 4 完成：`merge --dem10b-input source/GSI/DEM10B` 載入獨立 10m layer，
  計算 DEM10B 對 DEM5 nodata 的填補（全量 999,851 格、佔 nodata 1.8%；
  其餘為公海，DEM10B 亦無資料）。`--query-lat/--query-lon` 示範 fallback 查詢
  （DEM5 無值 → DEM10B，如 503354 區域 335.00m）。runtime 語義：
  DEM5 有值即回、無值才 fallback DEM10（不 resample、不 merge）。
- Phase 5 完成：`tile` 把 merged .bin + DEM10B 切成 256×256 zstd int16 tile。
  固定 geographic grid（DEM5 step=1/18000°、DEM10 step=1/9000°，不 resample），
  row-sweep 有界記憶體。全量：DEM5 10,836 tiles / 633.1M valid，DEM10 2,889 tiles。
  DEM5 有效格數 == merge A+B+C 總和（無遺失）；`--check-lat/lon` 驗證 round-trip。
- Phase 6 完成：`build` 把 G5T1 tiles 讀入 SQLite（metadata / elevation_tiles /
  source_tiles，規劃 §23），540MB。`query-db` 實作 runtime 查詢
  （lat/lon → tile → zstd → sample；DEM5 無值 fallback DEM10），
  例如 (33.754,133.544) → 335.0m（DEM10）、(34.50513,134.25787) → 285.0m（DEM5）。
- Phase 7 完成：`validate-db` 做 golden coordinates regression（`tests/golden/`
  elevation.json，7 點全過，tolerance DEM5=10m / DEM10=20m）與 coverage/source
  report（source 分佈與 merge 一致）。`tests/golden.rs` 自動化 regression。
- Phase 8（Android 整合）尚未實作；`query` 目前用 nearest-cell。

## Henroyado Crawler（Phase 1：fetcher）

```bash
python3 -m henroyado fetch    # 下載全四國住宿清單，存為 source/henroyado.html
```

- 下載 `https://henroyado.com/inns` 並存為 `source/henroyado.html`。
- 只做 URL → HTML 快照（plan Step 1），不解析。
- 只存一份：base 與四個 `?pref=` URL 的 HTTP body 都包含完整四縣資料；
  `pref` 只由 `inn.js` 在瀏覽器端切換 `div.js_prefGroup` 的顯示，不會另抓資料。
- `source/henroyado.html` 已 gitignore（可重新抓取）。

### Detect（plan Step 2：記錄偵測）

```bash
python3 -m henroyado detect   # → output/henroyado/detect.jsonl
```

- 每筆住宿 = `tr.bl_table_row_frontInfo`（+ 緊接的 `tr.bl_table_row_detail`）。
- 偵測結果（2026-08-19 更新快照）：702 筆 listing（699 distinct 名稱），680 筆含
  detail card、22 筆無 detail；tokushima 137 / kochi 225 / ehime 224 / kagawa 116。
- 頁面以 164 個 table 分段：90 個 temple caption（88 札所）+ 74 個 route section
  （如 `#10-11合流後ルート`、`#19別格慈眼寺`），route section 的 record 無 temple。
- 已知 source 資料：3 組重複 listing（一富士旅館 / 松屋旅館 / 農家民宿かじか），
  detector 照樣各存一筆，不去重（plan §30）。

### Parse（plan Step 3：RawInn 抽取）

```bash
python3 -m henroyado parse   # → output/henroyado/raw.jsonl（702 筆）
```

- 每筆 = `tr.bl_table_row_frontInfo`（summary row）+ `tr.bl_table_row_detail`
  （detail card，含 h3 名稱 / description / route / お知らせ / 宿詳細 /
  料金 / お問い合わせ / マップ / carousel 圖片）。
- front row 第 4 欄的 `休業` / `閉業` 保存為 `source_context.row_status`；
  `詳細` 是按鈕文字，不視為狀態。
- 純抽取、不標準化（RawInn，plan §19）。空字串一律轉 `null`（plan §3.4）。
- 只把 <br> 保留為換行、其餘空白收斂；付款等文字未清除標點周圍空白
  （那是 Step 4 normalizer 的工作）。
- 680 張有完整 detail card、22 張只有 front row（無 detail 內容）。
- 全頁僅 2 個 Google Maps iframe（其餘 JS lazy load），embed URL 少見；
  679 張卡片有「google mapを開く」搜尋 URL。
- 圖片：只抽 `storage/inns/*` URL（去重、保留 query），**不**下載圖片。
- check_out 常缺（702 筆中僅 214 筆有）。

### Normalize（plan Step 4/5：RawInn → HenroyadoInnV1）

```bash
python3 -m henroyado normalize   # → output/henroyado/v1.jsonl（702 筆）
```

- 純函式 normalizer（`henroyado/normalize/`）：text/time/room/meal/route/
  facility/payment/map/image，各自獨立、失敗只記 warning 不丟 record。
- 結果符合 plan §5 schema：`henro.from/to_temple`（1番霊山寺→2番極楽寺）、
  `rooms.room_count`（`(\d+)部屋`，全形數字/冒號先正規化）、`meals`、
  `check_in/out`、`facilities`（icon→type 對應 + cross.png disabled）、
  `payment.methods/cards`（VISA/JCB/Mastercard/AE/UC 等）、`images.url`（去 query）。
  基礎 V1 只保留 Maps URL，不把 iframe viewport center 當作住宿座標。
- `business_status`：`休業` → `temporarily_closed`、`閉業` →
  `permanently_closed`，原文保留於 `raw.status`。更新快照共有 13 筆休業、15 筆閉業。
- **時間結構化**（`normalize/time.py`）：`check_in/out` 與 `meals.breakfast/dinner`
  各含 `time`（顯示）`start` `end`（`HH:MM`，range `15:00-19:00` 拆成
  start/end；開尾 `16:00-` → start + end null；`適宜/随時` → time null + notes；
  全形 `：`/數字與 4 位 `1500`→`15:00` 皆正常化；餐點 `06:30~` 同）。
  check_in 115 range / 227 single-or-open / 360 none（含無資料）；breakfast 164 有時間。
- 原始值保留在 `raw.*` + 各欄 `raw_text`（plan §3.3）。
- 圖片只做 URL 處理，**全程不下載 image binary**（僅 fetcher 會連網）。
- `rooms.room_count`：單一 `N部屋` 直接取；多組間數（如 Hostel 東風ノ家
  `ﾄﾞﾐﾄﾘｰ2人 1部屋. ﾄﾞﾐﾄﾘｰ4人 2部屋. 個室 2部屋`）**加總**（1+2+2=5）。
- 目前 0 warnings。

### Geocode（Google Maps embed place 補座標）

```bash
python3 -m henroyado geocode
# output/henroyado/v1.jsonl -> output/henroyado/v1-geocoded.jsonl
```

- 以每筆 `google_maps_search_url` 請求 `output=embed&hl=ja`，回應快取在
  `source/henroyado-google-maps/`；既有 cache 預設不重抓，`--force` 才更新。
- 只接受 Google place record 或 resolved URL 的
  `!8m2!3d<latitude>!4d<longitude>` marker；不使用原始 iframe 前段的
  `!2d...!3d...` viewport center。
- 保留 Google 正規化名稱、地址、place ID、CID 與請求 URL，查無單一 place
  時記 warning，不把地圖中心誤當住宿座標。
- `location.map_data_status` 區分 `source_data_incomplete`（Henroyado 無 Maps URL）、
  `pending_geocode`、`resolved`、`place_not_found`、`place_outside_shikoku` 與
  `fetch_failed`；重跑完整管線會依新版 source 自動更新。
- 2026-08-19 更新快照結果：702 筆中 582 筆有 place 座標、23 筆無 Maps URL、
  97 筆無有效單一 place（含 3 筆四國外同名結果）、0 fetch errors。基礎
  `v1.jsonl` 不含推導座標，地圖使用
  `v1-geocoded.jsonl`。

### Tests（plan Step 8：regression fixtures）

```bash
python3 -m unittest discover henroyado/tests
```

- `tests/test_normalizers.py`：normalizer 純函式單元測試（time/room/meal/route/
  payment/facility/image/map/text/geocode/status，46 個 test）。
- `tests/test_pipeline.py`：HTML fixture → RawInn → V1 == 凍結的 expected JSON
  （6 個代表性 record：ootoriien / no_meal / no_detail / multi_room /
  fullwidth_times / price）。
- fixtures 從 `source/henroyado.html` 抽真實片段：改版後跑
  `henroyado/tests/extract_fixtures.py` + `generate_expected.py` 重新凍結。

**Phase 1 狀態**：Step 1–8 全完成（fetch / detect / parse / normalize /
warnings / writers / fixtures+tests），另有 Google embed geocode enrichment；產出
`source/henroyado.html`、`output/henroyado/{detect,raw,v1,v1-geocoded}.jsonl`。

## min88 Lodging（archive + offline normalization）

```bash
python3 -m min88_lodging crawl-all
python3 -m min88_lodging parse
python3 -m min88_lodging normalize
python3 -m min88_lodging verify
python3 -m min88_lodging report
# optional, 尚未對 2026-08-19 archive 執行：python3 -m min88_lodging geocode
```

- 架構：日文列表 → `index.json` → 逐 post ID 的 immutable detail HTML archive →
  offline Raw JSONL → conservative `Min88LodgingV1`；Google Maps geocode 是獨立可選 enrichment。
- 預設 archive：`source/min88-lodging/`（`index/page.html`、`records/<id>/page.html`、
  `index.json`、`manifest.json`）；產出：
  `output/min88-lodging/{raw,v1,v1-geocoded}.jsonl` 與 `report.json`。
- crawler 預設 timeout 30 秒、單 worker、request delay 0.3 秒；有效 archive 會 resume 跳過，
  `--force` 才重抓。manifest 保存 URL/local path/status、retrieval/HTTP metadata、SHA-256、
  parser version 與完整 detail accounting；失敗不覆蓋既有有效頁。
- parser 優先讀 `.min88-basicdata-kv` hidden textarea，也支援舊版「基本情報」table；
  Raw/V1 保留來源文字，不能安全結構化的值只記 warning，不猜測、不丟 record。
- **2026-08-19 live 結果**：650 筆 list、650 張可解析 detail；tokushima 124 /
  kochi 239 / ehime 182 / kagawa 105。647 筆有 structured basic data，3 筆 source 缺資料。
  Raw/V1 各 650 筆，`verify: OK`。
- 尚餘 98 個保守 warning：3 `MISSING_REQUIRED_FIELD`、10 list/detail
  `SOURCE_NAME_MISMATCH`、85 `UNRECOGNIZED_FORMAT`（60 pricing、13 laundry、7 payment、
  4 malformed route distance、1 partial Wi-Fi state）；原值均保留，未強行推斷。
- optional geocode 尚未執行：base V1 為 647 `pending_geocode` + 3
  `source_data_incomplete`，目前沒有 `v1-geocoded.jsonl` live 結果。

## Shikoku Nature Trail（Phase 1 raw archive + Phase 2 normalization）

```bash
python3 -m shikoku_nature_trail --data-dir source/shikoku-nature-trail crawl-index   # 四縣列表 + course-index.json
python3 -m shikoku_nature_trail --data-dir source/shikoku-nature-trail crawl-details # 每 course 的 page.html + metadata/assets.json
python3 -m shikoku_nature_trail --data-dir source/shikoku-nature-trail download-assets # 內容圖片
python3 -m shikoku_nature_trail --data-dir source/shikoku-nature-trail download-kml   # Google My Maps KML
python3 -m shikoku_nature_trail --data-dir source/shikoku-nature-trail crawl-all      # index→details→assets→kml→report
python3 -m shikoku_nature_trail --data-dir source/shikoku-nature-trail verify
python3 -m shikoku_nature_trail --data-dir source/shikoku-nature-trail report
python3 -m shikoku_nature_trail --data-dir source/shikoku-nature-trail normalize --output output/shikoku-nature-trail.json
```

- 計畫：`reference/shikoku-nature-trail-crawler-plan.md`；詳見 `shikoku_nature_trail/README.md`。
- 網站結構實測：列表頁是 **div-based table**（`.courselist` + `a.row_line` + `.cel`），
  非 `<table>`；詳細頁 `iframe[src*="google.com/maps/d/"]` 的 `mid` query → KML。
- 列表欄位由 header row 建立 class→field mapping（`cel1`..`cel7`），不依賴位置。
- 詳細頁圖片只抓 `/wp-content/uploads/`（排除 theme/logo/icon）；hero background 也收。
- Phase 1 只存 raw archive：page.html + metadata.json + assets.json + images/ + map/map.kml。
- 重要檔案以 SHA-256 記錄；atomic write（temp→fsync→rename）；失敗不覆蓋有效檔。
- KML 驗證：HTTP 200 + 非空 + 內容含 `<kml>`（不信 Content-Type）；無效 body 存 `map.kml.failed`。
- resume：已存在檔案跳過，`--force` 才重抓；`crawl-state.json` 非唯一真相。
- 限速：預設 3 並發 + 0.3s delay；retry 429/5xx/timeout（exponential backoff）。
- `source/shikoku-nature-trail/` 已 gitignore（可重抓），僅爬蟲程式碼進 repo。
- Tests：`python3 -m unittest discover shikoku_nature_trail/tests`（parser fixtures）。

**Phase 1 狀態（2026-08-19）**：完整 archive 完成 —— 123 courses
（tokushima 24 / kagawa 28 / ehime 33 / kochi 38），123 張 detail HTML、
123 個 Google My Maps（全有 KML）、1040 張圖片，`verify: OK`。
Crawl report：`reports/shikoku-nature-trail-crawl-report.{json,md}`。

**Phase 2 狀態（2026-08-19）**：offline normalization 完成。輸出 schema v1
`output/shikoku-nature-trail.json`（deterministic、無 timestamp、atomic write，約 9.6MB，
已 gitignore）。每 course 合併 index 欄位、HTML introduction、`photo_point`、依來源順序的
`tourism_spots`（source URL + `assets.json` local path）、Google Maps metadata 與 KML。
KML 保留 Placemark name/description，以及 GeoJSON-compatible Point / LineString /
GeometryCollection；單 course malformed HTML/assets/KML 記 warning 後繼續，缺 index 才 fatal。
全量結果：123 courses / 123 photo points / 686 tourism spots / 1,713 Placemarks /
0 warnings；672/672 tourism spot images 成功對應 archive local path。

## 環境需求

- Java 21+
- Maven 3.8+
- git
- PMTiles CLI（`go install github.com/protomaps/go-pmtiles@latest`，binary 為 `go-pmtiles`）
- Docker（build-shikoku-nature-trail.sh 用 `ohenro-elevation-visuals` image 內的 tippecanoe）

## Build Shikoku Nature Trail（四國自然步道 Phase 3）

```bash
./scripts/build-shikoku-nature-trail.sh
# -> output/shikoku-nature-trail.pmtiles + shikoku-nature-trail.geojson
#    + shikoku-nature-trail-pois.geojson + shikoku-nature-trail-report.json
```

- 唯一來源：`source/shikoku-nature-trail/` 的 `shikoku-nature-trail.com` 官方 archive。
- 流程：offline normalize → `export-map` → tippecanoe（`--no-line-simplification`）→ PMTiles。
- Layers：`shikoku_nature_trail`（route LineString）與 `shikoku_nature_trail_pois`（Point，z10+）。
- Route ID：`SNT_<source_post_id>`；POI ID：`SNT_<source_post_id>_P####`。
- 觀光內容只在同 course 正規化名稱一對一相等時連結為 `SNT_<source_post_id>_S###`；
  不做 fuzzy matching，unmatched/ambiguous 全寫入 report。
- attribution：`shikoku-nature-trail.com`，寫入 PMTiles metadata。
- 2026-08-19 實際產出：123 routes / 145 segments / 65,753 route points /
  1,568 POIs；394/686 tourism spots 一對一連結，34 組名稱 ambiguous。

## Build Basemap

```bash
./scripts/build-basemap.sh
```

步驟：

1. 檢查 Java / pmtiles / 來源 PBF。
2. 將本機 `source/shikoku-latest.osm.pbf` 複製到
   `basemaps/tiles/data/sources/shikoku.osm.pbf`
   （用複製而非 symlink，避免 Planetiler 視為檔案不存在而重新下載）。
3. 執行 Planetiler：`java -Xmx8g -jar ... --area=shikoku --download --force`。
4. 產出移到 `output/shikoku-basemap.pmtiles`。
5. 保存 metadata 到 `reports/basemap-metadata.txt`。

`--download` 只會下載缺失的 supporting datasets（Natural Earth、water/land
polygons、landcover、qrank、pgf-encoding），不會重新下載 OSM。

## Inspect / Validate

```bash
./scripts/inspect-pmtiles.sh   # 顯示 basemap、henro、contours、terrain、trail metadata
./scripts/validate.sh          # 驗證輸出、bounds、必需 layers（失敗回傳 1）
```

## Basemap 驗證結果（2026-08-15）

- 10 個 source layers：boundaries, buildings, earth, landcover, landuse, places,
  pois, roads, water。
- bounds：131.77E–135.18E, 32.23N–34.65N（覆蓋四國）。
- zoom 0–15。
- `roads` 保留 path / footway / steps / track / pedestrian / service / residential。
- `pois` 保留 station / bus_stop / convenience / drinking_water / shelter / toilets 等 kind。

## Henro（完成 v1）

自訂 Henro Planetiler profile（`henro/`，獨立 Maven 專案，不修改 Protomaps Basemap）。

```bash
./scripts/build-henro.sh
```

- 輸入：`source/shikoku-latest.osm.pbf`（`--osm-path` 指定本機 immutable PBF）
- 輸出：`output/shikoku-henro.pmtiles`
- 產出 `henro_routes` layer（LineString，overlay，zoom 0–14）
- 抽取所有 `type=route` + `route=hiking` relations，`route_kind=henro_candidate`
  （Extraction 與 classification 分開，正式分類屬 v1.3）
- Smoke test（temporary rule）：relation `13653654` 必須出現且帶
  `name` / `network` / `route` metadata — `python3 scripts/smoke-test-henro.py`

### 驗證結果（2026-08-15）

- `henro_routes` layer：fields `relation_id / name / ref / network / route / route_kind`
- 19,921 features，1,098 tiles，739KB
- Relation `13653654`（四国遍路 1番札所霊山寺~2番札所極楽寺）在 44 個 features 中出現，
  `network=nwn`、`route=hiking`、`route_kind=henro_candidate`

Schema 詳見 `henro/schema.md`。
