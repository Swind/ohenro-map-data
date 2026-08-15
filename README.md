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
├── source/                    原始資料（immutable）：OSM PBF、seichijunrei spots.json
├── basemaps/                  Protomaps Basemaps repo（外部 git clone，勿放入自訂檔案）
├── henro/                     自訂 Henro Planetiler 專案（schema 見 henro/schema.md）
│   └── scripts/               遍路寺廟資料管線（extract / normalize / generate）
├── output/                    所有產出：temples.json、temples.geojson、兩份 PMTiles
├── scripts/                   build / validate 腳本
├── reference/                 計畫與操作文件
└── reports/                   build log 與 metadata 報告
```

遍路寺廟資料管線詳見 `reference/henro_data_pipeline.md`（更新資料時依該文件執行）。

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
