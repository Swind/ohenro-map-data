# OpenStreetMap：下載到最終產出

## 一鍵執行

從 repo 根目錄執行：

```bash
python3 -m datasets.osm
```

流程：檢查依賴 → 比對 Geofabrik checksum → 必要時下載四國 PBF →
編譯 Protomaps 與 Henro profiles → 建置底圖與 hiking overlay → 抽取住宿 →
驗證全部產出 → 發布至本來源的 `output/`。

**自動下載來源**：<https://download.geofabrik.de/asia/japan/shikoku.html>。
每次執行都檢查官方 `.md5`；未更新就略過 PBF 下載，仍重新建置產出。
舊 PBF 在替換前保存為 `raw/snapshots/<sha256>.osm.pbf`；下載失敗、checksum
不符或非 PBF 都不替換現有輸入。

## 第一次使用

系統需有 **Python 3.11+、Java 21+、Maven、git、bash、PMTiles CLI**。

```bash
python3 -m pip install -r datasets/osm/requirements.txt
# 若已有 Go，可用以下命令安裝 PMTiles CLI，並將 GOPATH/bin 加入 PATH：
go install github.com/protomaps/go-pmtiles@latest
```

支援 `pmtiles` 或 `go-pmtiles` binary。缺少工具時會列出錯誤並停止。
缺少 `basemaps/` 時會自動初始化 repo 固定版本的 submodule；已有 checkout
沿用目前版本。Maven 自動取得 Java 依賴。Planetiler 自動下載缺少的
Natural Earth、水陸邊界、landcover、qrank 等輔助資料，快取在 `basemaps/tiles/data/`。
首次建置需要網路與較多磁碟空間；底圖 JVM 預設最大 8GB RAM。

## 手動提供檔案／拆開執行

自動下載不可用時，把四國範圍的 OSM PBF 放到：

```text
datasets/osm/raw/shikoku-latest.osm.pbf
```

```bash
python3 -m datasets.osm --local   # 使用本機 PBF，略過上游更新檢查
python3 -m datasets.osm fetch     # 只下載／更新
python3 -m datasets.osm build     # 只從本機 PBF 建置、驗證並發布
python3 -m datasets.osm validate  # 只驗證現有產出
```

`--local` 只控制 PBF 來源；首次 Maven／Planetiler 輔助資料仍可能需要網路。
可用 `--pbf PATH` 指定手動檔案；`run` 預設會把該路徑更新為 Geofabrik 四國資料，
要保留自備輸入請使用 `--local` 或 `build`。

測試或獨立產出：

```bash
python3 -m datasets.osm --pbf /tmp/opencode/osm-check/shikoku.osm.pbf \
  --output-dir /tmp/opencode/osm-check/output \
  --reports-dir /tmp/opencode/osm-check/reports
```

## 最終產出與驗證

| 檔案（相對本目錄） | 內容 |
|---|---|
| `output/shikoku-basemap.pmtiles` | Protomaps 通用底圖，OSM 道路／建物／POI 等 |
| `output/shikoku-henro.pmtiles` | hiking relations overlay，`henro_routes` layer |
| `output/lodging.geojson` | OSM 住宿 Point features |
| `output/lodging-report.json` | 住宿數量、分類、缺值與重複候選 |
| `reports/pipeline.json` | PBF SHA-256、Protomaps commit、產出大小／SHA-256、住宿數量 |
| `reports/*-build.log`、`*-metadata.txt` | Planetiler build log 與 metadata |

驗證 PMTiles 結構、必需 layers、四國 bounds、既有 relation 13653654 smoke test，
以及住宿 geometry／ID 唯一性／數量 accounting。所有階段在暫存輸出目錄完成，
全部驗證成功後才逐檔 atomic replace；這是逐檔替換，不是四檔的單一交易。
原有單獨建置腳本仍可使用，但整組驗證後發布請使用本入口。
入口會鎖定本來源的建置，避免兩個工作同時使用 Planetiler 的共用暫存目錄。

Henro overlay 的 Planetiler profile 設定 z0–14，但低 zoom 的短線可能被省略；
新管線依實際 tile zoom 範圍校正 PMTiles header，再執行嚴格驗證。舊版產出可能
因 header 宣告 z0、實際由 z5 開始而無法通過 `validate`，用 `build` 重建即可。

跨來源的統合 POI 與 App manifest 為後續管線：更新 OSM 後，要更新統合 POI
時執行 `datasets/info_pois/scripts/build-info-pois.sh`；發布 App 包前重新產生
`scripts/build-app-map-manifest.py --version <新版本>`，讓大小與 checksum 對上新檔。
更新資料數量時同步維護 `docs/data_catalog.md`。

## 測試

```bash
python3 -m unittest discover datasets/osm/tests
```

2026-11-04 完整實跑通過：Geofabrik 最新 PBF → 兩份 PMTiles → 1,349 個住宿點
（0 warnings）→ 嚴格驗證與發布。測試產出放在 `/tmp/opencode/osm-check/`，
repo 的正式 `output/` 未套用這次更新；6 項 regression tests 全部通過。

住宿 schema 詳見 `docs/lodging_data_pipeline.md`；hiking schema 見 `henro/schema.md`。
