# Shikoku Map Data Pipeline

四國遍路 App 的離線地圖資料管線。從同一份 OSM PBF 產生兩份獨立的 PMTiles：

```text
shikoku-latest.osm.pbf
        |
        +--> Protomaps Basemaps profile --> shikoku-basemap.pmtiles (通用底圖)
        |
        +--> Custom Henro profile        --> shikoku-henro.pmtiles  (遍路 overlay)
        |
        +--> Henro 自行? no：shikoku-trail.pmtiles 由官方 GPX/KML 產生（見下）
```

## 目錄結構

```text
ohenro-map-data/
├── source/                    原始資料（immutable）：OSM PBF、seichijunrei spots.json、henroyado.html 快照、GSI DEM ZIPs、shikoku_trail/ 四國自然步道官方 KML/GPX
├── basemaps/                  Protomaps Basemaps repo（外部 git clone，勿放入自訂檔案）
├── henro/                     自訂 Henro Planetiler 專案（schema 見 henro/schema.md）
│   └── scripts/               遍路寺廟資料管線（extract / normalize / generate）
├── henroyado/                 Henroyado 住宿爬蟲（Python package，Phase 1：fetcher→parse→normalize）
│   └── tests/                 regression fixtures + 單元測試
├── shikoku_nature_trail/      四國自然步道網站爬蟲（Python，Phase 1 raw archive；見 reference/shikoku-nature-trail-crawler-plan.md）
│   ├── crawler/               index / detail / assets / kml / manifest 子命令
│   ├── parser/                course_list + course_detail HTML parser
│   └── tests/                 fixtures + parser 單元測試
├── gsi-dem/                   GSI DEM 轉換工具（Rust，Phase 1 Inspector 完成）
├── output/                    所有產出：henroyado/{detect,raw,v1}.jsonl、temples.*、lodging.*、shikoku-trail.*、五份 PMTiles（basemap/henro/contours/terrain/trail）
├── scripts/                   build / validate 腳本
├── docs/                      操作文件（lodging_data_pipeline.md 等）
├── reference/                 計畫與操作文件
└── reports/                   build log 與 metadata 報告
```

遍路寺廟資料管線詳見 `reference/henro_data_pipeline.md`（更新資料時依該文件執行）。
住宿資料管線詳見 `docs/lodging_data_pipeline.md`（OSM lodging extractor，
`python3 henro/scripts/extract_lodging.py` → `output/lodging.geojson` + `lodging-report.json`）。
Henroyado 住宿爬蟲（Phase 1）詳見 `reference/henroyado-parser-standardization-plan.md`。
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
- 只存一份：server 忽略 `pref` 參數，任一 prefecture 頁都回傳全部 88 札所
  的完整清單（~507 筆住宿），用 base URL 抓反而多幾筆。
- `source/henroyado.html` 已 gitignore（可重新抓取）。

### Detect（plan Step 2：記錄偵測）

```bash
python3 -m henroyado detect   # → output/henroyado/detect.jsonl
```

- 每筆住宿 = `tr.bl_table_row_frontInfo`（+ 緊接的 `tr.bl_table_row_detail`）。
- 偵測結果（2026-08-16）：572 筆 listing（569 distinct 名稱），445 筆含
  detail card、127 筆無 detail；tokushima 123 / kochi 182 / ehime 163 / kagawa 104。
- 頁面以 155 個 table 分段：90 個 temple caption（88 札所）+ 65 個 route section
  （如 `#10-11合流後ルート`、`#19別格慈眼寺`），route section 的 record 無 temple。
- 已知 source 資料：3 組重複 listing（如スーパーホテル今治 在同一 temple table
  出現兩次），detector 照樣各存一筆，不去重（plan §30）。

### Parse（plan Step 3：RawInn 抽取）

```bash
python3 -m henroyado parse   # → output/henroyado/raw.jsonl（572 筆）
```

- 每筆 = `tr.bl_table_row_frontInfo`（summary row）+ `tr.bl_table_row_detail`
  （detail card，含 h3 名稱 / description / route / お知らせ / 宿詳細 /
  料金 / お問い合わせ / マップ / carousel 圖片）。
- 純抽取、不標準化（RawInn，plan §19）。空字串一律轉 `null`（plan §3.4）。
- 只把 <br> 保留為換行、其餘空白收斂；付款等文字未清除標點周圍空白
  （那是 Step 4 normalizer 的工作）。
- 445 張有完整 detail card、127 張只有 front row（無 detail 內容）。
- 全頁僅 3 個 Google Maps iframe（其餘 JS lazy load），embed URL 少見；
  每張卡的「google mapを開く」連結（search URL）恆在。
- 109 張卡片的 部屋 值為空白 `<br/>` → `room: null`（source 本身無資料）。
- 圖片：只抽 `storage/inns/*` URL（去重、保留 query），**不**下載圖片。
- 522 張卡片有 room/meal/check-in 等文字資料，但 check_out 常缺（僅 203 張有）。

### Normalize（plan Step 4/5：RawInn → HenroyadoInnV1）

```bash
python3 -m henroyado normalize   # → output/henroyado/v1.jsonl（572 筆）
```

- 純函式 normalizer（`henroyado/normalize/`）：text/time/room/meal/route/
  facility/payment/map/image，各自獨立、失敗只記 warning 不丟 record。
- 結果符合 plan §5 schema：`henro.from/to_temple`（1番霊山寺→2番極楽寺）、
  `rooms.room_count`（`(\d+)部屋`，全形數字/冒號先正規化）、`meals`、
  `check_in/out`、`facilities`（icon→type 對應 + cross.png disabled）、
  `payment.methods/cards`（VISA/JCB/Mastercard/AE/UC 等）、
  `location.coordinates`（僅 2 筆有 embed iframe）、`images.url`（去 query）。
- **時間結構化**（`normalize/time.py`）：`check_in/out` 與 `meals.breakfast/dinner`
  各含 `time`（顯示）`start` `end`（`HH:MM`，range `15:00-19:00` 拆成
  start/end；開尾 `16:00-` → start + end null；`適宜/随時` → time null + notes；
  全形 `：`/數字與 4 位 `1500`→`15:00` 皆正常化；餐點 `06:30~` 同）。
  check_in 115 range / 200 single / 1 open / 256 none（含無資料）；breakfast 157 有時間。
- 原始值保留在 `raw.*` + 各欄 `raw_text`（plan §3.3）。
- 圖片只做 URL 處理，**全程不下載 image binary**（僅 fetcher 會連網）。
- `rooms.room_count`：單一 `N部屋` 直接取；多組間數（如 Hostel 東風ノ家
  `ﾄﾞﾐﾄﾘｰ2人 1部屋. ﾄﾞﾐﾄﾘｰ4人 2部屋. 個室 2部屋`）**加總**（1+2+2=5）。
- 目前 0 warnings。

### Tests（plan Step 8：regression fixtures）

```bash
python3 -m unittest discover henroyado/tests
```

- `tests/test_normalizers.py`：normalizer 純函式單元測試（time/room/meal/route/
  payment/facility/image/map/text，39 個 test）。
- `tests/test_pipeline.py`：HTML fixture → RawInn → V1 == 凍結的 expected JSON
  （6 個代表性 record：ootoriien / no_meal / no_detail / multi_room /
  fullwidth_times / price）。
- fixtures 從 `source/henroyado.html` 抽真實片段：改版後跑
  `henroyado/tests/extract_fixtures.py` + `generate_expected.py` 重新凍結。

**Phase 1 狀態**：Step 1–8 全完成（fetch / detect / parse / normalize /
warnings / writers / fixtures+tests），產出 `source/henroyado.html`、
`output/henroyado/{detect,raw,v1}.jsonl`。

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
- Docker（build-shikoku-trail.sh 用 `ohenro-elevation-visuals` image 內的 tippecanoe）

## Build Shikoku Trail（四國自然步道）

```bash
./scripts/build-shikoku-trail.sh   # -> output/shikoku-trail.pmtiles + shikoku-trail.geojson
```

- 來源：`source/shikoku_trail/` 四縣官方 KML（每 `<Placemark>` = 一段路線）。
  KML 的 name/description 已拆好、geometry 與同目錄 GPX 一致，故以 KML 為來源。
- 流程：KML → GeoJSON（`henro/scripts/extract_shikoku_trail.py`，每段一個 LineString
  feature）→ tippecanoe（Docker，`--no-line-simplification` 保留官方幾何）→ PMTiles。
- Layer `shikoku_trail`，zoom 0–14，attribution 寫入 metadata。
- 每個 feature 屬性讓 App 可「選段顯示」：
  - `route_id`：`SHIKOKU_TKS_01` 等官方編號；無編號者合成 `SHIKOKU_KCH_神峯のみち`
    （高知 4 條、愛媛 1 條共用前綴，需以名稱區分）。
  - `name`：中文名（`渦潮の見えるみち`）；接続/連絡コース為 null。
  - `pref`：tokushima / kagawa / ehime / kochi。
  - `kind`：main / connector（接続コース）/ link（連絡コース）。
  - `seg` / `seg_count`：同名多段路線的分段序號與總段數（如 TKS_13 有 4 段）。
- 驗證結果（2026-08-18）：158 段（125 條主路線 + 14 connector + 3 link）、38,878 點。

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
