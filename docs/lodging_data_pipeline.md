# Shikoku Henro Lodging Data Pipeline — 操作文件

本文件描述「四國遍路住宿 POI」資料管線的完整流程、資料格式與操作方式。
目的：讓 AI agent（或任何人）在更新或擴充住宿資料時，依此文件逐步執行。

設計原則依 `reference/lodging_data_plan.md`（計畫 §1–§30）。請先讀過該文件再操作。

---

## 1. 概覽

```text
source/shikoku-latest.osm.pbf (immutable, OSM raw)
        │
        ▼
henro/scripts/extract_lodging.py
        │
        ▼
output/lodging.geojson        ← normalized GeoJSON（中間 + QA 格式，含 raw_tags）
output/lodging-report.json    ← QA 統計 + duplicate candidates + warnings
```

核心原則：

- **`source/` 放原始資料**：OSM PBF 視為 immutable，不可手動修改。
- **`output/` 放所有產出**：normalized 中間檔、geojson、report。
- **GeoJSON = 可編輯／可審查的中間格式**；PMTiles = 渲染產物（尚未建置）；
  SQLite = 詳細應用資料（尚未建置）。
- **Pipeline 必須 deterministic**：同樣的 PBF 輸入，必須產生完全相同的輸出。
- 住宿抽取與 basemap build **完全獨立**，更新住宿不需重建 basemap。

## 2. 檔案位置

Scripts 內部用自身位置解析 repo 根目錄，從任何工作目錄執行都可以：

```text
ohenro-map-data/
├── source/
│   └── shikoku-latest.osm.pbf    # OSM 來源（immutable）
├── output/
│   ├── lodging.geojson           # normalized GeoJSON（含完整 raw_tags）
│   └── lodging-report.json       # QA report
└── henro/
    └── scripts/
        └── extract_lodging.py    # 唯一一支 script（抽取 + normalize + QA）
```

## 3. 環境依賴

- Python 3.10+
- `osmium`（pyosmium）— 讀 PBF
- `shapely` — point-on-surface（`representative_point()`）

```bash
python3 -m pip install osmium shapely
```

若重新安裝環境，務必確認這兩個套件存在，否則 script 會直接 import 失敗。

## 4. 執行方式

```bash
python3 henro/scripts/extract_lodging.py [PBF] [OUT_GEOJSON] [OUT_REPORT]
# 預設：
#   PBF         = source/shikoku-latest.osm.pbf
#   OUT_GEOJSON = output/lodging.geojson
#   OUT_REPORT  = output/lodging-report.json
```

執行會印出：

```text
pass 1: nodes / ways / relations ...
  found 480 nodes, 678 ways, 3 relations
pass 2: resolving N relation member ways ...
wrote 1161 features -> .../output/lodging.geojson
wrote report   -> .../output/lodging-report.json
  by_subtype: {...}
  by_osm_type: {'node': ..., 'way': ..., 'relation': ...}
  warnings: N, duplicate candidates: N
```

### 內部流程（兩階段讀 PBF）

1. **Pass 1**：`osmium.SimpleHandler` 讀全部 node / way / relation。
   - 只保留帶 `tourism` tag 且值在支援 subtype 清單內的物件。
   - 記錄 relation 需要的 member way id。
2. **Pass 2**：只重新解析這些 member way 的座標，供 relation 組 multipolygon。

## 5. 支援的 OSM 物件型別

| OSM 物件 | 代表點規則 | `point_method` |
|---|---|---|
| node | 直接用節點座標 | `node` |
| way（封閉 polygon） | shapely `representative_point()`（ST_PointOnSurface 等價） | `representative_point` |
| way（非封閉／太短） | 座標平均值（midpoint），並記錄 warning | `polyline_midpoint` |
| relation（`type=multipolygon`） | 組 multipolygon（含 inner hole 扣除、open ring 拼接）後 `representative_point()` | `representative_point` |
| relation（其他 type） | 不產出，記 warning | — |

支援的 `tourism` subtype（`SUBTYPES`）：

`hotel` `hostel` `guest_house` `motel` `camp_site` `apartment` `chalet`

不在此清單的 `tourism` 值一律忽略（不會進 extractor）。

## 6. `output/lodging.geojson` 資料格式

GeoJSON FeatureCollection，每筆 Feature：

```json
{
  "type": "Feature",
  "id": "lodging-osm-way-123456",
  "geometry": {
    "type": "Point",
    "coordinates": [134.123456, 33.987654]
  },
  "properties": {
    "id": "lodging-osm-way-123456",
    "type": "lodging",
    "subtype": "hostel",
    "name": "Example Guest House",
    "name_ja": "Example Guest House",
    "name_en": null,
    "address": {
      "prefecture": "徳島県",
      "city": "徳島市",
      "suburb": "…",
      "neighbourhood": "…",
      "street": "…",
      "housenumber": "…",
      "postcode": "770-0939",
      "full": "…"
    },
    "phone": "+81...",
    "website": "https://example.com",
    "email": null,
    "rooms": 6,
    "beds": 18,
    "stars": null,
    "internet_access": "wlan",
    "wifi": null,
    "washing_machine": true,
    "dryer": true,
    "wheelchair": "limited",
    "opening_hours": null,
    "check_date": null,
    "smoking": null,
    "pets": null,
    "breakfast": null,
    "restaurant": null,
    "air_conditioning": null,
    "reservation": null,
    "source": "osm",
    "osm_type": "way",
    "osm_id": 123456,
    "point_method": "representative_point",
    "osm_version": 1,
    "osm_timestamp": "2018-04-22 13:29:52+00:00",
    "raw_tags": {
      "tourism": "hostel",
      "name": "Example Guest House"
    }
  }
}
```

### 6.1 Canonical ID

`lodging-osm-{node|way|relation}-{osm_id}`

- **不可**用裸 OSM ID 當應用程式主鍵（避免三種型別碰撞）。
- Feature 的 `id` 與 `properties.id` 相同。
- 未來 PMTiles layer 與 SQLite row 必須共用同一個 canonical ID。

### 6.2 欄位語義

| 欄位 | 規則 |
|---|---|
| `name_ja` | `name:ja`，無則 fallback `name` |
| `name_en` | 只有 `name:en`（不 fallback） |
| `phone` / `website` / `email` | `contact:*` 優先，fallback 裸 tag（contact:phone → phone，餘類推） |
| `address` | 拆 `addr:prefecture / city / suburb / neighbourhood / street / housenumber / postcode / full`，只保留存在的 key；全無則 `null` |
| `rooms` / `beds` / `stars` | 轉 int；無法解析為 `null` |
| `internet_access` / `wifi` / `wheelchair` / `opening_hours` / `check_date` / `smoking` / `pets` / `breakfast` / `restaurant` / `air_conditioning` / `reservation` | nullable 字串，**不**強制轉 boolean |
| `washing_machine` / `dryer` | yes/no → `true`/`false`；其他值保留原字串（不摧毀未知狀態） |
| `osm_version` / `osm_timestamp` / `changeset` | 可選 metadata；`0`/空值被省略（此 PBF 的 changeset 為 0，通常不會出現） |
| `raw_tags` | **完整**原始 OSM tags（不含空值），務必保留 |

### 6.3 注意事項

- 座標順序是 **`[longitude, latitude]`**（GeoJSON 標準）。
- 這是 detailed 中間檔，**不是** PMTiles 的 layer 內容。PMTiles 只該放渲染欄位
  （`id / subtype / name / name_ja / name_en`），不要放 `raw_tags`、`phone`、
  `website`、`address` 等大欄位。

## 7. `output/lodging-report.json` 資料格式

```json
{
  "total": 1161,
  "by_subtype": { "hotel": 649, "guest_house": 204, "camp_site": 164, "motel": 63, "hostel": 51, "chalet": 24, "apartment": 6 },
  "by_osm_type": { "node": 480, "way": 678, "relation": 3 },
  "missing_name": 76,
  "missing_coordinate": 0,
  "missing_phone": 715,
  "missing_website": 849,
  "with_laundry_tags": 1,
  "with_internet_tags": 85,
  "unknown_subtypes": [],
  "duplicate_candidates": [
    { "a": "lodging-osm-node-…", "b": "lodging-osm-way-…", "signal": "same name + near coords (7m)" }
  ],
  "warnings": []
}
```

| 欄位 | 意義 |
|---|---|
| `total` / `by_subtype` / `by_osm_type` | 總數與分佈 |
| `missing_*` | 缺少 name / coordinate / phone / website 的數量（OSM 稀疏屬正常） |
| `with_laundry_tags` / `with_internet_tags` | 有洗衣（washing_machine/dryer）或網路（internet_access/wifi）標籤的數量 |
| `unknown_subtypes` | 未知 subtype 值清單（soft warning） |
| `duplicate_candidates` | 疑似重複配對，**不主動去重** |
| `warnings` | soft warning 明細字串陣列 |

### 7.1 Duplicate 訊號（計畫 §18）

- 同名 + 座標距離 < 100m
- 同 `phone`
- 同 `website`

OSM 常出現 node + building way 同時標記同一間住宿，這是**預期的**重複，extractor
保留兩者並回報，不自動合併。

## 8. Error Handling（計畫 §24）

- **Soft problems 不中斷 build**：缺 name、invalid phone/website、unknown subtype、
  non-polygon way、relation unclosed ring 等，全部進 `warnings` / QA 統計。
- **Hard failure 才中斷**：PBF 讀不到、geometry 不可用、輸出寫入失敗。

## 9. Web QA（map-preview）

`lodging.geojson` 已接進現有 Web Map Preview 作為暫時 QA layer：

- 位置：`map-preview/public/data/lodging.geojson`（symlink → `output/lodging.geojson`）
- 環境變數：`VITE_LODGING_URL=/data/lodging.geojson`（留空停用）
- layer：`lodging`（依 subtype 著色）+ `lodging-label`（z11+ 顯示名稱）
- debug panel 有 lodging 顯示/隱藏 toggle

執行 `npm run dev`（在 `map-preview/`），開啟 http://localhost:5173。
點擊 marker 可檢視完整 properties（含 `raw_tags`、`address`、`point_method`）。

QA 檢查重點：點位、subtype 分類、缺名、重複、point-on-surface 異常、地址格式、tag 完整度、涵蓋範圍。

## 10. 更新流程

```bash
# 1. 換新的 Shikoku PBF（放到 source/shikoku-latest.osm.pbf）
# 2. 重跑 extractor
python3 henro/scripts/extract_lodging.py
# 3. 檢查 output/lodging-report.json 的統計與 warnings
# 4. 在 map-preview 目視 QA
```

因住宿抽取與 basemap 獨立，更新住宿**不需**重建 basemap。

## 11. 驗證（Smoke Checks）

```bash
python3 -c "import json; d=json.load(open('output/lodging.geojson')); print(len(d['features']))"
python3 -c "import json; r=json.load(open('output/lodging-report.json')); print(r['total'], r['by_osm_type'])"
```

品質檢查範例（曾任 agent 使用）：

- 所有 way/relation 的 `point_method` 為 `representative_point`，且
  `representative_point()` 落在原 polygon／multipolygon 內。
- `by_osm_type` 的 node+way+relation 總和 = `total`。
- canonical ID 唯一；`osm_type`/`osm_id` 與 ID 一致。
- 所有 feature 都有 `raw_tags`，且 `raw_tags.tourism` 與 `subtype` 對應。

## 12. 已知事項與限制

- 此 PBF 的 `changeset` 欄位 pyosmium 讀到為 0，extractor 因此省略該欄位。
- `unknown_subtypes` 目前通常為空：extractor 只收 `SUBTYPES` 清單內的值，
  清單外的 `tourism` 直接忽略，不會進 report。
- relation 只支援 `type=multipolygon`；`type=site` 等群組 relation 會被記
  warning 並略過。
- 尚無自動 dedup、SQLite 匯出、PMTiles lodging layer（後續 Phase 3–6）。

## 13. 產出清單

```text
output/lodging.geojson       # 1,161 features（node 480 / way 678 / relation 3，2026-08-16）
output/lodging-report.json   # QA 統計 + duplicates + warnings
```
