# 四國遍路 Android App：PMTiles 地圖資料管線實作計畫

## 1. 目標

本專案採用兩條獨立的地圖資料管線：

```text
shikoku-latest.osm.pbf
        |
        +--> Protomaps Basemaps profile
        |         |
        |         +--> shikoku-basemap.pmtiles
        |
        +--> Custom Henro Planetiler profile
                  |
                  +--> shikoku-henro.pmtiles
```

Android / MapLibre 端同時載入：

```text
MapLibre
├── basemap source
│   └── shikoku-basemap.pmtiles
├── henro source
│   └── shikoku-henro.pmtiles
└── user GPS track
```

核心原則：

* 通用底圖與遍路專用資料分離。
* 兩份 PMTiles 可以使用同一份 OSM PBF 作為來源。
* Basemap 優先使用 Protomaps Basemaps 官方 Planetiler profile。
* 遍路資料使用獨立的自訂 Planetiler profile。
* 所有產出都必須可重建，不直接手動修改 PMTiles。
* 第一版先確保資料正確輸出，再處理進階 geometry merge。

---

# 2. 本階段範圍

## 2.1 要完成

* 從 `shikoku-latest.osm.pbf` 建立 `shikoku-basemap.pmtiles`。
* 驗證 Protomaps Basemap 的主要 source layers。
* 建立獨立的 Henro Planetiler profile。
* 從 OSM `route=hiking` relations 抽取路線資訊。
* 建立 `henro_routes` source layer。
* 使用 OSM relation `13653654` 作為第一個 smoke test。
* 建立可重複執行的 build scripts。
* 建立 PMTiles validation scripts。
* 撰寫 Henro layer schema 文件。

## 2.2 暫時不做

* Android UI。
* MapLibre Android 整合。
* GPS tracking。
* turn-by-turn routing。
* 完整寺院資料。
* 完整住宿、補給、廁所等 POI schema。
* 自動將 relation ways merge 成單一 LineString。
* 人工修正 OSM 路線。

---

# 3. 建議目錄結構

```text
shikoku-map-data/
├── README.md
├── AGENTS.md
│
├── source/
│   └── shikoku-latest.osm.pbf
│
├── basemaps/
│   └── protomaps-basemaps/
│
├── output/
│   ├── shikoku-basemap.pmtiles
│   ├── shikoku-henro.pmtiles
│   └── temples.geojson
│
├── henro/
│   ├── pom.xml
│   ├── src/
│   │   └── main/
│   │       └── java/
│   ├── schema.md
│   ├── scripts/
│   │   ├── extract_henro.py
│   │   ├── normalize_henro.py
│   │   └── generate_geojson.py
│   └── data/
│       ├── raw/seichijunrei/spots.json
│       └── normalized/temples.json
│
├── scripts/
│   ├── build-basemap.sh
│   ├── build-henro.sh
│   ├── inspect-pmtiles.sh
│   └── validate.sh
│
└── reports/
    ├── basemap-metadata.txt
    └── henro-metadata.txt
```

不要修改：

```text
source/shikoku-latest.osm.pbf
```

它應視為 immutable input。

---

# 4. Phase 1：建立 Shikoku Basemap

## 4.1 使用技術

使用：

* OpenStreetMap PBF
* Planetiler
* Protomaps Basemaps profile
* PMTiles

資料流：

```text
shikoku-latest.osm.pbf
        ↓
Protomaps Basemaps profile
        ↓
Planetiler
        ↓
shikoku-basemap.pmtiles
```

---

# 5. Basemap 環境需求

安裝：

```bash
sudo apt update

sudo apt install -y \
  openjdk-21-jdk \
  maven \
  git
```

確認：

```bash
java -version
mvn -version
```

至少需要：

```text
Java 21+
Maven
```

---

# 6. Clone Protomaps Basemaps

```bash
git clone https://github.com/protomaps/basemaps.git
```

進入：

```bash
cd basemaps/tiles
```

`tiles/` 是 Protomaps Basemaps 的 Planetiler profile 專案。

它負責：

```text
OSM tags
   ↓
分類 / 過濾 / schema mapping
   ↓
vector tile source layers
```

例如：

```text
natural=water
→ water

highway=footway
→ roads

building=yes
→ buildings
```

---

# 7. Build Protomaps Planetiler Profile

執行：

```bash
mvn clean package
```

完成後應在：

```text
target/
```

看到類似：

```text
protomaps-basemap-*-with-deps.jar
```

不要在 automation script 中硬編碼完整版本號。

可以找到：

```bash
JAR=$(find target -name '*-with-deps.jar' | head -n 1)
```

但必須確認只有一個符合項目。

---

# 8. 準備 Shikoku OSM input

建立：

```bash
mkdir -p data/sources
```

複製：

```bash
cp /path/to/shikoku-latest.osm.pbf \
  data/sources/shikoku.osm.pbf
```

最後應是：

```text
basemaps/
└── tiles/
    ├── data/
    │   └── sources/
    │       └── shikoku.osm.pbf
    └── target/
```

---

# 9. Build Shikoku Basemap

執行：

```bash
java -Xmx8g \
  -jar target/protomaps-basemap-HEAD-with-deps.jar \
  --area=shikoku \
  --download \
  --force
```

如果實際 JAR 名稱不同，使用實際產出的 `*-with-deps.jar`。

## `--area=shikoku`

代表使用：

```text
data/sources/shikoku.osm.pbf
```

## `--download`

會下載 Basemap profile 另外需要的 supporting datasets，例如：

```text
Natural Earth
land polygons
water polygons
language data
feature ranking data
```

不是重新下載 Shikoku OSM。

## `--force`

允許覆蓋既有 output。

---

# 10. Basemap 產出

預期得到：

```text
shikoku.pmtiles
```

將它整理到：

```text
output/shikoku-basemap.pmtiles
```

例如：

```bash
mkdir -p output

mv shikoku.pmtiles \
  output/shikoku-basemap.pmtiles
```

實際路徑可以依 repository 結構調整。

---

# 11. Basemap 驗證

至少檢查：

```bash
pmtiles show \
  output/shikoku-basemap.pmtiles
```

驗證：

* PMTiles 可正常解析。
* 檔案不是 0 bytes。
* Bounds 正確覆蓋四國。
* min zoom / max zoom 合理。
* 地圖可在 PMTiles / Protomaps viewer 中開啟。

主要檢查 source layers：

```text
roads
water
buildings
places
pois
```

特別檢查徒步 App 會需要的資料。

例如 `roads`：

```text
path
footway
steps
track
```

以及 POI：

```text
toilets
shelter
drinking_water
convenience
station
bus_stop
```

注意：

> OSM PBF 有某個 tag，不代表 Protomaps Basemap 一定會把它保留下來。

因此必須實際 inspect 最終 PMTiles schema。

---

# 12. 不要修改 Basemap 來塞 Henro 資料

Basemap 的責任是：

```text
道路
水域
建築
土地利用
地名
一般 POI
```

不要因為需要遍路路線，就直接修改 Protomaps Basemap：

```text
roads
+
henro route metadata
+
temple-specific logic
+
henro guidepost logic
```

這會讓 Basemap 與產品邏輯混在一起。

正確方式：

```text
Basemap
+
獨立 Henro overlay
```

---

# 13. Phase 2：建立 Henro Planetiler Profile

資料流：

```text
shikoku-latest.osm.pbf
        ↓
Custom Henro Planetiler Profile
        ↓
shikoku-henro.pmtiles
```

這個 profile 應該是一個獨立 Java / Maven 專案。

不要直接 fork Protomaps `tiles/` 後塞一堆 Henro logic。

---

# 14. Henro Profile v1 目標

第一版只處理：

```text
OSM route relations
```

主要條件：

```text
type=route
route=hiking
```

例如：

```text
relation 13653654

type=route
route=hiking
network=nwn
name=四国遍路 1番札所霊山寺~2番札所極楽寺
alt_name=遍路道
```

這種 relation 本身通常包含很多：

```text
way A
way B
way C
way D
```

我們需要保留：

> 這些 ways 屬於哪一個 hiking relation。

---

# 15. Planetiler relation 處理概念

OSM route relation 不能單純在處理每一條 way 時看它自己的 tags。

因為 way 本身可能只有：

```text
highway=footway
surface=gravel
```

但：

```text
它是不是遍路路線
```

是存在 relation 裡。

因此流程需要：

```text
第一遍
    ↓
讀取 OSM relations
    ↓
保存 relation metadata
    ↓
保存 relation member relationship

第二遍
    ↓
處理 ways
    ↓
知道某個 way 屬於哪些 relations
    ↓
輸出 henro_routes
```

Planetiler 提供 relation preprocessing 機制處理這種需求。

---

# 16. Henro Profile pseudocode

以下只是設計方向。

實際 API 名稱應以目前 Planetiler 版本為準。

```java
class HenroProfile implements Profile {

    preprocessOsmRelation(relation) {

        if (
            relation.getTag("type").equals("route") &&
            relation.getTag("route").equals("hiking")
        ) {
            return relationMetadata;
        }
    }

    processFeature(sourceFeature, features) {

        if (sourceFeature is OSM way) {

            memberships =
                getRelationMemberships(sourceFeature);

            for (membership : memberships) {

                if (membership is target hiking relation) {

                    features
                        .line("henro_routes")
                        .setAttr(
                            "relation_id",
                            membership.relationId
                        )
                        .setAttr(
                            "name",
                            membership.name
                        )
                        .setAttr(
                            "network",
                            membership.network
                        )
                        .setAttr(
                            "route",
                            "hiking"
                        );
                }
            }
        }
    }
}
```

Agent 不應照抄 pseudocode。

先查看：

* Planetiler current Profile API
* relation preprocessing API
* Planetiler example projects

再實作。

---

# 17. Henro PMTiles v1 Schema

## Layer

```text
henro_routes
```

Geometry：

```text
LineString
```

第一版不需要 merge。

同一個 relation 可以有：

```text
50 個 member ways
```

就輸出：

```text
50 個 LineString features
```

MapLibre 一樣可以把它們畫成一條看起來連續的路線。

---

# 18. `henro_routes` 欄位

第一版建議：

```text
relation_id
name
ref
network
route
route_kind
```

## `relation_id`

來源：

```text
OSM relation ID
```

例如：

```text
13653654
```

這個一定要保存。

它是未來 debug OSM 資料非常重要的欄位。

---

## `name`

直接保存 relation：

```text
name=...
```

不要第一版就自行 parse。

---

## `ref`

如果 OSM 有：

```text
ref=...
```

則保存。

沒有就省略。

---

## `network`

保留：

```text
nwn
rwn
lwn
```

等原始值。

第一版不要自行改寫語意。

---

## `route`

例如：

```text
hiking
```

---

## `route_kind`

第一版可以：

```text
henro_candidate
```

原因是：

> `route=hiking` 不代表一定是四國遍路。

後續再分類：

```text
henro_main
henro_alternate
henro_connector
other_hiking
```

---

# 19. 不要一開始把所有 hiking route 都叫 Henro

Extraction 與 Classification 應該分開。

第一層：

```text
type=route
route=hiking
```

代表：

```text
Hiking route candidate
```

第二層才判斷：

```text
是不是 Shikoku Henro
```

正式判斷規則需要先盤點實際 OSM 資料。

可能需要參考：

```text
relation hierarchy
name
alt_name
name:en
ref
network
superroute
member relations
```

不要只寫：

```java
if (name.contains("四国遍路"))
```

然後當成正式規則。

---

# 20. Relation 13653654 Smoke Test

第一版必須使用：

```text
OSM relation 13653654
```

作為 smoke test。

驗證：

```text
shikoku-latest.osm.pbf
        ↓
Henro Profile
        ↓
shikoku-henro.pmtiles
```

最後至少應有：

```text
henro_routes feature

relation_id = 13653654
```

並且至少保留：

```text
name
network
route
```

如果 relation 中有多個 member ways：

```text
relation 13653654
├── way A
├── way B
├── way C
└── way D
```

PMTiles 可以是：

```text
henro_routes

feature A
  relation_id=13653654

feature B
  relation_id=13653654

feature C
  relation_id=13653654

feature D
  relation_id=13653654
```

這是完全可以接受的 v1 結果。

---

# 21. v1 不做 Geometry Merge

不要第一版就做：

```text
way A
+
way B
+
way C
+
way D
        ↓
一條完美 LineString
```

因為這會碰到：

```text
way direction
disconnected segments
alternate paths
shared segments
duplicate members
gaps
```

第一版：

```text
relation member ways
→ individual LineStrings
```

即可。

MapLibre rendering 不需要 geometry 先 merge。

---

# 22. 之後什麼時候才需要 Merge

如果未來需要：

```text
計算完整路線距離
GPX export
route progress
nearest position along route
navigation
```

才建立另外的 route-processing pipeline。

不要強迫：

```text
Rendering geometry
```

跟：

```text
Navigation route graph
```

完全共用同一資料結構。

---

# 23. 未來 Henro PMTiles Schema

後續可以逐步擴充：

```text
shikoku-henro.pmtiles
│
├── henro_routes
├── temples
├── henro_pois
├── guideposts
└── danger_sections
```

第一版只做：

```text
henro_routes
```

---

# 24. v1.1：Temples

之後先盤點 OSM 中 88 所寺院如何 tagging。

可能包含：

```text
amenity=place_of_worship
religion=buddhist
temple=*
name=*
```

也可能透過：

```text
relation
node
way
```

表示。

不要先假設所有 88 所札所 tag 結構一致。

建議 layer：

```text
temples
```

欄位：

```text
osm_id
name
name_en
temple_number
source
```

`temple_number` 必須有可靠 mapping 後才加入。

---

# 25. v1.2：Henro POI

候選：

```text
guidepost
shelter
drinking_water
toilets
convenience
rest_area
bus_stop
station
```

在新增 Henro layer 前先確認：

> Protomaps Basemap 是否已經有相同資料。

例如：

```text
toilets
shelter
convenience
```

如果 basemap 已經有，可能只需要 style 強調它，不一定需要重複放入 Henro PMTiles。

只有：

* Basemap 沒保留。
* Basemap 缺必要 attributes。
* 是 Henro 專屬 semantic。

才考慮加入：

```text
henro_pois
```

---

# 26. Build Script：Basemap

建立：

```text
scripts/build-basemap.sh
```

建議職責：

```bash
#!/usr/bin/env bash
set -euo pipefail

# Check Java 21+
# Check Maven
# Check source PBF
# Build Protomaps tiles profile
# Copy/symlink PBF into data/sources/shikoku.osm.pbf
# Run Planetiler
# Move result to output/
# Run pmtiles show
# Save metadata report
```

不要讓 Agent 每次手動打不同指令。

---

# 27. Build Script：Henro

建立：

```text
scripts/build-henro.sh
```

職責：

```bash
#!/usr/bin/env bash
set -euo pipefail

# Check Java / Maven
Build custom Henro profile
# Read source/shikoku-latest.osm.pbf
# Generate output/shikoku-henro.pmtiles
# Inspect PMTiles metadata
# Run relation 13653654 smoke test
```

---

# 28. Validation Script

建立：

```text
scripts/validate.sh
```

至少驗證：

```text
output/shikoku-basemap.pmtiles
output/shikoku-henro.pmtiles
```

存在且非空。

再驗證：

```text
PMTiles metadata readable
bounds valid
henro_routes layer exists
relation 13653654 exists
```

如果任何一項失敗：

```text
exit 1
```

讓 AI agent 或 CI 可以明確知道 build 沒完成。

---

# 29. PMTiles Inspection

安裝 PMTiles CLI 後：

```bash
pmtiles show \
  output/shikoku-basemap.pmtiles
```

以及：

```bash
pmtiles show \
  output/shikoku-henro.pmtiles
```

保存：

```text
reports/basemap-metadata.txt
reports/henro-metadata.txt
```

例如：

```bash
pmtiles show \
  output/shikoku-basemap.pmtiles \
  > reports/basemap-metadata.txt
```

---

# 30. Debug Henro Relation Pipeline

如果 relation 13653654 沒有出現，不要直接修改 filter 亂試。

按照下面順序檢查：

```text
1. shikoku-latest.osm.pbf
   是否真的包含 relation 13653654？

2. preprocessOsmRelation
   是否看到 relation？

3. 是否成功保存 relation metadata？

4. member ways
   是否取得 relation membership？

5. processFeature
   是否產生 henro_routes feature？

6. minzoom / filter
   是否把 feature 丟掉？

7. PMTiles
   是否真的包含 henro_routes？

8. 最後才檢查 viewer / MapLibre。
```

---

# 31. 建議 AI Agent 執行順序

## Task 1 — Repository setup

建立：

```text
source/
basemap/
henro/
scripts/
reports/
```

不要修改 source PBF。

---

## Task 2 — Basemap pipeline

完成：

```text
OSM PBF
→ Protomaps Basemap
→ shikoku-basemap.pmtiles
```

---

## Task 3 — Basemap validation

驗證：

```text
roads
water
buildings
places
pois
```

並特別記錄與徒步相關的 attributes。

---

## Task 4 — Henro Planetiler project

建立獨立 Maven project。

使用 Planetiler 官方 custom-profile examples 作為基礎。

---

## Task 5 — Hiking relation preprocessing

支援：

```text
type=route
route=hiking
```

保存 relation metadata。

---

## Task 6 — `henro_routes`

將 relation member ways 輸出：

```text
henro_routes
```

---

## Task 7 — Smoke test

確認：

```text
relation_id=13653654
```

至少出現在一個 output feature 中。

---

## Task 8 — PMTiles output

產生：

```text
output/shikoku-henro.pmtiles
```

---

## Task 9 — Schema documentation

建立：

```text
henro/schema.md
```

記錄：

```text
layer
geometry
attributes
source OSM tags
filter rules
min/max zoom
```

---

## Task 10 — Full validation

最後執行：

```bash
./scripts/validate.sh
```

只有全部通過才能視為完成。

---

# 32. Definition of Done

* [ ] `source/shikoku-latest.osm.pbf` 保持原始狀態。
* [ ] `shikoku-basemap.pmtiles` 可以從 script 重建。
* [ ] Basemap PMTiles 可正常顯示四國。
* [ ] `roads` 有徒步 path 類型。
* [ ] 主要 basemap source layers 正常。
* [ ] 建立獨立 Henro Planetiler profile。
* [ ] `shikoku-henro.pmtiles` 可從 script 重建。
* [ ] Henro PMTiles 中存在 `henro_routes` layer。
* [ ] Relation `13653654` 至少有一個 member way feature 被輸出。
* [ ] 該 feature 帶有 `relation_id=13653654`。
* [ ] relation name / network / route metadata 有被保留。
* [ ] Henro build 不修改 Protomaps Basemap profile。
* [ ] Basemap 與 Henro PMTiles 可以獨立更新。
* [ ] `henro/schema.md` 完成。
* [ ] `README.md` 記錄完整 build 方法。
* [ ] `scripts/validate.sh` 全部通過。

---

# 33. Agent Guardrails

AI agent 必須遵守以下規則。

### 不要 hard-code geometry

不可以因為 relation 13653654 是 smoke test，就人工建立它的座標。

資料必須來自：

```text
shikoku-latest.osm.pbf
```

---

### Smoke-test allowlist 可以，但要標記

第一版可以暫時：

```text
relation_id == 13653654
```

作為 pipeline 驗證。

但必須明確標註：

```text
temporary smoke-test rule
```

不能把它當正式 Henro classification。

---

### 不要把所有 hiking route 當 Henro

```text
route=hiking
```

只能代表：

```text
hiking candidate
```

不能代表：

```text
Shikoku Henro
```

---

### 不要修改 upstream Basemap profile 來塞 Henro logic

Henro profile 必須保持獨立。

---

### 不要假設 OSM tagging 一致

任何：

```text
name parsing
temple number parsing
route type inference
```

在沒有盤點實際資料以前，不應建立成正式 schema。

---

### 每次 profile 修改後都必須 rebuild + validate

至少：

```bash
./scripts/build-henro.sh
./scripts/validate.sh
```

---

### 以目前 Planetiler API 為準

本文件中的 Java code 都是 pseudocode。

若：

```text
Planetiler API
```

與文件不同，應：

1. 查目前官方 API / examples。
2. 使用當前 API。
3. 在 README 記錄 Planetiler 版本。
4. 不要為了符合 pseudocode 而使用 deprecated API。

---

# 34. 後續 Roadmap

完成目前版本後，再依序處理。

## v1.1

```text
Temples
```

## v1.2

```text
Henro POIs
```

## v1.3

```text
Henro relation classification

main route
alternate route
connector
other hiking
```

## v1.4

```text
Geometry QA

relation gaps
duplicate ways
incorrect directions
disconnected routes
```

## v1.5

```text
Android offline map package

PMTiles
style.json
sprites
glyphs/fonts
```

## v2

```text
route progress
GPX export
offline navigation
route deviation warning
```

---

# 35. 最終架構

最後我們希望資料層是：

```text
OpenStreetMap
      |
      +------------------------------+
      |                              |
      v                              v
Protomaps Basemap              Henro Profile
      |                              |
      v                              v
shikoku-basemap.pmtiles      shikoku-henro.pmtiles
      |                              |
      +--------------+---------------+
                     |
                     v
                  MapLibre
                     |
          +----------+----------+
          |                     |
      Basemap               Henro Overlay
                                |
                         User GPS Track
```

核心原則：

> **Basemap 負責「四國是什麼樣子」，Henro PMTiles 負責「四國遍路對這個 App 代表什麼」。**

