# 水谷遍路導覽圖 Pipeline

將水谷卓也先生的 Google My Maps KML 建置為個人離線使用的獨立 PMTiles overlay。
詳細設計、資料來源與發布限制見 `datasets/mizutani_henro_map/docs/mizutani-henro-map-pipeline-plan.md`。

## 使用限制

- 成品 metadata 固定標記 `usage=personal-use`。
- raw KML、normalized JSON、GeoJSON 與 PMTiles 均為 gitignored，不隨 repository 發布。
- 作者的「分享自由」文字不等同於離線封裝或再散布授權。公開 App 或網站發布前，必須取得作者對轉換、分類、離線封裝與再散布的明確書面許可。

## 前置需求

- Python 3
- `tippecanoe`，或 Docker 與 `ohenro-elevation-visuals:latest` image（缺少 image 時共用 helper 會建置）。
- `pmtiles` 或 `go-pmtiles` CLI。
- Python packages：`pmtiles`、`mapbox-vector-tile`、`mercantile`（讀回實際 z14 tiles）。

## 初次建置

```bash
python3 -m datasets.mizutani_henro_map
```

產出：

- `datasets/mizutani_henro_map/raw/snapshots/<sha256>/map.kml`：immutable raw snapshot。
- `datasets/mizutani_henro_map/raw/current.json`：目前 snapshot pointer。
- `datasets/mizutani_henro_map/output/mizutani-henro-map.json`：deterministic normalized data。
- `datasets/mizutani_henro_map/output/mizutani-henro-routes.geojson`、`datasets/mizutani_henro_map/output/mizutani-henro-pois.geojson`：tile input。
- `datasets/mizutani_henro_map/output/mizutani-henro-report.json`：來源、分類與 feature accounting。
- `datasets/mizutani_henro_map/output/mizutani-henro-update-report.json`：與上次發布來源的 diff；首次建置比較自身，首次遷移則保留有效既有 diff 的基準。
- `datasets/mizutani_henro_map/output/shikoku-mizutani-henro.pmtiles`：獨立 overlay。
- `datasets/mizutani_henro_map/output/mizutani-henro-routes.pmtiles`：provider route pack。
- `datasets/mizutani_henro_map/reports/pipeline.json`：來源、build config、全部輸出 SHA-256 與驗證摘要，最後才發布。

Overlay layers 為 `mizutani_henro_routes` 與 `mizutani_henro_pois`；provider pack 只有 `routes`，保留 `route_id`、`segment_id`。兩者均為 zoom 0–14、不簡化線條，provider pack 不啟用 drop-densest。

## 日常更新

```bash
python3 -m datasets.mizutani_henro_map
```

預設為 `run`，每次重新下載並驗證遠端 KML，不要求預先存在 `current.json`：

- 來源、設定、程式及所有輸出 size/SHA-256 都相同時才跳過；缺少任一 JSON 或 tile archive 都會重建。
- 新來源在語法、geometry、styles、Shikoku bounds 與 routes/POIs 完整性通過後才選為 current；不完整或錯誤回應不會取代有效 current。
- 所有 JSON、GeoJSON、diff 及兩份 PMTiles 先在同一 stage 產生並驗證；全部成功才逐檔 atomic replace，最後發布 pipeline report。建置失敗保留既有輸出。
- source-local `.pipeline.lock` 非阻塞鎖避免兩個更新互相覆蓋。若發布中斷，下次會依完整輸出 hashes 修復，不會誤判 unchanged。

```bash
python3 -m datasets.mizutani_henro_map fetch       # 只更新 raw
python3 -m datasets.mizutani_henro_map build       # 從 local current 建置
python3 -m datasets.mizutani_henro_map run --local # 同 build
python3 -m datasets.mizutani_henro_map build --force
python3 -m datasets.mizutani_henro_map validate    # 不下載；驗證已發布全部輸出
```

`--raw-dir`（舊名 `--data-dir`）、`--output-dir`、`--reports-dir` 可放在 command 前後。`--local` 只用於 run，`--force` 只用於 run/build。`MIZUTANI_IMAGE` 可指定 Docker image，會記入 build config。
舊 `build-mizutani-henro.sh` 只轉交 `build`，加 `--update` 則轉交 `run`，沒有第二套建置路徑。

Google endpoint 可能即使資料量未變仍回傳不同 raw SHA。這是依設計採用的 source identity；update report 可用 stable feature IDs 區分實際新增、移除或內容修改。

## 人工分類

`datasets/mizutani_henro_map/style_categories.json` 是受版控的 icon ID 分類表。解析優先序：

1. `style_overrides` 的完整 `styleUrl`。
2. `icons` 的 icon ID。
3. `unclassified` / `other` fallback。

目前 live source 的 79 個 icon IDs 已映射至 10 個 App categories：`temple`、`lodging`、`food`、`shop_supply`、`transport`、`wayfinding`、`warning_hazard`、`water_toilet_rest`、`experience_note`、`other`。來源新增 style 或 icon 時先執行 `inspect`，檢視固定前五個 samples 後再人工更新 mapping；不要用名稱規則自動猜測。

## 個別命令與驗證

```bash
python3 -m datasets.mizutani_henro_map inspect
python3 -m datasets.mizutani_henro_map normalize
python3 -m datasets.mizutani_henro_map export-map
python3 -m datasets.mizutani_henro_map verify
python3 -m datasets.mizutani_henro_map diff <old-sha256> <new-sha256>
python3 -m unittest discover datasets/mizutani_henro_map/tests
./scripts/validate.sh
```

`verify` 比對 raw、normalized 與 GeoJSON 的完整 schema、properties、分類及 geometry，不只計數。`validate` 另驗證全部輸出 hashes、diff、PMTiles structure、layers、bounds、personal-use/source metadata，並讀回 z14 的 route、每個 category 的一筆 POI 及 provider route，確認 consumer IDs 與分類。
