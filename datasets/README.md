# 地圖資料來源

每個來源的原始資料、產出、程式、測試與文件都實際存放在自己的資料夾。
所有命令由 repo 根目錄執行；Python CLI 改為 `python3 -m datasets.<來源>`。

| 資料夾 | 來源／用途 | 程式入口 |
|---|---|---|
| [osm](osm/README.md) | OpenStreetMap 底圖、hiking relations、住宿 | **已一鍵化**：`python3 -m datasets.osm`（自動下載／更新→建置→驗證）；手動檔用 `--local` |
| [gsi](gsi/README.md) | 國土地理院 DEM、高程、等高線、Terrain-RGB | **已一鍵化**：`python3 -m datasets.gsi`（四國更新檢查→手動 ZIP→建置→驗證）；本機檔用 `--local` |
| [seichijunrei](seichijunrei/README.md) | 聖地巡礼網站的 canonical 88 札所與詳細內容 | **已一鍵化**：`python3 -m datasets.seichijunrei`（下載→JSON／GeoJSON／SQLite／PMTiles→驗證；未變跳過） |
| [sekaiisan_henro](sekaiisan_henro/README.md) | 世界遺產協議會路線、札所、廁所、路由 graph | **已一鍵化**：`python3 -m datasets.sekaiisan_henro run`（更新→graph／區間／審閱→驗證；未變跳過） |
| [arukihenro_routes](arukihenro_routes/README.md) | ohenro.jp 步行遍路路線與 POI | **已一鍵化**：`python3 -m datasets.arukihenro_routes run`（HTML／KML 更新→驗證→JSON；未變不重發） |
| [mizutani_henro_map](mizutani_henro_map/) | 水谷卓也 Google My Maps 路線與 POI | `python3 -m datasets.mizutani_henro_map` |
| [shikoku_nature_trail](shikoku_nature_trail/) | 四國自然步道網站與 My Maps | `python3 -m datasets.shikoku_nature_trail` |
| [henroyado](henroyado/) | Henroyado 住宿；含 Google Maps 補座標快取 | `python3 -m datasets.henroyado` |
| [min88_lodging](min88_lodging/) | min88 住宿 | `python3 -m datasets.min88_lodging` |
| [henrohub](henrohub/) | Henro Hub release 路線與 graph | `scripts/` |
| [henro_helper](henro_helper/) | Henro Helper APK 路線與 POI | `reference/extract_routes.py` |
| [ohenro88](ohenro88/) | OHenro 88 APK 路線與 graph | `reference/build_reference.py`、`scripts/` |
| [ohenro_no_akari](ohenro_no_akari/) | 四國電力「遍路のあかり」網站路線 | `reference/build_web_reference.py` |
| [omotenashi_henro_inspection](omotenashi_henro_inspection/) | 遍路道點檢活動 KML archive | `python3 -m datasets.omotenashi_henro_inspection` |
| [info_pois](info_pois/) | 多來源統合 POI（衍生資料集） | `scripts/` |

## 資料夾約定

- `raw/`：下載的原始快照；保留原始內容，不手動修改。
- `output/`：該來源的 JSON、GeoJSON、SQLite、PMTiles 與產出報告。
- `reports/`：建置 log、metadata 與診斷報告。
- `docs/`：來源專屬操作文件與設計。
- `scripts/`、Python package 模組、`tests/`：來源專屬程式與測試。
- App 抽取來源的 `reference/`：原始 APK／bundle、抽取中間檔與抽取器。
- 按需要建立以上子目錄，沒有資料的階段不必建立空目錄。

Git 僅追蹤程式、設定、文件與小型測試 fixtures。各來源的 `raw/`、`output/`、
`reports/`，共用 `source/`、`output/`、`reports/` 及歷史地圖樣本均只保留本機，
不提交實際地圖資料；新 clone 需執行來源管線或手動提供輸入檔。

共用程式在根目錄 `scripts/`；跨來源 App manifest、字型圖示、route packs、
人工編輯成果在根目錄 `output/`。`work/` 是可重建的暫存工作區。
根目錄 `reference/` 保留共用設計及尚未確認來源的歷史樣本。

## 常用命令

```bash
python3 -m datasets.henroyado normalize
python3 -m datasets.sekaiisan_henro normalize
./datasets/osm/scripts/build-basemap.sh
./datasets/shikoku_nature_trail/scripts/build-shikoku-nature-trail.sh
cargo test --manifest-path datasets/gsi/gsi-dem/Cargo.toml
python3 -m unittest discover datasets/henroyado/tests
python3 scripts/build-app-map-manifest.py --version <version>
```

`map-preview/public/data/` 只提供穩定的 Web URL 連結；真實資料在上述來源目錄。
路線編輯器列出各來源的 `output/`，寫入仍集中在根目錄 `output/route-editor/`。
Docker Compose 同時掛載 `datasets/` 與共用 `output/`。

完整 schema、數量與資料用途見 [資料目錄](../docs/data_catalog.md)。

Henro Hub 的原始 release 檔先前位於暫存目錄，目前本機只保有衍生產出；
下次下載請存為 `henrohub/raw/planner.geojson`，再執行 `henrohub/scripts/build-henrohub-routes.py`。
