# Shikoku Map Data Pipeline

四國遍路 App 的離線地圖資料管線。從同一份 OSM PBF 產生兩份獨立的 PMTiles：

```text
shikoku-latest.osm.pbf
        |
        +--> Protomaps Basemaps profile --> shikoku-basemap.pmtiles (通用底圖)
        |
        +--> Custom Henro profile        --> shikoku-henro.pmtiles  (遍路 overlay)
```

## 目錄結構

```text
ohenro-map-data/
├── source/                    原始資料（immutable）：OSM PBF、seichijunrei spots.json、henroyado.html 快照、GSI DEM ZIPs
├── basemaps/                  Protomaps Basemaps repo（外部 git clone，勿放入自訂檔案）
├── henro/                     自訂 Henro Planetiler 專案（schema 見 henro/schema.md）
│   └── scripts/               遍路寺廟資料管線（extract / normalize / generate）
├── henroyado/                 Henroyado 住宿爬蟲（Python package，Phase 1：fetcher→parse→normalize）
│   └── tests/                 regression fixtures + 單元測試
├── gsi-dem/                   GSI DEM 轉換工具（Rust，Phase 1 Inspector 完成）
├── output/                    所有產出：henroyado/{detect,raw,v1}.jsonl、temples.*、lodging.*、兩份 PMTiles
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

## GSI DEM（Phase 1 Inspector）

```bash
cargo run --manifest-path gsi-dem/Cargo.toml --release -- inspect source/GSI/DEM5/5A/FG-GML-513462-DEM5A-20251208.zip
cargo test --manifest-path gsi-dem/Cargo.toml
```

- 直接從 ZIP 讀 XML entry，不將 XML 解壓到磁碟；支援 nested ZIP。
- streaming XML parser（quick-xml），tupleList → SoA（elevation f32 + mask u8）。
- 關鍵資料結構發現（詳見 `gsi-dem/README.md`）：
  - DEM5 沿海 mesh 的 sample count **不固定**（partial coverage，非損壞）。
  - Grid row 0 = 北（north-up），與 envelope lowerCorner（SW）不同。
  - DEM10B 用 `その他,-9999.00` sentinel，無 sea 語義；DEM5 用 `海水面`/`内水面`。
  - `内水面`（內陸水）帶真實高程，非 sentinel。
- Phase 2（raster correctness）完成前**不要開始 bulk build**（規劃 §42）。

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

## 環境需求

- Java 21+
- Maven 3.8+
- git
- PMTiles CLI（`go install github.com/protomaps/go-pmtiles@latest`，binary 為 `go-pmtiles`）

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
./scripts/inspect-pmtiles.sh   # 顯示 basemap 與 henro metadata
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
