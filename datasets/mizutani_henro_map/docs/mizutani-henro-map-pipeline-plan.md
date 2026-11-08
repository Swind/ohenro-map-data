# 水谷遍路導覽圖 KML → PMTiles 實作計畫

> **實作狀態（2026-08-22）**：Milestone 1-6 已完成。操作方式見
> `datasets/mizutani_henro_map/docs/mizutani_henro_map_pipeline.md`；本文件保留為設計、資料來源與發布 gate。

## 1. 目的

將水谷卓也先生維護的 Google My Maps：

- 原始名稱：`お遍路のルート・おすすめ宿・お店・道しるべ・経験談`
- 顯示名稱：`水谷遍路導覽圖`
- 英文名稱：`Mizutani Henro Guide Map`
- Map ID：`1FYOrTzLZCmGi4wGFf5bNhIe3K18`
- 地圖網址：<https://www.google.com/maps/d/u/0/viewer?mid=1FYOrTzLZCmGi4wGFf5bNhIe3K18>
- 作者說明：<https://min88.jp/photo/558/>

轉換成可在 App 離線使用、可獨立更新的 PMTiles overlay：

```text
Google My Maps KML
        |
        +--> immutable raw snapshot + metadata
        |
        +--> KML parser + style inventory
        |
        +--> manual icon classification
        |
        +--> normalized JSON + GeoJSON + report
        |
        +--> tippecanoe MBTiles
        |
        +--> datasets/mizutani_henro_map/output/shikoku-mizutani-henro.pmtiles
```

這份資料不併入 `shikoku-henro.pmtiles`、住宿 PMTiles 或自然步道 PMTiles。作者更新頻繁，獨立檔案可讓 App 單獨下載、替換、回復上一版，也能維持清楚的來源與授權界線。

## 2. 範圍

### 2.1 本計畫要做

1. 自動下載公開 Google My Maps KML。
2. 以 SHA-256 保存不可變的原始快照，內容未變時不重建。
3. 保存下載時間、來源 URL、HTTP metadata、Map ID 與 checksum。
4. 解析 Folder、Placemark、StyleMap、Style、Point 與 LineString。
5. 產生 style/icon 使用盤點，供人工建立簡單分類。
6. 保留原始名稱、說明、folder、style 與 geometry，不用文字猜測分類。
7. 產生 routes 與 POIs GeoJSON。
8. 建立並嚴格驗證獨立 PMTiles。
9. 提供單一更新命令，只有來源內容改變才重新 build。
10. 產生更新差異報告，避免來源改版或新 icon 靜默造成資料遺失。

### 2.2 本計畫暫時不做

1. 不與 OSM route、寺廟或住宿資料自動合併、去重。
2. 不依名稱、描述或 AI 猜測 POI 類型。
3. 不修正作者路線或座標。
4. 不下載 POI 描述內的外部圖片。
5. 不重新散布 Google 的 icon 圖檔；App 使用自己的 category icon。
6. 不建立公開下載服務或把原始 KML、衍生 PMTiles commit 進 repository。
7. 未取得明確再散布許可前，不把成品隨公開 App 發布。

## 3. 授權與使用界線

作者頁面明確寫有：

> 他の方への共有はご自由に

作者另於留言表示：

> この地図、共有フリーという形にしてますのでよろしければシェアください

這清楚表達作者歡迎分享地圖連結與一般使用，但沒有明確指定 Creative Commons 等授權，也沒有明確寫出可複製、改作、離線封裝及再散布。`min88.jp` 利用規約第 8 條也說明投稿內容權利仍屬投稿者，超出私用範圍時需要權利人許可。

本階段定位為個人遍路使用：

- 可以在本機下載、分析及轉換供自己使用。
- raw archive、normalized output 與 PMTiles 保持 gitignored。
- 所有輸出仍保留作者與原始來源 attribution。
- 若未來要隨 App 或網站公開散布，先取得水谷卓也先生對「KML 轉換、離線 PMTiles、衍生分類及再散布」的書面許可。
- 取得許可後，將許可日期、適用範圍、署名要求及證據位置加入 metadata 與本文件，不自行推定授權條款。

此段是工程上的發布 gate，不是法律意見。

## 4. 實際來源盤點

2026-08-22 實測 KML endpoint：

```text
https://www.google.com/maps/d/kml?mid=1FYOrTzLZCmGi4wGFf5bNhIe3K18&forcekml=1
```

HTTP 回應為 `200`、`text/xml; charset=utf-8`，約 2.8 MB。當時資料結構如下：

| 項目 | 數量 |
|---|---:|
| Folder | 6 |
| Placemark | 2,807 |
| Point | 2,680 |
| LineString | 127 |
| Polygon | 0 |
| Style | 256 |
| StyleMap | 128 |
| Placemark 使用的 styleUrl | 128 |
| Point 使用的 styleUrl | 124 |
| Point 使用的 icon 編號 | 79 |

Folder 與 geometry 分布：

| Folder | Point | LineString |
|---|---:|---:|
| `sub route` | 0 | 45 |
| `20route` | 0 | 10 |
| `88route` | 0 | 72 |
| `88+20` | 107 | 0 |
| `∵∵` | 1,999 | 0 |
| `∵` | 574 | 0 |

這些名稱是來源資料，不先猜測 `∵` 與 `∵∵` 的語意。

### 4.1 Icon 分類的重要限制

KML 中所有 Point Style 的 `<Icon><href>` 目前都指向：

```text
https://www.gstatic.com/mapspro/images/stock/503-wht-blank_maps.png
```

因此不能只靠 icon URL 分類。有效辨識資訊主要在：

- Placemark 的 `styleUrl`，例如 `#icon-1602-C2185B`
- icon 編號，例如 `1602`
- 顏色，例如 `C2185B`
- StyleMap 的 normal/highlight 對應
- Folder 名稱
- 用來人工判讀的代表性 Point 名稱與描述

分類器以 `styleUrl` 中的 icon 編號為主要分類 key；同一 icon 的不同顏色預設屬於同一 category。完整 `styleUrl` 可做例外覆寫，且永遠保存在輸出中。顏色與 folder 也保留為報告欄位，但不從共同的 icon URL 推斷類別。

## 5. 建議目錄結構

```text
ohenro-map-data/
├── source/
│   └── mizutani-henro-map/             # gitignored raw archive
│       ├── current.json                 # 目前採用的 snapshot SHA
│       └── snapshots/
│           └── <sha256>/
│               ├── map.kml
│               └── metadata.json
├── datasets/mizutani_henro_map/                  # Python package
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py
│   ├── config.py
│   ├── fetch.py
│   ├── parser.py
│   ├── normalize.py
│   ├── export_map.py
│   ├── verify.py
│   ├── style_categories.json            # tracked manual classification
│   └── tests/
├── output/
│   ├── mizutani-henro-map.json
│   ├── mizutani-henro-routes.geojson
│   ├── mizutani-henro-pois.geojson
│   ├── mizutani-henro-report.json
│   └── shikoku-mizutani-henro.pmtiles
├── work/
│   └── mizutani-henro-map/
│       └── mizutani-henro.mbtiles
├── reports/
│   ├── mizutani-henro-build.log
│   └── mizutani-henro-metadata.txt
└── scripts/
    └── build-mizutani-henro.sh
```

`datasets/mizutani_henro_map/raw/` 與中間/輸出資料應加入 `.gitignore`。`style_categories.json`、程式、tests 與本計畫則進版控。

## 6. CLI 設計

```bash
# 下載；內容相同時只報 no change
python3 -m datasets.mizutani_henro_map fetch

# 顯示 geometry、folder、style/icon 使用量及代表性 Point
python3 -m datasets.mizutani_henro_map inspect

# KML -> deterministic normalized JSON
python3 -m datasets.mizutani_henro_map normalize

# normalized JSON -> routes/POIs GeoJSON + accounting report
python3 -m datasets.mizutani_henro_map export-map

# 驗證 raw、normalized 與 GeoJSON accounting
python3 -m datasets.mizutani_henro_map verify

# 完整下載、驗證並建立 overlay 與 provider pack
python3 -m datasets.mizutani_henro_map

# 只從 local current 重建／驗證已發布資料
python3 -m datasets.mizutani_henro_map build
python3 -m datasets.mizutani_henro_map validate
```

目前 CLI 與所有輸出契約以 [Pipeline 操作文件](mizutani_henro_map_pipeline.md) 為準：

- `--raw-dir`（保留 `--data-dir` 別名）、`--output-dir`、`--reports-dir`：替代資料路徑。
- `--force`：run/build 不跳過完整重建；run 預設每次下載來源。
- `--local`：run 使用已驗證的 current；低階 inspect/normalize/verify 可用 `--snapshot <sha256>`。

不先加入 concurrency、複雜 config framework 或資料庫。

## 7. Phase 1：下載與 immutable archive

### 7.1 Fetch 行為

1. 使用既有 stdlib `urllib` HTTP 模式，設定固定 User-Agent、30 秒 timeout、有限次 retry。
2. GET KML endpoint，不相信 Content-Type，驗證 HTTP 200、body 非空且包含 `<kml`。
3. 完整 XML parse 成功後才視為有效。
4. 計算 SHA-256。
5. 若 SHA 已存在，只更新 `current.json` 的檢查資訊，不複製第二份 KML。
6. 若 SHA 是新的，以 atomic write 建立 `snapshots/<sha>/map.kml` 與 metadata。
7. 下載失敗或回傳 HTML 時保存 `.failed` 到暫存/debug 位置，不覆蓋目前有效 snapshot。

### 7.2 Snapshot metadata

```json
{
  "schema_version": 1,
  "dataset_id": "mizutani-henro-map",
  "map_id": "1FYOrTzLZCmGi4wGFf5bNhIe3K18",
  "title": "お遍路のルート・おすすめ宿・お店・道しるべ・経験談",
  "author": "水谷卓也",
  "source_map_url": "https://www.google.com/maps/d/u/0/viewer?mid=1FYOrTzLZCmGi4wGFf5bNhIe3K18",
  "source_article_url": "https://min88.jp/photo/558/",
  "kml_url": "https://www.google.com/maps/d/kml?mid=1FYOrTzLZCmGi4wGFf5bNhIe3K18&forcekml=1",
  "retrieved_at": "RFC3339 timestamp",
  "http_status": 200,
  "content_type": "text/xml; charset=utf-8",
  "size": 2792067,
  "sha256": "..."
}
```

`current.json` 至少記錄目前 SHA 與最後檢查時間。真正的 source identity 是 SHA，不用 `retrieved_at` 判斷是否更新。

## 8. Phase 2：KML parser 與資料保真

使用 Python 標準庫 `xml.etree.ElementTree`，避免新增 dependency。Parser 應處理：

1. KML namespace，不依固定 prefix。
2. Document 與 Folder 階層，輸出完整 `folder_path`。
3. StyleMap 的 `normal` 與 `highlight` pair。
4. Style 的 IconStyle、LineStyle、PolyStyle。
5. Placemark 的 `name`、`description`、`styleUrl`、geometry。
6. Point、LineString，以及可能出現的 MultiGeometry。
7. 座標格式 `lon,lat[,alt]`、finite number 與合法經緯度範圍。
8. KML 顏色 `aabbggrr` 轉成 App 易用的 `#RRGGBB`，同時保留 raw value。

描述可能含 HTML。normalized data 保存：

- `description_html`：原始內容，僅供 archive/診斷，不直接在 App WebView 執行。
- `description`：HTML entity decode、`<br>` 轉換、其餘 tag 移除後的純文字。
- `links`：從允許的 `http`/`https` anchor 提取；App 開啟前仍需做 URL 安全檢查。

若更新後出現 Polygon、NetworkLink、Track 或目前不支援的 geometry，`inspect` 要列出，正式 build 預設失敗，不能靜默丟棄。

## 9. Phase 3：Style/Icon 盤點與人工分類

### 9.1 Inventory

`inspect` 產生 `datasets/mizutani_henro_map/output/mizutani-henro-style-inventory.json`，每個被使用的 style 包含：

```json
{
  "style_url": "#icon-1602-C2185B",
  "icon_id": "1602",
  "color": "#C2185B",
  "geometry_type": "Point",
  "count": 379,
  "folders": {"∵∵": 306, "∵": 73},
  "examples": [
    {"name": "...", "description": "..."}
  ],
  "classification": "unclassified"
}
```

代表樣本固定依 source order 取前 5 筆，確保報告 deterministic。報告另外列出：

- 新出現但未分類的 style。
- mapping 中已不存在的 style。
- 同一 style 跨 folder 的使用量。
- style 的 geometry type 發生改變。
- 相較上一 snapshot 的 Point、LineString、style 數量差異。

### 9.2 分類表

`datasets/mizutani_henro_map/style_categories.json` 由人工閱讀範例及對照 My Maps 畫面後維護。通常只需分類 79 個 icon 編號；只有同一 icon 在特定顏色確實代表不同用途時才加入 style override：

```json
{
  "schema_version": 1,
  "icons": {
    "1602": {
      "category": "lodging",
      "icon": "lodging",
      "note": "人工確認依據"
    }
  },
  "style_overrides": {
    "#icon-1602-C2185B": {
      "category": "lodging",
      "icon": "lodging",
      "note": "只有語意不同時才覆寫"
    }
  }
}
```

解析優先順序為 `style_overrides[style_url]`、`icons[icon_id]`、最後 `unclassified`。這兼顧維護成本與來源保真。

第一版 category vocabulary：

| category | 用途 |
|---|---|
| `temple` | 札所、別格及寺院 |
| `lodging` | 宿泊、善根宿、野宿相關點 |
| `food` | 餐飲、補給食物 |
| `shop_supply` | 商店、用品、補給地點 |
| `transport` | 車站、巴士、渡船等交通 |
| `wayfinding` | 道標、轉彎、路線提示 |
| `warning_hazard` | 危險、通行注意、容易迷路 |
| `water_toilet_rest` | 飲水、廁所、休息點 |
| `experience_note` | 作者經驗或一般說明 |
| `other` | 已人工確認但不屬以上類型 |
| `unclassified` | 尚未人工確認 |

category 保持粗粒度；原始 icon/style 仍完整保留，因此以後可以細分而不用重抓 KML。顏色可能代表群組或狀態，不在沒有證據時解讀。

### 9.3 未分類政策

- 未分類 Point 不丟棄，寫入 PMTiles 並標記 `category=unclassified`。
- `verify` 顯示未分類 style/feature 數量。
- 初次導入可以允許未分類；分類表完成後，正式個人使用 build 設定目標為 0 個未知 style。
- 後續更新若出現新 style，build 可完成但必須在 log/report 明顯警告。若 App 無法顯示 `unclassified` fallback icon，build 必須失敗。

## 10. Phase 4：Normalized schema

輸出 `datasets/mizutani_henro_map/output/mizutani-henro-map.json`，固定排序、UTF-8、無 build timestamp，使相同 snapshot 與 mapping 產生相同內容。

頂層：

```json
{
  "schema_version": 1,
  "dataset_id": "mizutani-henro-map",
  "source": {
    "snapshot_sha256": "...",
    "map_id": "...",
    "title": "...",
    "author": "水谷卓也",
    "map_url": "...",
    "article_url": "..."
  },
  "styles": [],
  "features": [],
  "summary": {}
}
```

每個 feature 至少包含：

```json
{
  "feature_id": "MHM_P_ab12cd34ef56",
  "source_order": 1,
  "geometry_type": "Point",
  "name": "...",
  "description": "...",
  "description_html": "...",
  "links": [],
  "folder_path": ["∵∵"],
  "style_url": "#icon-1602-C2185B",
  "icon_id": "1602",
  "color": "#C2185B",
  "category": "unclassified",
  "app_icon": "other",
  "geometry": {}
}
```

### 10.1 Stable ID

Google KML 沒有提供可依賴的 Placemark ID。為避免作者調整順序造成所有 ID 改變：

1. canonicalize `geometry + folder_path + style_url`。
2. 計算 SHA-256，使用前 12 個 hex。
3. Point 為 `MHM_P_<hash>`，LineString 為 `MHM_L_<hash>`。
4. 完全相同內容重複出現時，依 source order 加 `_02`、`_03`。

名稱或描述修改但位置/style 不變時 ID 保持；geometry 或 style 改變時視為新的 feature。完整 canonical hash 也保存在 normalized data，碰撞時不能靜默覆蓋。

## 11. Phase 5：GeoJSON export

產生兩份 GeoJSON：

### 11.1 Routes

`datasets/mizutani_henro_map/output/mizutani-henro-routes.geojson`

PMTiles layer：`mizutani_henro_routes`

Properties：

- `feature_id`
- `name`
- `folder`
- `route_kind`
- `style_url`
- `color`
- `width`
- `description`
- `source`

初始 `route_kind` 只依來源 folder 做明確映射：

| Folder | route_kind |
|---|---|
| `88route` | `source_88route` |
| `20route` | `source_20route` |
| `sub route` | `alternate` |

未知 folder 使用 `other` 並在 report 列出，不因名稱相似自動歸類。

### 11.2 POIs

`datasets/mizutani_henro_map/output/mizutani-henro-pois.geojson`

PMTiles layer：`mizutani_henro_pois`

Properties：

- `feature_id`
- `name`
- `description`
- `url`（若只有一個主要連結）
- `folder`
- `category`
- `icon`
- `style_url`
- `icon_id`
- `color`
- `source`

GeoJSON 不攜帶 `description_html`，避免 tile 膨脹與 App 誤當可信 HTML。完整原文仍存在 raw/normalized archive。

目前來源沒有 Polygon，因此第一版不建立空的 areas layer。若未來實際出現 Polygon，再增加 `mizutani_henro_areas`，而不是先維護未使用的 schema。

## 12. Phase 6：PMTiles build

`datasets/mizutani_henro_map/scripts/build-mizutani-henro.sh` 只轉交 Python `build`；`--update` 轉交 `run`。唯一建置實作位於 `pipeline.py`：

1. run 下載遠端來源；build 選取 current，驗證 immutable source hashes 與完整 geometry/styles。
2. 只有來源、程式、設定、所有成品 size/hash 全部吻合才略過。
3. 在 stage 執行 normalize、export-map、diff、verify。
4. 使用共用 helper 建立 overlay 及只有 `routes` layer 的 provider pack。
5. 寫入 attribution/source metadata，驗證 layers、bounds、實際 tile 中的 consumer IDs 與分類。
6. 全部成功後才逐檔 atomic replace 全部成品，最後寫入 `reports/pipeline.json`。

建議 tippecanoe 命令：

```bash
tippecanoe --quiet --force \
  --output work/mizutani-henro-map/mizutani-henro.mbtiles \
  --minimum-zoom 0 --maximum-zoom 14 \
  --drop-densest-as-needed \
  --no-line-simplification \
  -L mizutani_henro_routes:datasets/mizutani_henro_map/output/mizutani-henro-routes.geojson \
  -L mizutani_henro_pois:datasets/mizutani_henro_map/output/mizutani-henro-pois.geojson
```

POI GeoJSON 可使用 tippecanoe feature property 設定 `minzoom=10`，避免低 zoom 載入數千個 Point。路線保持 z0-14，先延續自然步道 build 對路線不簡化的策略；若實測 tile 過大，再以 report 驗證後調整，不預先破壞 geometry。

### 12.1 PMTiles metadata

至少寫入：

```json
{
  "name": "Mizutani Henro Guide Map",
  "description": "Offline derivative for personal use of お遍路のルート・おすすめ宿・お店・道しるべ・経験談",
  "attribution": "水谷遍路導覽圖 / Original map by 水谷卓也; source: https://min88.jp/photo/558/",
  "dataset_id": "mizutani-henro-map",
  "source_map_id": "1FYOrTzLZCmGi4wGFf5bNhIe3K18",
  "source_sha256": "...",
  "source_url": "https://www.google.com/maps/d/u/0/viewer?mid=1FYOrTzLZCmGi4wGFf5bNhIe3K18",
  "usage": "personal-use"
}
```

## 13. Phase 7：驗證與 regression tests

### 13.1 Raw validation

- KML 可 parse。
- Document 存在。
- 至少有一個 Placemark。
- 所有 Placemark 都有受支援 geometry；沒有 geometry 的紀錄需明確列出。
- 每個 styleUrl 可 resolve 到 Style/StyleMap；無法 resolve 時列出 warning/error。
- 經緯度 finite 且位於合法世界範圍。

### 13.2 Dataset accounting

必須成立：

```text
raw Point count      == normalized Point count == POI GeoJSON feature count
raw LineString count == normalized line count  == routes GeoJSON feature count
classified + unclassified == total Point count
每個輸出 feature_id 唯一
每個 raw Placemark 恰好被 accounted 一次
```

若 MultiGeometry 被拆成多個 feature，report 必須另外記錄 placemark count 與 geometry part count，不能用錯誤的一對一公式。

### 13.3 PMTiles validation

- 檔案存在且非空。
- vector layers 恰含 `mizutani_henro_routes` 與 `mizutani_henro_pois`。
- bounds 位於四國合理範圍：`131 < west < east < 136`、`31.5 < south < north < 35.5`。
- zoom 為預期範圍。
- metadata 含 author、source URL、Map ID、source SHA、personal-use。
- 抽查至少一個 route 與每個已分類 category 的 POI 可由 tile 讀回必要欄位。

完成後把這個 optional artifact 加入 `scripts/validate.sh`；不存在時 warning，存在時嚴格驗證。

### 13.4 最小測試集

使用 `unittest` 與小型手寫 fixture：

1. StyleMap normal/highlight resolution。
2. icon ID/color extraction。
3. Folder path preservation。
4. Point 與 LineString parsing。
5. HTML description 純文字與 link extraction。
6. unknown style → `unclassified`，feature 不遺失。
7. stable ID 不受 placemark order 影響。
8. malformed XML、非法座標、unsupported geometry 失敗。
9. fixture KML → expected normalized JSON regression。

執行方式：

```bash
python3 -m unittest discover datasets/mizutani_henro_map/tests
```

## 14. Phase 8：頻繁更新流程

日常更新只需：

```bash
./datasets/mizutani_henro_map/scripts/build-mizutani-henro.sh --update
```

行為：

1. fetch KML、驗證完整 routes/POIs、styles、geometry，保存 immutable snapshot 後才選為 current。
2. SHA、程式、build config 與全部輸出 hashes 都未變時才跳過；任何缺檔或損毀都重建。
3. 比較已發布的新舊 snapshot，產生 update report；首次建置比較自身。
4. 在 stage normalize、export、verify，建立 overlay 與 provider pack。
5. 全部驗證成功後才逐檔 atomic replace 全部輸出，最後寫 pipeline report。
6. 不完整來源保留 current 與既有成品；建置失敗保留既有成品。非阻塞 source-local lock 避免併行更新。

Update report 至少包含：

- old/new SHA 與下載時間。
- Point、LineString、Folder、style count 差異。
- 新增/移除的 styleUrl。
- 新增/移除/改變的 stable feature ID。
- category 分布差異。
- 新增的 unclassified style 與代表樣本。
- bounds 是否顯著改變。

更新流程不以 Google My Maps 頁面的 views 或文章日期判斷版本，只相信下載 KML 的內容 SHA。

## 15. App 整合契約

App 將此檔視為可選、可獨立更新的 overlay：

- 顯示名稱：`水谷遍路導覽圖`
- 檔名：`shikoku-mizutani-henro.pmtiles`
- routes layer：`mizutani_henro_routes`
- POIs layer：`mizutani_henro_pois`
- 預設可獨立開關 route 與 POI。
- POI 依 `category` 篩選，依 `icon` 選 App 內建圖示。
- `unclassified` 永遠有 fallback icon。
- detail panel 顯示名稱、純文字描述、來源連結與作者署名。
- 不直接渲染來源 HTML。
- App 可用 `source_sha256` 判斷本機資料版本。

PMTiles 與 App release 解耦後，未來可以只下載新的 overlay，不重發 basemap、henro routes 或整個 App。

## 16. 錯誤處理原則

1. 網路錯誤不破壞已存在 snapshot。
2. 無效 KML 不更新 `current.json`。
3. Parser 不認識的新結構不靜默略過。
4. 未分類 style 保留資料並警告，不丟 Point。
5. build 到暫存檔，驗證通過後才替換正式 PMTiles。
6. 所有 command 失敗回傳非 0 exit code。
7. report 與 log 必須指出 source SHA，方便重現問題。

## 17. 實作順序

### Milestone 1：Raw archive

- 建立 package、config、fetch command。
- 實作 KML validation、SHA snapshots、atomic current pointer。
- 驗收：相同來源重跑不產生重複 snapshot，失敗不破壞 current。

### Milestone 2：Parser 與 inventory

- 實作 Folder/StyleMap/Style/Point/LineString parser。
- 產生 style inventory 與 current snapshot summary。
- 加入 fixture tests。
- 驗收：當前來源 2,680 Point、127 LineString 全部 accounted。

### Milestone 3：人工 icon 分類

- 依 inventory 與 My Maps 畫面逐一確認 style。
- 建立 tracked `style_categories.json`。
- App icon vocabulary 維持粗粒度。
- 驗收：每個 style 有已確認分類或明確 `unclassified` 狀態，沒有猜測規則。

### Milestone 4：Normalize 與 GeoJSON

- 實作 deterministic schema、stable IDs、routes/POIs export。
- 產生 accounting/update report。
- 驗收：raw → normalized → GeoJSON 數量一致。

### Milestone 5：PMTiles build

- 建立 build script、tippecanoe、PMTiles metadata 與嚴格 validation。
- 加入 `scripts/validate.sh` optional check。
- 驗收：App 可離線顯示 route、POI、分類 icon 與 detail text。

### Milestone 6：Incremental update

- `--update` 串接 fetch、diff、build、atomic replace。
- 保存新舊 snapshot 差異報告。
- 驗收：無變更不重建；來源或新 style 改版不會靜默遺失資料。

## 18. 完成條件

第一版完成需同時符合：

1. 一個命令可從公開 KML 建立獨立 PMTiles。
2. KML 未變時不重建。
3. 原始 snapshot 有 SHA、來源及下載 metadata。
4. 目前 2,807 個 Placemark 全部 accounted，沒有靜默遺失。
5. routes 與 POIs 使用獨立 layers。
6. 每個 Point 保留原始 style，且有 category 或 `unclassified` fallback。
7. 新 style 會出現在 update report。
8. PMTiles 含作者、來源、Map ID、source SHA 與 personal-use metadata。
9. build 失敗不覆蓋上一份可用 PMTiles。
10. parser/unit regression tests 與 PMTiles validation 全部通過。

## 19. 後續公開發布前檢查

個人使用轉為公開散布前，另外完成：

1. 取得作者對轉換、分類、離線封裝及再散布的明確許可。
2. 確認是否允許商業 App、免費 App 或僅非商業使用。
3. 確認署名文字、原始連結及撤回/更新方式。
4. 檢查描述中的第三方圖片、文章與連結不被打包或誤認為已授權。
5. 將 `usage=personal-use` 改成經確認的正式授權標記。
6. 在 App 資料來源頁顯示作者、資料日期、免責聲明及原始地圖連結。
