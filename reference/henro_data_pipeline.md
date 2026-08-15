# Shikoku Henro Temple Data Pipeline — 操作文件

本文件描述「聖地巡礼 四国遍路」寺廟資料的完整轉換流程、資料格式與操作方式。
目的：讓 AI agent（或任何人）在需要更新資料時，依此文件逐步執行。

架構設計依 `reference/henro_data_plan.md`。請先讀過該文件再操作。

---

## 1. 概覽

```text
seichijunrei-shikokuhenro.jp HTML
        │
        ▼
[1] Extract   extract_henro.py      → source/seichijunrei/spots.json
        │
        ▼
[2] Normalize normalize_henro.py    → output/temples.json
        │
        ▼
[3] Generate  generate_geojson.py   → output/temples.geojson
        │
        ▼
[4] (未來) Planetiler → output/*.pmtiles
```

原則：

- **`source/` 放原始資料**：所有從外部下載／抓取的資料都放這裡（OSM PBF、seichijunrei
  spots.json），視為 immutable，不可手動修改。
- **`output/` 放所有產出**：normalized 中間檔、geojson、pmtiles 全部輸出到這裡。
- **Pipeline 必須 deterministic**：同樣的 source 輸入，必須產生完全相同的 output。
- 不要直接使用來源網站 schema（`Spot` / `SpotContent`）作為應用程式領域模型。

## 2. 檔案位置

Scripts 位於 `henro/scripts/`，內部用自身位置解析 repo 根目錄，所以**從任何工作目錄
執行都可以**，不需先 `cd`：

```text
ohenro-map-data/
├── source/
│   ├── shikoku-latest.osm.pbf        # OSM 來源（immutable）
│   └── seichijunrei/spots.json       # 寺廟原始資料（immutable）
├── output/
│   ├── temples.json                  # normalized 中間產出
│   ├── temples.geojson               # 地圖用 GeoJSON
│   ├── shikoku-basemap.pmtiles       # basemap
│   └── shikoku-henro.pmtiles         # henro overlay
└── henro/
    └── scripts/
        ├── extract_henro.py          # Step 1
        ├── normalize_henro.py        # Step 2
        └── generate_geojson.py       # Step 3
```

## 3. 操作方式（更新流程）

要更新資料時，依序執行：

```bash
# Step 1: 從網站抓取原始資料
python3 henro/scripts/extract_henro.py

# Step 2: 正規化
python3 henro/scripts/normalize_henro.py

# Step 3: 產生 GeoJSON
python3 henro/scripts/generate_geojson.py
```

預設抓取來源為 `https://www.seichijunrei-shikokuhenro.jp/map/all`
（該頁含全部 88 寺，不需逐頁抓取）。

`extract_henro.py` 亦接受參數：

```bash
python3 henro/scripts/extract_henro.py [URL] [輸出檔]
# 例如：
python3 henro/scripts/extract_henro.py "https://www.seichijunrei-shikokuhenro.jp/map/all/107" /tmp/spot107.json
```

### 3.1 手動驗證

```bash
python3 -c "import json; d=json.load(open('output/temples.geojson')); print(len(d['features']), 'features')"
```

預期：`88 features`。

## 4. 資料格式

### 4.1 Raw — `source/seichijunrei/spots.json`

來源網站 `<script>` 內 `var spots = [...]` 的 JSON，**原封不動**存下。是 JSON array，
每筆長這樣（僅列重要欄位）：

```json
[
  {
    "Spot": {
      "id": "8",
      "spot_category_id": "3",
      "name_ja": "霊山寺",
      "name_en": "Ryouzen-ji",
      "post_code": "779-0230",
      "pref": "徳島県",
      "address_ja": "鳴門市大麻町板東塚鼻126",
      "address_en": "126, Tsukahana, Oasacho bando, Naruto-shi",
      "latitude": "34.159474",
      "longitude": "134.502972",
      "eyecatch": "/uploads/2016/02/04/201602040212279e75cjd0u6.jpg",
      "number": "1"
    },
    "SpotCategory": { "id": "3", "name_ja": "札所情報" },
    "SpotContent": {
      "id": "3",
      "spot_id": "8",
      "short_name_ja": "霊山寺",
      "short_name_en": "Ryouzen-ji",
      "short_name_kana_ja": "りょうぜんじ",
      "long_name_ja": "第一番　竺和山　霊山寺",
      "long_name_en": "No.1 Jikuwazan Ryouzen-ji",
      "long_name_kana_ja": "じくわざん　りょうぜんじ",
      "rekishiyurai_ja": "…",
      "rekishiyurai_en": "",
      "honzon_ja": "釈迦如来",
      "syuha_ja": "高野山真言宗",
      "kaiki_ja": "行基菩薩",
      "souken_ja": "天平年間（729～749）",
      "tel_ja": "088-689-1111",
      "syukubou_ja": "休止中"
    }
  }
]
```

特點（raw 階段不處理，保留原狀）：

- 數值欄位是字串：`"number": "1"`、`"latitude": "34.159474"`。
- 有些欄位含前後空白（例：`"Shingon sect "`）。
- 空字串 `""` 代表「沒有值」。
- `syukubou_ja` 的值有：`なし`、`あり`、`休止中`、`あり（…）` 等。

### 4.2 Normalized — `output/temples.json`

Canonical domain model，依計畫 §4。JSON array，每筆：

```json
{
  "id": "temple-001",
  "number": 1,
  "name": {
    "ja": "霊山寺",
    "en": "Ryouzen-ji",
    "kana": "りょうぜんじ"
  },
  "full_name": {
    "ja": "第一番　竺和山　霊山寺",
    "en": "No.1 Jikuwazan Ryouzen-ji",
    "kana": "じくわざん　りょうぜんじ"
  },
  "location": {
    "latitude": 34.159474,
    "longitude": 134.502972,
    "source": "seichijunrei"
  },
  "address": {
    "postal_code": "779-0230",
    "prefecture": "徳島県",
    "ja": "鳴門市大麻町板東塚鼻126",
    "en": "126, Tsukahana, Oasacho bando, Naruto-shi"
  },
  "phone": "088-689-1111",
  "temple": {
    "principal_deity": { "ja": "釈迦如来", "en": null },
    "sect": { "ja": "高野山真言宗", "en": null },
    "founder": { "ja": "行基菩薩", "en": null },
    "founded": { "ja": "天平年間（729～749）", "en": null },
    "has_lodging": false
  },
  "history": { "ja": "…", "en": null },
  "image": { "eyecatch": "/uploads/2016/02/04/201602040212279e75cjd0u6.jpg" },
  "sources": {
    "seichijunrei": {
      "spot_id": "8",
      "content_id": "3",
      "modified_at": "2016-06-06 11:50:28"
    }
  }
}
```

正規化規則（依計畫 §13）：

| Raw | Normalized |
| --- | --- |
| `"number": "1"` | `"number": 1`（int） |
| `"latitude": "34.159474"` | `34.159474`（float） |
| 前後空白 `"Shingon sect "` | strip 後 `"Shingon sect"` |
| 空字串 `""` | `null` |
| `syukubou_ja` 以 `あり` 開頭 | `has_lodging: true` |
| `syukubou_ja` 為 `なし` / `休止中` / 空 | `has_lodging: false` |
| `Spot.id`, `SpotContent.id`, `modified` | 保留在 `sources.seichijunrei` |

Canonical ID：`temple-` + 三位數編號（`temple-001` ～ `temple-088`），由 `number` 產生。
**不可**使用來源網站的 `Spot.id` 作為應用程式主鍵。

### 4.3 GeoJSON — `output/temples.geojson`

依計畫 §5/§6，**只**放地圖渲染與互動需要的屬性，不含詳細資料。

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "id": "temple-001",
      "geometry": {
        "type": "Point",
        "coordinates": [134.502972, 34.159474]
      },
      "properties": {
        "id": "temple-001",
        "type": "temple",
        "number": 1,
        "name_ja": "霊山寺",
        "name_en": "Ryouzen-ji",
        "name_kana": "りょうぜんじ"
      }
    }
  ]
}
```

規則：

- 座標順序是 **`[longitude, latitude]`**（GeoJSON 標準）。
- `properties` 固定 5 個欄位：`id`、`type`（固定 `"temple"`）、`number`、`name_ja`、`name_en`、`name_kana`。
- **不要**放入 `history`、`rekishiyurai_ja/en`、`honzon` 等大欄位。詳細資料由 `id` 到
  SQLite（`henro.db`，尚未建置）查詢。

## 5. 詳細資料與地圖資料分離（計畫 §5、§8、§9）

- PMTiles 只放地圖屬性（= GeoJSON properties 那 5 個欄位）。
- 完整中繼資料（歷史、電話、宗派、本尊、地址、宿坊、圖片）放 SQLite / Room。
- Runtime 流程：map marker（PMTiles）→ 點擊 → 用 `id`（如 `temple-088`）查 SQLite → 詳細頁。

## 6. 注意事項

- 來源資料最後更新約為 2016 年，寺廟本體資料穩定，但若未來加入 benches / cycle
  stands 等設施 POI，需視為補充資料，除非另行驗證，否則不應視為當前狀態。
- 若之後要加入 benches / stands / toilets 等 POI：
  1. 修改 `extract_henro.py` 同時輸出 `benches` / `stands` 陣列到 `source/seichijunrei/`。
  2. 依計畫 §14 各自建 normalized model 與 GeoJSON，輸出到 `output/`。
  3. 每種 POI 一個獨立 layer（`henro_benches`、`henro_cycle_stands` …），勿混入 temple 層。
- `source/` 下的檔案改動過後不應再手動編輯；要更新資料就重新跑 pipeline。

## 7. 產出清單

執行完 3 個 script 後應得到：

```text
source/seichijunrei/spots.json     # 88 筆（原始）
output/temples.json                # 88 筆（canonical）
output/temples.geojson             # 88 features（地圖用）
```
