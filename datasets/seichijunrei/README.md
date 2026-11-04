# 聖地巡礼：88 札所一鍵管線

```bash
python3 -m pip install -r datasets/seichijunrei/requirements.txt
python3 -m datasets.seichijunrei
```

需要 Python 3.11+、Docker（daemon 可用）、`pmtiles` CLI。
沿用 `ohenro-elevation-visuals` image 的 tippecanoe；image 不存在時自動 build。

## 下載與更新

自動取得 <https://www.seichijunrei-shikokuhenro.jp/map/all>，該頁 JavaScript 的
`spots` 已含 88 寺的座標、名稱、電話、歷史、宗派、本尊等詳細內容。
不需逐寺爬頁，也不下載圖片；保留來源圖片路徑。

每次 `run`／`fetch` 都重新取得網頁，抽取 category 3 的 spots，先正常化並驗證
恰好 88 寺、編號 1–88、canonical ID、名稱與四國座標，再替換 `raw/spots.json`。
下載／解析／驗證失敗保留原檔；內容未變則不替換。舊檔存入
`raw/snapshots/<sha256>.json`。

## 產出

| `output/` 檔案 | 用途 |
|---|---|
| `temples.json` | 完整 canonical 資料，88 筆 |
| `temples.geojson` | 地圖 Point features，88 筆 |
| `content.sqlite` | `features` 表，88 筆完整 payload 與基本查詢欄位 |
| `shikoku-temples.pmtiles` | `temples` layer、z0–14，保留所有寺廟、不抽稀 |

PMTiles 屬性沿用 GeoJSON：`id`（`temple-001`…`temple-088`）、`type`、`number`、
`name_ja`、`name_en`、`name_kana`；null 屬性可能不進 MVT。來源 attribution 寫入 metadata。
獨立 PMTiles 尚未加入共用 App manifest；既有 App `temples` role 仍使用 GeoJSON。

使用新暫存目錄建置，檢查 JSON／GeoJSON／SQLite 一致性、SQLite integrity、
PMTiles 結構／attribution／zoom、z14 完整 88 IDs 與名稱編號，成功後才逐檔發布。
`reports/pipeline.json` 記錄來源 hash、建置設定／程式碼 hash、產出大小與 hash、
temple_count。輸入／設定／產出都未變就略過建置；缺失或損壞會重建。
逐檔替換不是四檔的單一交易；發布途中中斷需重跑。

## 分步、手動放檔與強制重建

```bash
python3 -m datasets.seichijunrei fetch     # 只抓來源並驗證
python3 -m datasets.seichijunrei build     # 使用本機來源；未變就跳過
python3 -m datasets.seichijunrei validate  # 驗證現有四份產出
python3 -m datasets.seichijunrei --local   # 略過網路來源更新
python3 -m datasets.seichijunrei --force   # 抓來源後強制重建
python3 -m datasets.seichijunrei build --force
```

網站無法取得時，把先前下載的 category 3 spots array 放到
`datasets/seichijunrei/raw/spots.json`，再用 `--local`。
支援 `--raw-dir`、`--output-dir`、`--reports-dir`；例如隔離實跑：

```bash
python3 -m datasets.seichijunrei --raw-dir /tmp/opencode/temples-check/raw \
  --output-dir /tmp/opencode/temples-check/output \
  --reports-dir /tmp/opencode/temples-check/reports
```

Docker 同名 image／外部工具版本更新不會自動偵測，需 `--force`。
資料與報告皆不提交 Git。更新正式資料後，視需要重建統合 POI 與共用 App manifest。

```bash
python3 -m unittest discover datasets/seichijunrei/tests
```

Schema 詳見 [docs/henro_data_pipeline.md](docs/henro_data_pipeline.md)。

2026-11-04 完整下載／建置實跑通過：88 寺、309 tiles，四種產出全部驗證成功；
測試產出在 `/tmp/opencode/temples-check/output/`，正式資料未替換。
24 項測試（SQLite 20、管線 4）通過。
