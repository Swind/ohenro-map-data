# 水谷遍路導覽圖 Pipeline

將水谷卓也先生的 Google My Maps KML 建置為個人離線使用的獨立 PMTiles overlay。
詳細設計、資料來源與發布限制見 `datasets/mizutani_henro_map/docs/mizutani-henro-map-pipeline-plan.md`。

## 使用限制

- 成品 metadata 固定標記 `usage=personal-use`。
- raw KML、normalized JSON、GeoJSON 與 PMTiles 均為 gitignored，不隨 repository 發布。
- 作者的「分享自由」文字不等同於離線封裝或再散布授權。公開 App 或網站發布前，必須取得作者對轉換、分類、離線封裝與再散布的明確書面許可。

## 前置需求

- Python 3
- Docker，及 `ohenro-elevation-visuals:latest` image
- `pmtiles` 或 `go-pmtiles` CLI
- `jq`（PMTiles tile smoke test）

## 初次建置

```bash
python3 -m datasets.mizutani_henro_map fetch
python3 -m datasets.mizutani_henro_map inspect
./datasets/mizutani_henro_map/scripts/build-mizutani-henro.sh
```

產出：

- `datasets/mizutani_henro_map/raw/snapshots/<sha256>/map.kml`：immutable raw snapshot。
- `datasets/mizutani_henro_map/raw/current.json`：目前 snapshot pointer。
- `datasets/mizutani_henro_map/output/mizutani-henro-map.json`：deterministic normalized data。
- `datasets/mizutani_henro_map/output/mizutani-henro-routes.geojson`、`datasets/mizutani_henro_map/output/mizutani-henro-pois.geojson`：tile input。
- `datasets/mizutani_henro_map/output/shikoku-mizutani-henro.pmtiles`：獨立 overlay。
- `reports/mizutani-henro-{build,metadata}.*`：build log 與 metadata。

PMTiles layers 為 `mizutani_henro_routes` 與 `mizutani_henro_pois`，zoom 0-14。

## 日常更新

```bash
./datasets/mizutani_henro_map/scripts/build-mizutani-henro.sh --update
```

此命令下載 KML 並比較 raw SHA-256：

- SHA 相同：輸出 `source unchanged`，不啟動 Docker、不重建 PMTiles。
- SHA 不同：保存新 snapshot、產生 `datasets/mizutani_henro_map/output/mizutani-henro-update-report.json`，再 normalize、verify、build。
- 任何 build 或 validation 失敗都不會替換現有 PMTiles。

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

`verify` 比對 raw、normalized 與 GeoJSON 的 Point、LineString 與 feature IDs。build 另驗證 PMTiles structure、layers、bounds、personal-use metadata，並以 GDAL MVT reader 從 z14 tile 讀回一條 route 和每個 category 的一筆 POI。
