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
| [henro_helper](#henro-helper-一鍵更新) | Henro Helper APK 路線與 POI | **已一鍵化**：`python3 -m datasets.henro_helper`（APKPure 更新→ARM64 靜態抽取→驗證發布；未變跳過） |
| [ohenro88](ohenro88/) | OHenro 88 APK 路線與 graph | `reference/build_reference.py`、`scripts/` |
| [ohenro_no_akari](ohenro_no_akari/) | 四國電力「遍路のあかり」網站路線 | `reference/build_web_reference.py` |
| [omotenashi_henro_inspection](omotenashi_henro_inspection/docs/omotenashi_henro_inspection_source.md) | 遍路道點檢活動覆蓋（非通行保證） | **已一鍵化**：`python3 -m datasets.omotenashi_henro_inspection`（官方頁發現 KML→快照→GeoJSON／provenance→驗證；未變跳過） |
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

## Henro Helper 一鍵更新

```bash
python3 -m datasets.henro_helper                  # 查最新版、下載、抽取及驗證發布
python3 -m datasets.henro_helper fetch            # 僅更新已驗證 APK/XAPK 快照
python3 -m datasets.henro_helper run --local      # 使用本機 current 快照
python3 -m datasets.henro_helper build            # 離線來源建置
python3 -m datasets.henro_helper validate         # 產出 hash／schema／accounting 驗證
python3 -m datasets.henro_helper run --force      # 強制重建（仍檢查遠端更新）
python3 -m unittest discover datasets/henro_helper/tests
```

需要 Python 3.11+、`curl`、`git`。Blutter 使用固定 revision，自動下載至
`work/henro-helper-tools/`，Python 依賴裝在其獨立 venv，不修改系統環境。
Linux 主機另需 g++ >=13（或設定 `CXX` 使用 clang++ >=16）、cmake、ninja、
pkg-config、libicu-dev、libcapstone-dev、python3-venv；缺少主機建置依賴時使用
Docker 自動建置工具映像。首次執行會下載並編譯對應 Dart runtime；之後重用工具快取。
`--local`／`build` 只免除 APK 來源下載，工具未快取時仍需網路。
可用 `--raw-dir`／`--output-dir`／`--reports-dir`／`--tools-dir` 隔離執行。

套件為 `com.henrohelper100.app`。採用 [EFF apkeep](https://github.com/EFForg/apkeep)
的 APKPure App API 與 headers，用 curl 傳輸；API 仍可能回傳多個 ABI，
先以 ZIP range 讀 XAPK manifest 選 ARM64。完整下載後檢查來源 SHA1、ZIP CRC、
package/version 與兩個 ARM64 ELF，再保存 `raw/snapshots/<sha256>/`、更新
`raw/current.json`。相同已驗證版本不重抓完整 archive；保留歷史來源。

只靜態抽取 `libapp.so`／`libflutter.so`，不安裝或執行 App。來源、抽取程式與
全部產出 hash 未變就跳過建置。全部 GeoJSON 驗證成功才逐檔 atomic replace，
最後寫 `reports/pipeline.json`；**不是跨檔交易**，中斷後重跑修復。
網頁挑戰／API schema 改變或來源損壞會失敗，不用 HTML 冒充 APK、不覆蓋有效產出。
來源 SHA1／本機 SHA256／CRC 是完整性檢查，**不是開發者簽章驗證**。
APKPure 僅供研究／個人靜態分析，App 資料非官方引導線，未加入正式 App manifest。
產出位置、欄位與來源記錄 accounting 見 [資料目錄](../docs/data_catalog.md)。
