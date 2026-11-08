# Henro Hub (henro.app) 資料調查與比較分析

日期：2026-09-07
狀態：**靜態分析（Phase A）**，僅下載 + 量化比對，未整合進管線。

## 1. 概況

`https://hub.henro.app`（= `henro.app`）是商業化 PWA（Henro Hub，含 free/premium tier）。
其路線資料透過公開 asset 端點釋出（無認證），release channel 機制：

- channel：`https://assets.henro.app/routes/channels/beta.json`
- 本次 release：`henro-route-network-20260903-1358`（2026-09-03 產生，schema_version 1.2.0）
- POI 走 Supabase REST：`https://agbjsmrsvxkaxdyrscjg.supabase.co/rest/v1/v_pois_lovable`
  （anon key 直接從前端 bundle 讀出，3286 筆）

## 2. 資料結構

### 路線網路（`planner/route.planner.geojson`，15.8MB，1884 features）

| 欄位 | 值 |
|---|---|
| 總長 | ~2733 km（union） |
| route_set_ids | henro-network 1884 / shikoku-88 775 / bekkaku-20 152 / okunoin 16 |
| route_role | canonical_shikoku88 770 / unique_alternative 1041 / transition_connector 47 / continuity_fallback 26 |
| 作者群 | `hrn_*`（Henro Hub 自家數位化）1024 / `shikoku88-*` 466 / `hh26_*`（Henro Helper）394 |
| 附帶欄位 | elevation min/max/ascent/descent、road class、road stress、tunnel 修正、OSM 比對 metadata |

### Planner edges（`routing.edge-metadata.json`，5.5MB）

299,574 條 planner edge，逐邊帶 OSM highway / bridge / tunnel / steps / surface / road stress /
osm_match_status（matched），並提供 edge_start/edge_end（對齊 planner geometry 的 index range）。

### Sections（`sections/…/definitions.json` + `traversals.json`）

272 個 section（T_a→T_b 區間），含 default_distance_m、open/closed、方向（clockwise 一致性檢查）、
traversal steps（feature id + from/to measure + 正向/反向）。85/87 個相鄰 88 區間有 cover
（缺 72→73、76→77），另有 88→1 閉環與 bekkaku/okunoin 接點。

### Thematic（`thematic/`）

elevation / pilgrim_way / road_stress / slope / surface 五種視覺化（GeoJSON + PMTiles，z8-15）。

### POI（Supabase，3286 筆）

category：Lodging 941 / POI 1989 / Spiritual 356。
含 bus / train / konbini / onsen / toilet / supermarket / michi-no-eki / viewpoint 等，
附多語名稱、地址、Google rating、amenities、pilgrimage_sets（shikoku_88 / bekkaku_20 /
okunoin / fudo_36 / shin_shikoku / bangai…）。

## 3. 與本 repo 現有資料的比較

### 3.1 路線覆蓋（20m buffer，henrohub 被 repo 來源覆蓋的 %）

| repo 來源 | 覆蓋 henrohub % | repo 總長 |
|---|---|---|
| henro-helper（已抽自 Henro Helper APK） | **86.2%** | 2576 km |
| sekaiisan（88sekaiisan 協議會） | 41.3% | 1424 km |
| arukihenro（ohenro.jp 手繪） | 43.2% | 1551 km |
| ohenro88（App 自身路線） | 33.6% | 1041 km |
| ohenro-no-akari（四國電力） | 42.3% | 1237 km |
| **以上任一來源** | **93.6%** | — |

**henrohub 完全未被任何 repo 來源覆蓋（20m）：~174 km（6.4%）**。

### 3.2 作者群細分

| 作者群 | 條數 | 長度 | henro-helper 覆蓋 | 未被任何 repo 覆蓋 |
|---|---|---|---|---|
| `hh26_*`（Henro Helper） | 394 | 497 km | 97.8% | 6.6 km（1.3%） |
| `shikoku88-*`（Hub 自家 88 線） | 466 | 578 km | 94.7% | 3.7 km（0.7%） |
| `hrn_*`（Hub 自家） | 1024 | 1658 km | 79.7% | **163.8 km（9.9%）** |

- `hh26_*` 的 297/394 條與 repo henro-helper 幾何差 <1m（**幾乎同一份**）。
- `hrn_*` 未被覆蓋的 164 km 集中在：**canonical_shikoku88 65 條 + unique_alternative 99 條**，
  多為 red/black（繁忙道路）與 bekkaku-20 繞行，地理上偏 Ehime 西側（~132.6-133.0）與香川 bekkaku 帶。
  這是最「新」的部分，但**大多是 alternative，非官方主線**。

### 3.3 Section 距離與 sekaiisan 對照

- henrohub 272 sections 的 default_distance_m 中位數 ~6.6 km。
- 與 repo `SEC_*`（sekaiisan 官方引導線）比對：部分區間高度一致（如 T1→T2 1317m vs 1306m、
  T84→T85 5528m vs 5515m），但不少區間 ratio 差異大（如 T36→T37、T26→T27）——
  反映 henrohub 常走「較短的替代/徒步線」，而 sekaiisan 官方線較長，**兩者是不同取徑，非同一路線**。

### 3.4 POI

| 比對 | 數量 |
|---|---|
| henrohub POI 總數 | 3286 |
| 50m 內有 repo temples / henro-helper-pois | 100 / 1399 |
| 50m 內有 repo min88 lodging | 528 |
| 50m 內有 repo henroyado lodging | 487 |
| 200m 內未被**任何** repo POI 覆蓋 | ~1016（其中 Lodging 339/941） |
| shikoku_88 編號寺廟 POI | 61 / 88（repo `temples.geojson` 有完整 88） |

henrohub POI 對 repo 的**附加價值主要在中盤**：bus/train/konbini/onsen/toilet/viewpoint 等
生活服務點（含 amenity、多語、Google rating），以及一組獨立的住宿點（339 筆與 min88/henroyado 不同）。

## 4. 授權風險（重要）

- `assets.henro.app` 為商業產品資產，**無 license / attribution / ODbL 標示**（與 OSM 不同）。
- 前端 bundle 僅見第三方函式庫 license（ISC/MIT），**未見資料本身的開放授權條款**。
- 資料中 `hh26_*` 部分源自 Henro Helper App 既有抽出（repo 已從 APK 合法抽取），但
  `hrn_*` / `shikoku88-*` / thematic / POI 為 Henro Hub 自家編譯成果，使用前需取得授權。
- 聯絡：JS bundle 中有 `johanesu@henro.app` / `admin@henro.app`。

## 5. 結論與建議

**重疊度高**：93.6% 的 henrohub 路線已被 repo 現有來源覆蓋；其獨特部分（~174 km）
多為**替代路線與自家數位化主線**，對 repo 的「88 主線/官方線」不是必要的補充。

**真正有參考價值的**：
1. **272 section 切法與方向** —— 與 repo `build-sections` 可對照（但取徑不同，僅供交叉驗證）。
2. **逐 planner-edge 的 OSM metadata + road stress + elevation** —— 可作為 henro 路線分級/高程的獨立先驗。
3. **POI 中段生活服務點**（bus/train/konbini/onsen/toilet）—— repo 目前沒有這樣完整的單一來源。

**建議**：
- 若要整併，需先向 Henro Hub 洽談授權（資料非開放授權）。
- 若僅做 QA/交叉驗證：可將其 section 距離與 road class 當作「soft reference」，不落地進管線。
- 不建議把 `hrn_*` alternative 路線當成官方主線引用（取徑不同、非官方）。

## 6. 附錄：下載檔案（`/tmp/opencode/henrohub/`）

- `planner.geojson` / `routing.edge-metadata.json` / `elevation.profile.json`
- `sections-{definitions,manifest,feature-sections,traversals}.json`
- `thematic/*.preview.geojson`、`thematic/{pilgrim_way,road_stress,surface}.web.geojson`
- `poi-all.json`（3286 筆全欄位）
- 分析腳本：`compare_routes.py` / `compare_groups.py` / `compare_pois.py` / `find_uncovered.py`

## 7. 更新操作（不改寫上述歷史調查）

```bash
python3 -m datasets.henrohub                  # beta channel → 驗證 release → 全部衍生產出
python3 -m datasets.henrohub fetch            # 僅更新已驗證的 immutable snapshot
python3 -m datasets.henrohub build            # 本地 current snapshot → routes + graph + PMTiles
python3 -m datasets.henrohub validate         # 檢查發布雜湊、schema、幾何及 accounting
python3 -m datasets.henrohub --local          # 不連網；未變則跳過
python3 -m datasets.henrohub --source /path/to/planner.geojson
```

可用 `--raw-dir`、`--output-dir`、`--reports-dir` 指定資料目錄；`--force` 僅供
run/build，`--source` 僅供 run/fetch 匯入原生 archived planner（舊的
`raw/planner.geojson` 也可明確指定）。正常 run 每次重新查詢公開 beta channel，
依 manifest 宣告路徑、SHA-256、bytes、feature count 下載和驗證，不固定舊 release。
原始 channel、manifest、planner、provenance 保存在 `raw/snapshots/<hash>/`，
驗證成功才原子更新 `raw/current.json`；錯誤／不完整下載不取代有效 current。

每次完整 build 先暫存並驗證 `henrohub-routes.geojson`、
`henrohub-plan-graph.json`、`shikoku-henrohub.pmtiles`，再逐檔原子發布，
最後寫入 `reports/pipeline.json`。輸入、程式設定和所有輸出雜湊未變則跳過；
中斷後報告與輸出不符會在下次重建。非阻塞 `.pipeline.lock` 防止同來源並行執行。
既有 `scripts/build-henrohub-pmtiles.sh` 改為完整本地 build 入口，避免單獨覆寫 tiles。
Graph 仍只納入 main + alternative；connector/fallback 僅保留在 GeoJSON/tiles。
切分 traversal edge 時保留並插值來源高程，synthetic join 本身仍可為 2D。

自動化不代表取得開放授權：所有產出仍限 **personal-use**，保留 Henro Hub attribution；
不下載 Supabase POI，也不抓取本管線未使用的 thematic/section/profile 資產。
上述 2026-09-07 比較數字與觀察保留為歷史記錄，不代表後續 release 的即時結果。