# GSI：四國 DEM 更新檢查與一鍵建置

從 repo 根目錄執行：

```bash
python3 -m pip install -r datasets/gsi/requirements.txt
python3 -m datasets.gsi
```

需要 Python 3.11+、Rust/Cargo、Docker（daemon 可用）、`pmtiles` CLI。
缺少 `ohenro-elevation-visuals` Docker image 時會自動用
`docker/Dockerfile.elevation` 建置；首次 Cargo 與 Docker build 需要網路。
請預留數十 GB 暫存空間。

## 資料取得

入口先查詢官方網站使用的 DEM catalog，固定 `region_codes=shikoku`，只包含
DEM5A／DEM5B／DEM5C／DEM10B。清單包含版本檔名、日期、大小與檔案 ID，
儲存在 `reports/updates.json`。網站查詢介面非保證穩定的公開 API；回應異常即停止。

**ZIP 下載需使用者登入官方網站**：
<https://service.gsi.go.jp/kiban/app/map/?search=dem>。
選「数値標高モデル」、最新資料、上述四種 DEM、地方區分「四国」，下載後放入：

```text
datasets/gsi/raw/
├── DEM5/5A/FG-GML-<mesh>-DEM5A-<date>.zip
├── DEM5/5B/FG-GML-<mesh>-DEM5B-<date>.zip
├── DEM5/5C/FG-GML-<mesh>-DEM5C-<date>.zip
└── DEM10B/FG-GML-<mesh>-DEM10B-<date>.zip
```

若下載的是外層批次包，先取出上述每 mesh ZIP；保留 ZIP，不需展開 XML。
更新同一 mesh/type 時，把舊 ZIP 移到 `raw/` **以外**的備份位置。
同一 mesh/type 多版本、錯放目錄、損壞 ZIP 均會拒絕建置。
官方清單與本機有差異時，列出待下載／待移走檔案並回傳 1，不繼續建置。
比較依據是**檔名版本**，官方未提供 checksum；本機 CRC 與 SHA-256 是另外的驗證。

2026-11-04 查詢：692 ZIP（5A 275／5B 98／5C 44／10B 275），
與當時本機檔名集合完全一致。

## 流程與產出

```text
官方四國清單比對 → 本機 ZIP CRC 檢查與 SHA-256
→ DEM5A > B > C merge + 獨立 DEM10B fallback
→ 256×256 高程 tiles
→ 完整 SQLite + DEM10-only SQLite
→ DEM10 VRT / COG → 20m 等高線 + Terrain-RGB
→ SQLite integrity / DEM10 subset / golden coordinates / PMTiles 驗證
→ 發布四份產出與 reports
```

產出在 `datasets/gsi/output/`：
- `shikoku-elevation.sqlite`：DEM5 + DEM10 fallback。
- `shikoku-elevation-dem10.sqlite`：同一組 tiles 的 DEM10 子集。
- `shikoku-contours.pmtiles`：20m 等高線。
- `shikoku-terrain.pmtiles`：Terrain-RGB，z6–14。

輸入 ZIP SHA-256、建置設定／程式碼，以及四份產出的大小與 SHA-256 都與上次
成功紀錄一致時，直接跳過重建（不需啟動 Cargo／Docker）。缺檔、內容變更或報告
缺失／損壞都會重建。舊版 `pipeline.json` 沒有 `build_config`，首次需重建一次。
實際建置使用新的暫存工作目錄，避免舊 mesh/tile 殘留；結束後自動清除。
所有產出驗證通過、確認輸入 SHA-256 未變後，才逐檔 atomic replace。
四檔發布不是單一交易；發布時若磁碟／程序中斷，需重跑整組。
`reports/pipeline.json` 記錄輸入 hash、build_config、產出 hash 與大小；另有 merge、tile、
validation JSON 和視覺化 log。入口鎖定避免同時建置。
需保存完整失敗紀錄時，將命令 stdout/stderr 重導到自己的 log 檔。

## 分步與離線操作

```bash
python3 -m datasets.gsi check     # 只查更新，無需 Cargo/Docker
python3 -m datasets.gsi --local   # 跳過官方清單，使用本機資料建置
python3 -m datasets.gsi build     # 同上
python3 -m datasets.gsi validate  # 驗證已發布四份產出
python3 -m datasets.gsi --force   # 查官方更新後強制重建
python3 -m datasets.gsi build --force  # 本機輸入強制重建

# 隔離完整實跑，不替換正式資料
python3 -m datasets.gsi --output-dir /tmp/opencode/gsi-check/output \
  --reports-dir /tmp/opencode/gsi-check/reports
```

`--raw-dir` 可指定另一份已整理的輸入。`--local`／`build` 不確認官方四國清單完整性，
請使用先前查核過的四國輸入；仍做 ZIP、版本重複與產出驗證。
預設仍查官方更新；`--force` 只強制重建，不略過更新檢查或下載需求。
建置設定包含等高線間距、terrain zoom、workers、Docker image 名稱及管線程式碼 hash。
外部工具版本／同名 Docker image 內容變更後請用 `--force`；不做增量 raster 更新。
資料與產出皆 gitignore，不提交 Git。發布 App 包前重建共用 manifest。

```bash
python3 -m unittest discover datasets/gsi/tests
cargo test --manifest-path datasets/gsi/gsi-dem/Cargo.toml
```

底層格式與 CLI 詳見 [gsi-dem/README.md](gsi-dem/README.md)。

## 完整實跑紀錄

2026-11-04：692 ZIP → 兩份 SQLite → 兩份 PMTiles → 發布至
`/tmp/opencode/gsi-check/output/` 全程成功。SQLite integrity、DEM10 子集一致性、
7/7 golden coordinates、等高線範圍／屬性、Terrain-RGB 與 PMTiles 結構驗證皆通過。
DEM5 10,836 tiles、DEM10 2,889 tiles；5 項管線測試與 55 項 Rust 測試通過。
本次使用隔離輸出，正式資料未替換。
